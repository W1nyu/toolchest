"""Simple Windows-friendly desktop UI for the local converter."""

from __future__ import annotations

import shutil
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from PIL import Image, ImageTk

from image_to_pdf import build_searchable_pdf
from image_to_text import OcrError, image_from_clipboard, image_to_text, load_image
from local_converter import ConversionError, convert
from web_to_pdf import WebPdfError, webpage_to_pdf


class ConverterApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("로컬 변환기")
        self.geometry("820x640")
        self.minsize(720, 560)
        self.input_path = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.target_format = tk.StringVar(value="mp3")
        self.overwrite = tk.BooleanVar()
        self.compress = tk.BooleanVar()
        self.quality = tk.StringVar(value="ebook")
        self.status = tk.StringVar(value="변환할 파일을 선택하세요.")
        self.web_url = tk.StringVar()
        self.web_output_dir = tk.StringVar(value=str(Path.cwd() / "output" / "pdf"))
        self.web_overwrite = tk.BooleanVar()
        self.web_include_source = tk.BooleanVar()
        self.web_status = tk.StringVar(value="웹페이지 주소를 붙여넣으세요. 본문과 본문 이미지만 PDF로 저장합니다.")
        self.image_info = tk.StringVar(value="이미지를 불러오거나 Ctrl+V로 붙여넣으세요.")
        self.image_status = tk.StringVar(value="한국어·영어 텍스트를 인식합니다.")
        self.current_image: Image.Image | None = None
        self.last_result = None
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.temp_image_path: Path | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        file_tab = ttk.Frame(self.notebook)
        web_tab = ttk.Frame(self.notebook)
        image_tab = ttk.Frame(self.notebook)
        self.notebook.add(file_tab, text="파일 변환")
        self.notebook.add(web_tab, text="웹 본문 PDF")
        self.notebook.add(image_tab, text="이미지 텍스트")
        self._build_file_ui(file_tab)
        self._build_web_ui(web_tab)
        self._build_image_ui(image_tab)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind_all("<Control-v>", self._on_paste_shortcut)
        self.bind_all("<Control-V>", self._on_paste_shortcut)

    def _build_file_ui(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="입력 파일").grid(row=0, column=0, sticky="w", pady=7)
        ttk.Entry(frame, textvariable=self.input_path).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(frame, text="파일 선택", command=self.choose_input).grid(row=0, column=2)
        ttk.Label(frame, text="변환 형식").grid(row=1, column=0, sticky="w", pady=7)
        formats = ["mp3", "mp4", "wav", "flac", "aac", "m4a", "ogg", "opus", "webm", "avi", "mkv", "mov", "pdf", "jpg", "png"]
        ttk.Combobox(frame, textvariable=self.target_format, values=formats).grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Label(frame, text="목록 외 형식도 직접 입력 가능").grid(row=1, column=2, sticky="w")
        ttk.Label(frame, text="출력 폴더").grid(row=2, column=0, sticky="w", pady=7)
        ttk.Entry(frame, textvariable=self.output_dir).grid(row=2, column=1, sticky="ew", padx=8)
        ttk.Button(frame, text="폴더 선택", command=self.choose_output).grid(row=2, column=2)
        ttk.Checkbutton(frame, text="같은 이름이면 덮어쓰기", variable=self.overwrite).grid(row=3, column=1, sticky="w", padx=8, pady=7)
        ttk.Checkbutton(frame, text="파일 용량 줄이기", variable=self.compress).grid(row=4, column=1, sticky="w", padx=8, pady=7)
        ttk.Label(frame, text="압축 품질").grid(row=4, column=2, sticky="w")
        ttk.Combobox(frame, textvariable=self.quality, values=["screen", "ebook", "printer"], width=12, state="readonly").grid(row=4, column=2, sticky="e")
        self.convert_button = ttk.Button(frame, text="변환 시작", command=self.start_conversion)
        self.convert_button.grid(row=5, column=1, sticky="e", padx=8, pady=18)
        ttk.Separator(frame).grid(row=6, column=0, columnspan=3, sticky="ew")
        ttk.Label(frame, textvariable=self.status, wraplength=660).grid(row=7, column=0, columnspan=3, sticky="w", pady=14)

    def _build_web_ui(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="웹페이지 주소").grid(row=0, column=0, sticky="w", pady=8)
        url_entry = ttk.Entry(frame, textvariable=self.web_url)
        url_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        url_entry.focus_set()
        ttk.Label(frame, text="PDF 저장 폴더").grid(row=1, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=self.web_output_dir).grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Button(frame, text="폴더 선택", command=self.choose_web_output).grid(row=1, column=2)
        ttk.Checkbutton(frame, text="같은 제목이면 덮어쓰기", variable=self.web_overwrite).grid(row=2, column=1, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(frame, text="PDF 첫 줄에 원본 URL 표시", variable=self.web_include_source).grid(row=3, column=1, sticky="w", padx=8, pady=6)
        self.web_button = ttk.Button(frame, text="본문 PDF 만들기", command=self.start_web_conversion)
        self.web_button.grid(row=4, column=1, sticky="e", padx=8, pady=18)
        ttk.Separator(frame).grid(row=5, column=0, columnspan=3, sticky="ew")
        ttk.Label(
            frame,
            text="광고·메뉴·댓글은 제외합니다. 로그인, 캡차 또는 자바스크립트 전용 페이지는 본문을 읽지 못할 수 있습니다.",
            wraplength=700,
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(14, 4))
        ttk.Label(frame, textvariable=self.web_status, wraplength=700).grid(row=7, column=0, columnspan=3, sticky="w", pady=4)

    def _build_image_ui(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(2, weight=1)
        frame.rowconfigure(3, weight=1)

        ttk.Button(frame, text="이미지 불러오기", command=self.choose_image).grid(
            row=0, column=0, sticky="w")
        ttk.Button(frame, text="클립보드에서 붙여넣기", command=self.paste_image).grid(
            row=0, column=1, sticky="w", padx=8)
        ttk.Label(frame, textvariable=self.image_info, wraplength=420).grid(
            row=0, column=2, sticky="w", padx=8)

        self.preview_label = ttk.Label(frame)
        self.preview_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=10)

        run_row = ttk.Frame(frame)
        run_row.grid(row=2, column=2, sticky="e")
        self.direct_pdf_button = ttk.Button(
            run_row, text="PDF로 바로 저장", command=self.start_direct_pdf)
        self.direct_pdf_button.pack(side="left", padx=(0, 8))
        self.image_button = ttk.Button(
            run_row, text="텍스트 추출", command=self.start_image_conversion)
        self.image_button.pack(side="left")

        self.image_text = scrolledtext.ScrolledText(frame, wrap="word", height=12)
        self.image_text.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=10)

        actions = ttk.Frame(frame)
        actions.grid(row=4, column=0, columnspan=3, sticky="w")
        ttk.Button(actions, text="전체 복사", command=self.copy_image_text).pack(side="left")
        ttk.Button(actions, text=".txt 저장",
                   command=lambda: self.save_image_text("txt")).pack(side="left", padx=8)
        ttk.Button(actions, text=".md 저장",
                   command=lambda: self.save_image_text("md")).pack(side="left")
        ttk.Button(actions, text="PDF 저장",
                   command=self.save_image_pdf).pack(side="left", padx=8)

        ttk.Label(frame, textvariable=self.image_status, wraplength=740).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=12)

    def choose_input(self) -> None:
        path = filedialog.askopenfilename(title="변환할 파일 선택", filetypes=[("모든 파일", "*.*")])
        if path:
            self.input_path.set(path)
            suffix = Path(path).suffix.lower()
            if suffix in {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".odt", ".odp", ".ods"}:
                self.target_format.set("pdf")
            if not self.output_dir.get():
                self.output_dir.set(str(Path(path).parent))

    def choose_output(self) -> None:
        path = filedialog.askdirectory(title="출력 폴더 선택")
        if path:
            self.output_dir.set(path)

    def choose_web_output(self) -> None:
        path = filedialog.askdirectory(title="PDF 저장 폴더 선택")
        if path:
            self.web_output_dir.set(path)

    def start_conversion(self) -> None:
        if not self.input_path.get().strip() or not self.target_format.get().strip():
            messagebox.showwarning("입력 필요", "입력 파일과 변환 형식을 지정하세요.")
            return
        self.convert_button.configure(state="disabled")
        self.status.set("변환 중입니다...")
        threading.Thread(target=self._convert, daemon=True).start()

    def _convert(self) -> None:
        try:
            result = convert(Path(self.input_path.get()), self.target_format.get(),
                             Path(self.output_dir.get()) if self.output_dir.get().strip() else None,
                             self.overwrite.get(), self.compress.get(), self.quality.get(), 150)
        except (ConversionError, OSError) as exc:
            self.after(0, self._finish_error, str(exc))
        else:
            self.after(0, self._finish_success, result)

    def _finish_success(self, result: Path) -> None:
        self.convert_button.configure(state="normal")
        self.status.set(f"변환 완료: {result}")
        messagebox.showinfo("변환 완료", f"파일이 생성되었습니다.\n{result}")

    def _finish_error(self, error: str) -> None:
        self.convert_button.configure(state="normal")
        self.status.set(f"변환 실패: {error}")
        messagebox.showerror("변환 실패", error)

    def start_web_conversion(self) -> None:
        if not self.web_url.get().strip():
            messagebox.showwarning("주소 필요", "저장할 웹페이지 주소를 입력하세요.")
            return
        self.web_button.configure(state="disabled")
        self.web_status.set("본문과 본문 이미지를 가져와 PDF를 만드는 중입니다...")
        threading.Thread(target=self._convert_web, daemon=True).start()

    def _convert_web(self) -> None:
        try:
            result = webpage_to_pdf(
                self.web_url.get(),
                Path(self.web_output_dir.get()) if self.web_output_dir.get().strip() else None,
                overwrite=self.web_overwrite.get(),
                include_source=self.web_include_source.get(),
            )
        except (WebPdfError, OSError) as exc:
            self.after(0, self._finish_web_error, str(exc))
        else:
            self.after(0, self._finish_web_success, result)

    def _finish_web_success(self, result) -> None:
        self.web_button.configure(state="normal")
        message = f"PDF 생성 완료: {result.output}"
        if result.skipped_images:
            message += f" (가져오지 못한 이미지 {len(result.skipped_images)}개)"
        self.web_status.set(message)
        messagebox.showinfo("PDF 생성 완료", message)

    def _finish_web_error(self, error: str) -> None:
        self.web_button.configure(state="normal")
        self.web_status.set(f"PDF 생성 실패: {error}")
        messagebox.showerror("PDF 생성 실패", error)

    def _on_paste_shortcut(self, event: tk.Event) -> str | None:
        """Ctrl+V. 결과 편집창 안에서는 평범한 텍스트 붙여넣기로 남겨둔다."""
        if self.notebook.index("current") != 2:
            return None
        if self.focus_get() is self.image_text:
            return None
        self.paste_image()
        return "break"

    def _show_image(self, image: Image.Image, label: str) -> None:
        self._discard_temp_image()
        self.current_image = image
        self.last_result = None
        self.image_text.delete("1.0", "end")
        preview = image.copy()
        preview.thumbnail((220, 220))
        self.preview_photo = ImageTk.PhotoImage(preview)
        self.preview_label.configure(image=self.preview_photo)
        self.image_info.set(f"{label} · {image.width}×{image.height}")

    def choose_image(self) -> None:
        path = filedialog.askopenfilename(
            title="텍스트를 추출할 이미지 선택",
            filetypes=[("이미지", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff"),
                       ("모든 파일", "*.*")],
        )
        if not path:
            return
        try:
            image = load_image(Path(path))
        except OcrError as exc:
            messagebox.showerror("이미지 열기 실패", str(exc))
            return
        self._show_image(image, Path(path).name)
        self.image_status.set("텍스트 추출을 누르세요.")

    def paste_image(self) -> None:
        """클립보드 이미지를 임시 PNG 로 떨군 뒤 파일과 똑같은 경로로 읽는다.

        메모리에 있는 클립보드 이미지를 그대로 쓰면 파일에서 연 것과 미묘하게
        다를 수 있다. 한 번 PNG 로 저장했다가 다시 읽으면 두 경로가 완전히
        같아진다. 이 임시 파일은 다음 이미지를 넣거나 창을 닫을 때 지운다.
        """
        try:
            pasted = image_from_clipboard()
        except OcrError as exc:
            messagebox.showwarning("붙여넣기 실패", str(exc))
            return
        workspace = Path(tempfile.mkdtemp(prefix="clipboard_"))
        path = workspace / "clipboard.png"
        try:
            pasted.save(path, format="PNG")
            image = load_image(path)
        except (OSError, ValueError, OcrError) as exc:
            shutil.rmtree(workspace, ignore_errors=True)
            messagebox.showerror("붙여넣기 실패", str(exc))
            return
        self._show_image(image, path.name)
        self.temp_image_path = path
        self.image_status.set("텍스트 추출 또는 PDF로 바로 저장을 누르세요.")

    def _discard_temp_image(self) -> None:
        """붙여넣기로 만들어 둔 임시 PNG 와 그 폴더를 지운다."""
        if self.temp_image_path is None:
            return
        shutil.rmtree(self.temp_image_path.parent, ignore_errors=True)
        self.temp_image_path = None

    def close(self) -> None:
        self._discard_temp_image()
        self.destroy()

    def start_image_conversion(self) -> None:
        if self.current_image is None:
            messagebox.showwarning("이미지 필요", "이미지를 불러오거나 Ctrl+V로 붙여넣으세요.")
            return
        self.image_button.configure(state="disabled")
        self.image_status.set("문자를 인식하는 중입니다...")
        threading.Thread(target=self._extract_image_text, daemon=True).start()

    def _extract_image_text(self) -> None:
        try:
            result = image_to_text(self.current_image)
        except OcrError as exc:
            self.after(0, self._finish_image_error, str(exc))
        else:
            self.after(0, self._finish_image_success, result)

    def _finish_image_success(self, result) -> None:
        self.image_button.configure(state="normal")
        self.last_result = result
        self.image_text.delete("1.0", "end")
        self.image_text.insert("1.0", result.text)
        self.image_status.set(
            f"{len(result.lines)}줄 인식 완료. 오타를 고친 뒤 복사하거나 저장하세요.")

    def _finish_image_error(self, error: str) -> None:
        self.image_button.configure(state="normal")
        self.image_status.set(f"인식 실패: {error}")
        messagebox.showerror("인식 실패", error)

    def _current_image_text(self) -> str:
        return self.image_text.get("1.0", "end-1c")

    def copy_image_text(self) -> None:
        text = self._current_image_text()
        if not text.strip():
            messagebox.showwarning("복사할 내용 없음", "먼저 텍스트를 추출하세요.")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self.image_status.set("클립보드에 복사했습니다.")

    def save_image_text(self, extension: str) -> None:
        text = self._current_image_text()
        if not text.strip():
            messagebox.showwarning("저장할 내용 없음", "먼저 텍스트를 추출하세요.")
            return
        path = filedialog.asksaveasfilename(
            title="텍스트 저장",
            defaultextension=f".{extension}",
            filetypes=[(f"{extension.upper()} 파일", f"*.{extension}")],
        )
        if not path:
            return
        try:
            Path(path).write_text(text, encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("저장 실패", str(exc))
            return
        self.image_status.set(f"저장 완료: {path}")

    def save_image_pdf(self) -> None:
        if self.current_image is None or self.last_result is None:
            messagebox.showwarning("추출 필요", "먼저 이미지를 불러와 텍스트를 추출하세요.")
            return
        path = filedialog.asksaveasfilename(
            title="검색 가능한 PDF 저장",
            defaultextension=".pdf",
            filetypes=[("PDF 파일", "*.pdf")],
        )
        if not path:
            return
        try:
            build_searchable_pdf(
                self.current_image, self.last_result, Path(path), overwrite=True)
        except (OcrError, OSError) as exc:
            messagebox.showerror("PDF 저장 실패", str(exc))
            return
        self.image_status.set(
            f"PDF 저장 완료: {path} · PDF에는 인식 원본이 들어갑니다. "
            "편집창에서 고친 내용은 반영되지 않습니다."
        )


    def start_direct_pdf(self) -> None:
        """텍스트 추출 단계를 거치지 않고 이미지에서 곧장 검색 가능한 PDF를 만든다.

        표가 있는 이미지는 텍스트로 펼치면 행과 열을 맞춰야 하지만, PDF 는 원본
        레이아웃 위에 글자를 제자리에 얹으므로 그 문제가 아예 생기지 않는다.
        """
        if self.current_image is None:
            messagebox.showwarning("이미지 필요", "이미지를 불러오거나 Ctrl+V로 붙여넣으세요.")
            return
        path = filedialog.asksaveasfilename(
            title="검색 가능한 PDF 저장",
            defaultextension=".pdf",
            filetypes=[("PDF 파일", "*.pdf")],
        )
        if not path:
            return
        self.image_button.configure(state="disabled")
        self.direct_pdf_button.configure(state="disabled")
        self.image_status.set("문자를 인식해 PDF를 만드는 중입니다...")
        threading.Thread(
            target=self._direct_pdf, args=(Path(path),), daemon=True).start()

    def _direct_pdf(self, destination: Path) -> None:
        try:
            result = image_to_text(self.current_image)
            build_searchable_pdf(
                self.current_image, result, destination, overwrite=True)
        except (OcrError, OSError) as exc:
            self.after(0, self._finish_direct_pdf_error, str(exc))
        else:
            self.after(0, self._finish_direct_pdf_success, result, destination)

    def _enable_image_buttons(self) -> None:
        self.image_button.configure(state="normal")
        self.direct_pdf_button.configure(state="normal")

    def _finish_direct_pdf_success(self, result, destination: Path) -> None:
        self._enable_image_buttons()
        self.last_result = result
        self.image_text.delete("1.0", "end")
        self.image_text.insert("1.0", result.text)
        self.image_status.set(
            f"PDF 저장 완료: {destination} · 원본 위에서 글자를 드래그해 복사할 수 있습니다."
        )

    def _finish_direct_pdf_error(self, error: str) -> None:
        self._enable_image_buttons()
        self.image_status.set(f"PDF 저장 실패: {error}")
        messagebox.showerror("PDF 저장 실패", error)


if __name__ == "__main__":
    ConverterApp().mainloop()
