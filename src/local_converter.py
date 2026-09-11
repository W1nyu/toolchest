"""Local file converter CLI and reusable conversion functions."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

OFFICE_EXTENSIONS = {".doc", ".docx", ".odt", ".rtf", ".ppt", ".pptx", ".odp", ".xls", ".xlsx", ".ods", ".csv"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".flac", ".aac", ".ogg", ".opus"}


class ConversionError(RuntimeError):
    """Raised when a conversion cannot be completed."""


def find_executable(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def find_libreoffice() -> str | None:
    found = find_executable("soffice", "libreoffice", "soffice.exe")
    if found:
        return found
    for root in filter(None, (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"))):
        candidate = Path(root) / "LibreOffice" / "program" / "soffice.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def find_ghostscript() -> str | None:
    found = find_executable("gswin64c", "gswin32c", "gs", "gswin64c.exe")
    if found:
        return found
    for root in filter(None, (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"))):
        base = Path(root) / "gs"
        if base.is_dir():
            candidates = sorted(base.glob("*/bin/gswin64c.exe"), reverse=True)
            if candidates:
                return str(candidates[0])
    return None


def find_pdf_renderer() -> tuple[str, str] | None:
    """Find Poppler's pdftoppm or pdftocairo and return (program, mode)."""
    pdftoppm = find_executable("pdftoppm", "pdftoppm.exe")
    if pdftoppm:
        return pdftoppm, "pdftoppm"
    pdftocairo = find_executable("pdftocairo", "pdftocairo.exe")
    if pdftocairo:
        return pdftocairo, "pdftocairo"
    return None


def output_path(source: Path, target_format: str, output_dir: Path | None) -> Path:
    destination_dir = output_dir or source.parent
    return destination_dir / f"{source.stem}.{target_format.lower().lstrip('.') }"


def run_command(command: list[str]) -> None:
    try:
        completed = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ConversionError(str(exc)) from exc
    if completed.returncode:
        details = completed.stderr.strip() or completed.stdout.strip()
        raise ConversionError(details or f"Converter exited with code {completed.returncode}.")


def convert_media(source: Path, destination: Path, overwrite: bool, compress: bool = False) -> Path:
    ffmpeg = find_executable("ffmpeg", "ffmpeg.exe")
    if not ffmpeg:
        raise ConversionError("FFmpeg was not found. Install it from https://ffmpeg.org/download.html and add it to PATH.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [ffmpeg, "-y" if overwrite else "-n", "-i", str(source)]
    if destination.suffix.lower() == ".mp3":
        command += ["-vn", "-codec:a", "libmp3lame", "-q:a", "2"]
    if compress and destination.suffix.lower() not in AUDIO_EXTENSIONS:
        command += ["-crf", "28", "-preset", "medium"]
    elif compress and destination.suffix.lower() != ".wav":
        command += ["-b:a", "128k"]
    command += [str(destination)]
    run_command(command)
    return destination


def compress_pdf(source: Path, destination: Path, overwrite: bool, quality: str = "ebook") -> Path:
    ghostscript = find_ghostscript()
    if not ghostscript:
        raise ConversionError("PDF compression requires Ghostscript. Install it from https://ghostscript.com/releases/.")
    if destination.exists() and not overwrite:
        raise ConversionError(f"Output already exists: {destination} (use --overwrite to replace it)")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.compressed.pdf")
    setting = {"screen": "/screen", "ebook": "/ebook", "printer": "/printer"}.get(quality, "/ebook")
    command = [ghostscript, "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4", "-dNOPAUSE", "-dQUIET", "-dBATCH",
               f"-dPDFSETTINGS={setting}", f"-sOutputFile={temporary}", str(source)]
    try:
        run_command(command)
        if not temporary.exists():
            raise ConversionError("Ghostscript did not create a compressed PDF.")
        if destination.exists():
            destination.unlink()
        temporary.replace(destination)
        return destination
    finally:
        if temporary.exists():
            temporary.unlink()


def convert_pdf_to_images(source: Path, output_dir: Path | None, image_format: str, dpi: int = 150) -> Path:
    renderer = find_pdf_renderer()
    if not renderer:
        raise ConversionError("PDF image conversion requires Poppler (pdftoppm or pdftocairo). Install it and add it to PATH.")
    if dpi < 30:
        raise ConversionError("DPI must be at least 30.")
    destination_dir = output_dir or source.parent
    destination_dir.mkdir(parents=True, exist_ok=True)
    prefix = destination_dir / source.stem
    program, mode = renderer
    if mode == "pdftoppm":
        command = [program, "-r", str(dpi), "-jpeg" if image_format == "jpg" else "-png", str(source), str(prefix)]
    else:
        command = [program, "-r", str(dpi), "-jpeg" if image_format == "jpg" else "-png", str(source), str(prefix)]
    run_command(command)
    images = sorted(destination_dir.glob(f"{source.stem}-*.{image_format}"))
    if not images:
        raise ConversionError("PDF renderer did not create any image files.")
    return images[0]


def convert_office(source: Path, destination: Path, overwrite: bool, compress: bool = False, quality: str = "ebook") -> Path:
    soffice = find_libreoffice()
    if not soffice:
        raise ConversionError("LibreOffice was not found. Install it from https://www.libreoffice.org/download/download/.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = destination.parent / f".conversion_{source.stem}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        run_command([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(temp_dir), str(source)])
        generated = temp_dir / f"{source.stem}.pdf"
        if not generated.exists():
            raise ConversionError("LibreOffice did not create a PDF file.")
        if destination.exists() and not overwrite:
            raise ConversionError(f"Output already exists: {destination} (use --overwrite to replace it)")
        if destination.exists():
            destination.unlink()
        generated.replace(destination)
        if compress:
            compress_pdf(destination, destination, True, quality)
        return destination
    finally:
        try:
            temp_dir.rmdir()
        except OSError:
            pass


def convert(source: Path, target_format: str, output_dir: Path | None = None, overwrite: bool = False,
            compress: bool = False, quality: str = "ebook", dpi: int = 150) -> Path:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise ConversionError(f"Input file not found: {source}")
    target = target_format.lower().lstrip(".")
    if not target or any(char in target for char in "\\/:*?\"<>|"):
        raise ConversionError("Target format must be a simple extension, such as mp3 or pdf.")
    if source.suffix.lower() == ".pdf" and target in {"jpg", "jpeg", "png"}:
        return convert_pdf_to_images(source, output_dir, "jpg" if target == "jpeg" else target, dpi)
    destination = output_path(source, target, output_dir)
    if destination.exists() and not overwrite:
        raise ConversionError(f"Output already exists: {destination} (use --overwrite to replace it)")
    if source.suffix.lower() in OFFICE_EXTENSIONS:
        if target != "pdf":
            if compress:
                raise ConversionError("Office 파일 자체의 안전한 압축은 지원하지 않습니다. --to pdf --compress를 사용하세요.")
            raise ConversionError("Office documents currently support PDF output only.")
        return convert_office(source, destination, overwrite, compress, quality)
    if source.suffix.lower() == ".pdf" and target == "pdf":
        return compress_pdf(source, destination, overwrite, quality) if compress else source
    # Do not keep a media extension allow-list: FFmpeg itself supports many
    # formats, including formats added in future versions.
    return convert_media(source, destination, overwrite, compress)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert files locally without uploading them.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--to", required=True, help="Target extension, for example mp3, wav, mp4, or pdf")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--compress", action="store_true", help="Reduce output size")
    parser.add_argument("--quality", choices=("screen", "ebook", "printer"), default="ebook",
                        help="PDF compression quality: screen=smallest, ebook=balanced, printer=highest")
    parser.add_argument("--dpi", type=int, default=150, help="Resolution for PDF to image conversion (default: 150)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = convert(args.input, args.to, args.output_dir, args.overwrite, args.compress, args.quality, args.dpi)
    except ConversionError as exc:
        print(f"Conversion failed: {exc}", file=sys.stderr)
        return 1
    print(f"Conversion complete: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
