"""PDF 합치기·분할과 쪽 썸네일 렌더링. GUI를 모르는 코어 모듈이며 CLI로도 실행된다."""

from __future__ import annotations

import argparse
import os
import re
import sys
import threading
from collections.abc import Iterable, Sequence
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PyPdfError

THUMBNAIL_WIDTH = 110  # px

_SEPARATORS = re.compile(r"[,，、]")
_RANGE = re.compile(r"^(\d+)(?:\s*-\s*(\d+))?$")
# PDFium은 스레드 안전하지 않다. 썸네일 스레드가 둘 이상 동시에 돌면 접근 위반으로 죽으므로 호출을 줄 세운다.
_RENDER_LOCK = threading.Lock()


class PdfPagesError(Exception):
    """사용자에게 그대로 보여줄 수 있는 한국어 메시지를 담는다."""


def parse_page_range(text: str, page_count: int) -> list[int]:
    """"1-3, 5"를 [1, 2, 3, 5]로 푼다. 빈 문자열은 전체다. 번호는 1부터 시작한다.

    적은 순서를 그대로 지키고 중복도 허용한다. 합칠 때 같은 쪽을 두 번 넣거나
    순서를 바꿔 넣는 것이 가능해야 하기 때문이다.
    """
    if not text.strip():
        return list(range(1, page_count + 1))
    pages: list[int] = []
    for part in _SEPARATORS.split(text):
        part = part.strip()
        if not part:
            continue
        match = _RANGE.match(part)
        if not match:
            raise PdfPagesError(f"페이지 지정을 이해할 수 없습니다: {part}")
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        if end < start:
            raise PdfPagesError(f"페이지 범위는 작은 수에서 큰 수 순서여야 합니다: {part}")
        for number in (start, end):
            if not 1 <= number <= page_count:
                raise PdfPagesError(f"1부터 {page_count} 사이의 페이지만 지정할 수 있습니다: {number}")
        pages.extend(range(start, end + 1))
    return pages


def format_page_range(pages: Iterable[int]) -> str:
    """{1, 2, 3, 5}를 "1-3, 5"로 압축한다. 중복은 무시하고 항상 오름차순이다."""
    numbers = sorted(set(pages))
    chunks: list[str] = []
    index = 0
    while index < len(numbers):
        start = numbers[index]
        while index + 1 < len(numbers) and numbers[index + 1] == numbers[index] + 1:
            index += 1
        end = numbers[index]
        chunks.append(str(start) if start == end else f"{start}-{end}")
        index += 1
    return ", ".join(chunks)


def _open_reader(path: Path) -> PdfReader:
    """읽기 전용으로 연다. 열 수 없거나 암호가 걸려 있으면 한국어 메시지로 바꾼다."""
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise PdfPagesError(f"암호가 걸린 PDF는 지원하지 않습니다: {path.name}")
        len(reader.pages)  # 손상된 파일은 쪽 목록을 읽을 때 드러난다
    except (OSError, PyPdfError) as exc:
        raise PdfPagesError(f"PDF 파일을 읽을 수 없습니다: {path.name}") from exc
    return reader


def pdf_page_count(path: Path | str) -> int:
    return len(_open_reader(Path(path)).pages)


def render_page(path: Path | str, page_number: int, width: int = THUMBNAIL_WIDTH) -> Image.Image:
    """한 쪽을 폭 width px에 맞춰 그린 RGB 이미지를 돌려준다. 번호는 1부터 시작한다.

    pypdfium2는 여기서만 읽는다. 미설치여도 합치기·분할(pypdf)은 되어야 하므로
    ImportError는 감싸지 않고 그대로 올린다.
    """
    import pypdfium2 as pdfium

    with _RENDER_LOCK:
        try:
            document = pdfium.PdfDocument(str(path))
        except (pdfium.PdfiumError, OSError) as exc:  # pypdfium2는 열기 실패를 PdfiumError로 올린다
            raise PdfPagesError(f"PDF 파일을 읽을 수 없습니다: {Path(path).name}") from exc
        try:
            if not 1 <= page_number <= len(document):
                raise PdfPagesError(f"{page_number}쪽은 없습니다: {Path(path).name}")
            page = document[page_number - 1]
            try:
                page_width, _ = page.get_size()
                return page.render(scale=width / page_width).to_pil().convert("RGB")
            finally:
                page.close()
        finally:
            document.close()


def merged_name(first_source: Path | str) -> str:
    return f"{Path(first_source).stem}_합본.pdf"


def split_name(source: Path | str, pages: str) -> str:
    return f"{Path(source).stem}_p{re.sub(r'\s+', '', pages)}.pdf"


def merge_pdfs(
    sources: Sequence[tuple[Path | str, str]],
    destination: Path | str,
    *,
    overwrite: bool = False,
) -> Path:
    """sources 순서대로, 각 항목의 페이지 지정에 맞는 쪽만 모아 새 PDF를 만든다.

    페이지 문자열이 비어 있으면 그 파일 전체다. 원본은 읽기만 한다.
    """
    if len(sources) < 2:
        raise PdfPagesError("PDF를 2개 이상 지정하세요.")
    return _assemble(sources, Path(destination), overwrite)


def split_pdf(source: Path | str, pages: str, destination: Path | str, *, overwrite: bool = False) -> Path:
    """한 PDF에서 지정한 쪽만 모아 새 PDF 1개를 만든다. 전체를 다시 쓰는 것은 분할이 아니므로 빈 지정은 거부한다."""
    if not pages.strip():
        raise PdfPagesError("분리할 페이지를 입력하세요.")
    return _assemble([(source, pages)], Path(destination), overwrite)


def _assemble(sources: Sequence[tuple[Path | str, str]], destination: Path, overwrite: bool) -> Path:
    # 쓰기 전에 모든 입력을 먼저 검사한다. 3번째 파일의 오류 때문에 반쯤 쓰인 결과가 남으면 안 된다.
    planned: list[tuple[PdfReader, list[int]]] = []
    for path, pages in sources:
        reader = _open_reader(Path(path))
        planned.append((reader, parse_page_range(pages, len(reader.pages))))
    writer = PdfWriter()
    for reader, numbers in planned:
        for number in numbers:
            writer.add_page(reader.pages[number - 1])
    if len(writer.pages) == 0:
        raise PdfPagesError("합칠 페이지가 없습니다.")
    return _write_pdf(writer, destination, overwrite)


def _write_pdf(writer: PdfWriter, destination: Path, overwrite: bool) -> Path:
    """임시 파일에 쓴 뒤 최종 이름으로 옮긴다. 중간에 실패해도 반쯤 쓰인 파일이 남지 않는다."""
    if destination.exists() and not overwrite:
        raise PdfPagesError(f"같은 이름의 PDF가 이미 있습니다: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.writing.pdf")
    try:
        with open(temporary, "wb") as handle:
            writer.write(handle)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def _split_source_argument(argument: str) -> tuple[str, str]:
    """"b.pdf:1-3"을 ("b.pdf", "1-3")으로 나눈다. ".pdf"로 끝나면 페이지 지정이 없는 것이다.

    Windows 드라이브 문자의 콜론(C:\\...)과 구분하기 위해 마지막 콜론만 본다.
    """
    if argument.lower().endswith(".pdf") or ":" not in argument:
        return argument, ""
    path, _, pages = argument.rpartition(":")
    return path, pages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PDF를 합치거나 원하는 쪽만 분리해 새 PDF를 만듭니다. 원본은 바꾸지 않습니다.")
    commands = parser.add_subparsers(dest="command", required=True)

    merge = commands.add_parser("merge", help="여러 PDF를 순서대로 합칩니다")
    merge.add_argument("sources", nargs="+", help='경로 또는 "경로:1-3,5" (페이지를 생략하면 전체)')
    merge.add_argument("--output", type=Path, help="결과 PDF 경로 (기본: 저장 폴더/첫파일_합본.pdf)")
    merge.add_argument("--output-dir", type=Path, default=Path("output/pdf"))
    merge.add_argument("--overwrite", action="store_true")

    split = commands.add_parser("split", help="한 PDF에서 원하는 쪽만 분리합니다")
    split.add_argument("source", type=Path)
    split.add_argument("--pages", required=True, help='분리할 쪽, 예: "2-4,7"')
    split.add_argument("--output", type=Path, help="결과 PDF 경로 (기본: 저장 폴더/원본_p페이지.pdf)")
    split.add_argument("--output-dir", type=Path, default=Path("output/pdf"))
    split.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "merge":
            sources = [_split_source_argument(item) for item in args.sources]
            destination = args.output or args.output_dir / merged_name(sources[0][0])
            result = merge_pdfs(sources, destination, overwrite=args.overwrite)
        else:
            destination = args.output or args.output_dir / split_name(args.source, args.pages)
            result = split_pdf(args.source, args.pages, destination, overwrite=args.overwrite)
    except (PdfPagesError, OSError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    print(f"PDF 생성 완료: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
