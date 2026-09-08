"""Desktop UI for saving a webpage's article body and images as a local PDF."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from web_to_pdf import WebPdfError, WebPdfResult, webpage_to_pdf


class ArticleConverterApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Article Converter — 웹 본문 PDF")
        self.geometry("760x390")
        self.minsize(650, 340)
        self.url = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(Path.cwd() / "output" / "pdf"))
        self.overwrite = tk.BooleanVar()
        self.include_source = tk.BooleanVar()
        self.status = tk.StringVar(
            value="공개 웹페이지 주소를 붙여넣으세요. 본문과 본문 이미지만 PDF로 저장합니다."
        )
        self._build_ui()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="웹페이지 주소").grid(row=0, column=0, sticky="w", pady=8)
        url_entry = ttk.Entry(frame, textvariable=self.url)
        url_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(10, 0))
        url_entry.focus_set()

        ttk.Label(frame, text="PDF 저장 폴더").grid(row=1, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=self.output_dir).grid(row=1, column=1, sticky="ew", padx=10)
        ttk.Button(frame, text="폴더 선택", command=self._choose_output).grid(row=1, column=2)

        ttk.Checkbutton(frame, text="같은 제목이면 덮어쓰기", variable=self.overwrite).grid(
            row=2, column=1, sticky="w", padx=10, pady=7
        )
        ttk.Checkbutton(frame, text="PDF 첫 줄에 원본 URL 표시", variable=self.include_source).grid(
            row=3, column=1, sticky="w", padx=10, pady=7
        )

        self.convert_button = ttk.Button(frame, text="본문 PDF 만들기", command=self._start_conversion)
        self.convert_button.grid(row=4, column=1, sticky="e", padx=10, pady=18)

        ttk.Separator(frame).grid(row=5, column=0, columnspan=3, sticky="ew")
        ttk.Label(
            frame,
            text=(
                "광고·메뉴·댓글은 제외하도록 설계했습니다. 로그인, CAPTCHA, 유료벽, "
                "접근 차단 페이지는 변환하지 못할 수 있습니다."
            ),
            wraplength=700,
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(15, 5))
        ttk.Label(frame, textvariable=self.status, wraplength=700).grid(
            row=7, column=0, columnspan=3, sticky="w", pady=5
        )

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(title="PDF 저장 폴더 선택")
        if selected:
            self.output_dir.set(selected)

    def _start_conversion(self) -> None:
        if not self.url.get().strip():
            messagebox.showwarning("주소 필요", "저장할 웹페이지 주소를 입력하세요.")
            return
        self.convert_button.configure(state="disabled")
        self.status.set("본문과 본문 이미지를 가져와 PDF를 만드는 중입니다...")
        threading.Thread(target=self._convert, daemon=True).start()

    def _convert(self) -> None:
        try:
            result = webpage_to_pdf(
                self.url.get(),
                Path(self.output_dir.get()) if self.output_dir.get().strip() else None,
                overwrite=self.overwrite.get(),
                include_source=self.include_source.get(),
            )
        except (WebPdfError, OSError) as exc:
            self.after(0, self._finish_error, str(exc))
        else:
            self.after(0, self._finish_success, result)

    def _finish_success(self, result: WebPdfResult) -> None:
        self.convert_button.configure(state="normal")
        message = f"PDF 생성 완료: {result.output}"
        if result.skipped_images:
            message += f" (가져오지 못한 이미지 {len(result.skipped_images)}개)"
        self.status.set(message)
        messagebox.showinfo("PDF 생성 완료", message)

    def _finish_error(self, error: str) -> None:
        self.convert_button.configure(state="normal")
        self.status.set(f"PDF 생성 실패: {error}")
        messagebox.showerror("PDF 생성 실패", error)


if __name__ == "__main__":
    ArticleConverterApp().mainloop()
