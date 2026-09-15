"""PDF 쪽 썸네일 격자. 클릭으로 쪽을 고르면 페이지 칸(StringVar)이 채워지고, 칸을 고치면 격자가 따라간다."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageTk

from pdf_pages import (
    THUMBNAIL_WIDTH,
    PdfPagesError,
    format_page_range,
    parse_page_range,
    pdf_page_count,
    render_page,
)

PLACEHOLDER_HEIGHT = 150
CELL_PADDING = 8
BORDER = 3
SELECTED_COLOR = "#2f6fdd"
IDLE_COLOR = "#d0d0d0"
PLACEHOLDER_COLOR = "#e6e6e6"
POLL_MS = 80
MISSING_RENDERER_MESSAGE = (
    "썸네일을 그리려면 pypdfium2가 필요합니다. "
    "python -m pip install -r requirements.txt 를 실행하세요. 페이지 칸 입력은 그대로 동작합니다."
)


class PagePicker(ttk.Frame):
    def __init__(self, master, pages_var: tk.StringVar, status_var: tk.StringVar | None = None) -> None:
        super().__init__(master)
        self.pages_var = pages_var
        self.status_var = status_var
        self.page_count = 0
        self._path: Path | None = None
        self._selected: set[int] = set()
        self._cells: list[tk.Frame] = []
        self._image_labels: list[tk.Label] = []
        self._photos: dict[int, ImageTk.PhotoImage] = {}
        # 캐시 키는 (절대 경로, 수정 시각). 합치기 목록에서 행을 오갈 때 다시 그리지 않는다.
        self._cache: dict[tuple[str, float], dict[int, Image.Image | None]] = {}
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._generation = 0
        self._writing = False  # 위젯이 스스로 pages_var를 쓸 때 추적 콜백을 건너뛴다
        self._columns = 1
        self._placeholder = ImageTk.PhotoImage(
            Image.new("RGB", (THUMBNAIL_WIDTH, PLACEHOLDER_HEIGHT), PLACEHOLDER_COLOR), master=self)
        self._build()
        pages_var.trace_add("write", self._on_pages_var_changed)

    # ----- 구성 -----

    def _build(self) -> None:
        self.canvas = tk.Canvas(self, highlightthickness=0, height=PLACEHOLDER_HEIGHT + 60)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.grid_frame = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind(
            "<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        # 두 탭에 피커가 하나씩 있으므로 마우스가 올라와 있을 때만 휠을 받는다.
        self.canvas.bind("<Enter>", lambda _event: self.canvas.bind_all("<MouseWheel>", self._on_wheel))
        self.canvas.bind("<Leave>", lambda _event: self.canvas.unbind_all("<MouseWheel>"))

    def _on_wheel(self, event: tk.Event) -> None:
        self.canvas.yview_scroll(-int(event.delta / 120), "units")

    def _on_canvas_resize(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)
        columns = max(1, event.width // (THUMBNAIL_WIDTH + 2 * (CELL_PADDING + BORDER)))
        if columns != self._columns:
            self._columns = columns
            self._relayout()

    def _relayout(self) -> None:
        for index, cell in enumerate(self._cells):
            cell.grid(row=index // self._columns, column=index % self._columns,
                      padx=CELL_PADDING, pady=CELL_PADDING)

    def _add_cell(self, number: int) -> None:
        cell = tk.Frame(self.grid_frame, highlightthickness=BORDER,
                        highlightbackground=IDLE_COLOR, highlightcolor=IDLE_COLOR)
        image_label = tk.Label(cell, image=self._placeholder, compound="center", text="")
        image_label.pack()
        number_label = tk.Label(cell, text=str(number))
        number_label.pack()
        for widget in (cell, image_label, number_label):
            widget.bind("<Button-1>", lambda _event, n=number: self.toggle(n))
        self._cells.append(cell)
        self._image_labels.append(image_label)

    def _clear_cells(self) -> None:
        for cell in self._cells:
            cell.destroy()
        self._cells = []
        self._image_labels = []
        self._photos = {}

    # ----- 공개 동작 -----

    def load(self, path: Path | None) -> None:
        """새 PDF의 쪽들을 자리표시자로 깔고 백그라운드에서 썸네일을 채운다. None이면 비운다.

        선택은 비운다. 현재 pages_var 값은 적용하지 않으므로 호출자가 load 뒤에 설정한다.
        (이전 파일의 페이지 지정이 새 파일에 맞지 않아 엉뚱한 오류가 뜨는 것을 막는다.)
        """
        self._generation += 1
        self._clear_cells()
        self._selected = set()
        self.page_count = 0
        self._path = None
        if path is None:
            return
        path = Path(path)
        self.page_count = pdf_page_count(path)
        self._path = path
        for number in range(1, self.page_count + 1):
            self._add_cell(number)
        self._relayout()
        self.canvas.yview_moveto(0)
        key = (str(path.resolve()), path.stat().st_mtime)
        images = self._cache.setdefault(key, {})
        self._thread = threading.Thread(
            target=self._render_all, args=(self._generation, path, self.page_count, images), daemon=True)
        self._thread.start()
        self.after(POLL_MS, self._drain)

    def toggle(self, number: int) -> None:
        """썸네일 클릭. 선택을 뒤집고 페이지 칸을 오름차순 압축 표기로 다시 쓴다."""
        if number in self._selected:
            self._selected.discard(number)
        else:
            self._selected.add(number)
        self._paint()
        self._writing = True
        try:
            self.pages_var.set(format_page_range(self._selected))
        finally:
            self._writing = False

    def selected_pages(self) -> set[int]:
        return set(self._selected)

    def is_rendering(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ----- 칸 → 격자 -----

    def _on_pages_var_changed(self, *_args) -> None:
        if self._writing or self.page_count == 0:
            return
        text = self.pages_var.get()
        if not text.strip():
            self._selected = set()
        else:
            try:
                self._selected = set(parse_page_range(text, self.page_count))
            except PdfPagesError as exc:
                self._report(str(exc))
                return
        self._paint()

    def _paint(self) -> None:
        for index, cell in enumerate(self._cells):
            color = SELECTED_COLOR if index + 1 in self._selected else IDLE_COLOR
            cell.configure(highlightbackground=color, highlightcolor=color)

    def _report(self, message: str) -> None:
        if self.status_var is not None:
            self.status_var.set(message)

    # ----- 백그라운드 렌더링 -----

    def _render_all(self, generation: int, path: Path, page_count: int,
                    images: dict[int, Image.Image | None]) -> None:
        """워커 스레드. Tk를 만지지 않고 큐에만 넣는다."""
        for number in range(1, page_count + 1):
            if generation != self._generation:
                return
            if number not in images:
                try:
                    images[number] = render_page(path, number)
                except ImportError:
                    self._queue.put((generation, None, MISSING_RENDERER_MESSAGE))
                    return
                except PdfPagesError:
                    images[number] = None
            self._queue.put((generation, number, images[number]))

    def _drain(self) -> None:
        """메인 스레드. 큐를 비우고, 워커가 아직 살아 있으면 다시 예약한다."""
        alive = self.is_rendering()  # 비우기 전에 확인해야 마지막 항목을 놓치지 않는다
        while True:
            try:
                generation, number, payload = self._queue.get_nowait()
            except queue.Empty:
                break
            if generation != self._generation:
                continue
            if number is None:
                self._report(payload)
            else:
                self._show_thumbnail(number, payload)
        if alive:
            self.after(POLL_MS, self._drain)

    def _show_thumbnail(self, number: int, image: Image.Image | None) -> None:
        if number > len(self._image_labels):
            return
        label = self._image_labels[number - 1]
        if image is None:
            label.configure(text="?")
            return
        photo = ImageTk.PhotoImage(image, master=self)
        self._photos[number] = photo
        label.configure(image=photo, text="")
