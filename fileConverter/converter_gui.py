"""Simple Windows-friendly desktop UI for the local converter."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from local_converter import ConversionError, convert


class ConverterApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("로컬 파일 변환기")
        self.geometry("720x350")
        self.minsize(620, 320)
        self.input_path = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.target_format = tk.StringVar(value="mp3")
        self.overwrite = tk.BooleanVar()
        self.compress = tk.BooleanVar()
        self.quality = tk.StringVar(value="ebook")
        self.status = tk.StringVar(value="변환할 파일을 선택하세요.")
        self._build_ui()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=18)
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


if __name__ == "__main__":
    ConverterApp().mainloop()
