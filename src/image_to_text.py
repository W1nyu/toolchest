"""이미지에서 한국어/영어 텍스트를 추출한다. Windows 내장 OCR을 사용한다."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageGrab

ROW_OVERLAP_RATIO = 0.5
COLUMN_TOLERANCE_LINES = 2
DEFAULT_TIMEOUT = 60
MAX_IMAGE_DIMENSION = 10000
DEFAULT_SCALE = 3.0  # 실측(1.png): 2배 10/32 -> 3배 13/32. 그 이상은 거의 평평하다.
# 긴 이미지는 prepare_image 가 인식기 한계(10000px)에 맞춰 배율을 자동으로 낮춘다.
BRIDGE_SCRIPT = Path(__file__).with_name("win_ocr.ps1")

# 허용 문자: 숫자, 영문, 한글 음절/자모, 공백, ASCII 문장부호, 문서 기호(· • ※)
_ALLOWED_CHARACTERS = (
    "0-9A-Za-z"
    "가-힣"                    # 한글 음절
    "ᄀ-ᇿㄱ-ㆎ"       # 한글 자모, 호환 자모
    "!-/:-@"       # ASCII 문장부호 앞쪽
    "[-`{-~"       # ASCII 문장부호 뒤쪽
    "·•※"               # · • ※
    " \t"
)
_DISALLOWED = re.compile(f"[^{_ALLOWED_CHARACTERS}]")
_WHITESPACE_RUN = re.compile(r"\s+")


class OcrError(Exception):
    """사용자에게 그대로 보여줄 수 있는 한국어 메시지를 담는다."""


@dataclass(frozen=True)
class OcrLine:
    text: str
    x: float
    y: float
    width: float
    height: float


def _same_row(first: OcrLine, other: OcrLine) -> bool:
    overlap = min(first.y + first.height, other.y + other.height) - max(first.y, other.y)
    if overlap <= 0:
        return False
    return overlap >= ROW_OVERLAP_RATIO * min(first.height, other.height)


def filter_characters(text: str) -> str:
    """허용 목록에 없는 문자를 제거한다.

    제거만 하고 치환은 하지 않는다. 인식이 틀린 글자를 다른 글자로 바꿔 추측하면
    맞았던 글자까지 틀리게 만들 수 있어서, 노이즈를 지우는 데까지만 한다.
    """
    return _WHITESPACE_RUN.sub(" ", _DISALLOWED.sub("", text)).strip()


def reading_order(lines: Sequence[OcrLine]) -> tuple[tuple[OcrLine, ...], ...]:
    """줄을 사람이 읽는 순서의 행 묶음으로 정리한다.

    Windows OCR 은 표를 열 단위로 훑어 줄 순서가 뒤섞인 채 돌아온다. 텍스트 출력과
    PDF 텍스트 레이어가 같은 순서를 쓰도록, 정렬 규칙을 한곳에 둔다.
    """
    ordered = sorted(lines, key=lambda item: (item.y, item.x))
    bands: list[list[OcrLine]] = []
    for item in ordered:
        if bands and _same_row(bands[-1][0], item):
            bands[-1].append(item)
        else:
            bands.append([item])
    return tuple(tuple(sorted(band, key=lambda item: item.x)) for band in bands)


def _column_anchors(bands: Sequence[Sequence[OcrLine]]) -> tuple[float, ...]:
    """열이 시작되는 x 좌표를 모은다.

    표의 열 위치는 라벨과 내용이 나란히 잡힌 행에서만 드러난다. 그렇게 얻은
    앵커가 있어야, 라벨 없이 혼자 있는 내용 줄도 제 열에 넣어줄 수 있다.
    나란히 잡힌 행이 하나도 없으면 열을 추측하지 않는다.
    """
    starts = sorted(line.x for band in bands if len(band) > 1 for line in band)
    if not starts:
        return ()
    heights = sorted(line.height for band in bands for line in band)
    # 같은 열이라도 글머리 기호나 표마다 다른 들여쓰기 때문에 시작 x 가 흔들린다.
    # 실측(ex.png)에서 열 안쪽 흔들림은 최대 57px, 열 사이 간격은 최소 157px 이었다.
    # 줄 높이 두 개분이 그 사이에 들어와 둘을 갈라준다.
    tolerance = heights[len(heights) // 2] * COLUMN_TOLERANCE_LINES
    groups = [[starts[0]]]
    for x in starts[1:]:
        if x - groups[-1][-1] > tolerance:
            groups.append([x])
        else:
            groups[-1].append(x)
    return tuple(group[len(group) // 2] for group in groups)


def _column_index(x: float, anchors: Sequence[float]) -> int:
    return min(range(len(anchors)), key=lambda index: abs(x - anchors[index]))


def group_lines(lines: Sequence[OcrLine]) -> str:
    """줄을 읽는 순서대로 정렬하고, 같은 높이의 줄을 한 행으로 묶는다.

    밴드 판정은 누적 범위가 아니라 밴드의 첫 줄을 기준으로 한다. 줄이 하나씩
    붙으면서 밴드의 세로 범위가 늘어나 관계없는 줄까지 빨아들이는 것을 막는다.
    """
    if not lines:
        return ""
    bands = reading_order(lines)
    anchors = _column_anchors(bands)
    rows = []
    for band in bands:
        if not anchors:
            rows.append("\t".join(item.text for item in band))
            continue
        cells: dict[int, list[str]] = {}
        for item in band:
            cells.setdefault(_column_index(item.x, anchors), []).append(item.text)
        last = max(cells)
        rows.append("\t".join(" ".join(cells.get(index, ())) for index in range(last + 1)))
    return "\n".join(rows)


def _run_bridge(args: list[str], timeout: int) -> dict:
    """win_ocr.ps1 을 실행하고 JSON 결과를 돌려준다.

    결과를 stdout 이 아니라 임시 파일로 주고받는다. PowerShell 5.1 의 stdout 은
    콘솔 코드페이지를 타서 한글이 깨지므로 파일 경유가 유일하게 안전하다.
    """
    if not BRIDGE_SCRIPT.is_file():
        raise OcrError(f"OCR 브리지 스크립트를 찾을 수 없습니다: {BRIDGE_SCRIPT}")
    with tempfile.TemporaryDirectory(prefix="imgocr_") as workspace:
        out_path = Path(workspace) / "result.json"
        command = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(BRIDGE_SCRIPT), "-OutPath", str(out_path), *args,
        ]
        try:
            completed = subprocess.run(command, capture_output=True, timeout=timeout)
        except FileNotFoundError as exc:
            raise OcrError("PowerShell을 찾지 못했습니다. Windows에서 실행해야 합니다.") from exc
        except subprocess.TimeoutExpired as exc:
            raise OcrError(f"문자 인식이 {timeout}초 안에 끝나지 않았습니다.") from exc
        if completed.returncode != 0:
            detail = ""
            if out_path.is_file():
                try:
                    payload = json.loads(out_path.read_text(encoding="utf-8-sig"))
                    detail = str(payload.get("error") or "")
                except (OSError, json.JSONDecodeError):
                    detail = ""
            if not detail:
                detail = (completed.stderr or b"").decode("utf-8", "replace").strip()
            raise OcrError(f"문자 인식에 실패했습니다. {detail[:300]}".strip())
        if not out_path.is_file():
            raise OcrError("문자 인식에 실패했습니다. 결과 파일이 생성되지 않았습니다.")
        try:
            return json.loads(out_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OcrError(f"인식 결과를 읽지 못했습니다. {exc}") from exc


def engine_info(timeout: int = 15) -> tuple[tuple[str, ...], int]:
    """사용 가능한 인식기 언어 태그와 최대 이미지 크기를 돌려준다."""
    payload = _run_bridge(["-ListLanguages"], timeout)
    languages = tuple(str(tag) for tag in (payload.get("languages") or ()))
    limit = int(payload.get("maxDimension") or MAX_IMAGE_DIMENSION)
    return languages, limit


def pick_language(languages: Sequence[str]) -> str:
    """한국어 인식기 태그를 고른다. ko-KR 처럼 지역이 붙은 태그도 받아들인다."""
    for tag in languages:
        if tag.lower().startswith("ko"):
            return tag
    raise OcrError(
        "Windows에 한국어 문자 인식기가 없습니다. "
        "설정 → 시간 및 언어 → 언어 및 지역 → 한국어의 언어 옵션에서 "
        "'광학 문자 인식'을 설치한 뒤 다시 시도하세요."
    )


@dataclass(frozen=True)
class OcrResult:
    text: str
    lines: tuple[OcrLine, ...]
    language: str
    scale: float


def load_image(path: Path | str) -> Image.Image:
    path = Path(path)
    if not path.is_file():
        raise OcrError(f"이미지를 찾을 수 없습니다: {path}")
    try:
        with Image.open(path) as opened:
            return opened.convert("RGB")
    except (OSError, ValueError) as exc:
        raise OcrError(f"이미지를 열지 못했습니다: {path.name} ({exc})") from exc


def image_from_clipboard() -> Image.Image:
    try:
        data = ImageGrab.grabclipboard()
    except OSError as exc:
        raise OcrError(f"클립보드를 읽지 못했습니다. {exc}") from exc
    if isinstance(data, Image.Image):
        return data.convert("RGB")
    if isinstance(data, list) and data:
        return load_image(Path(data[0]))
    raise OcrError("클립보드에 이미지가 없습니다. 이미지를 복사한 뒤 다시 붙여넣으세요.")


def flatten_transparency(image: Image.Image) -> Image.Image:
    """알파 채널이 있으면 흰 바탕에 합성하고, 없으면 그대로 RGB 로 바꾼다.

    클립보드로 들어온 이미지는 알파 채널을 달고 오는 경우가 있다. 알파를 그냥
    버리면 투명했던 자리가 검게 남아, 그 위의 어두운 글자를 OCR 이 읽지 못한다.
    PDF 페이지처럼 불투명한 흰 바탕에 얹어야 저장했다가 다시 연 것과 같아진다.

    불투명한 이미지는 건드리지 않는다. 지금 잘 읽히는 이미지가 나빠지면 안 된다.
    """
    transparent = image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    )
    if not transparent:
        return image.convert("RGB")
    blended = image.convert("RGBA")
    canvas = Image.new("RGB", blended.size, (255, 255, 255))
    canvas.paste(blended, mask=blended.split()[-1])
    return canvas


def prepare_image(image: Image.Image, scale: float, limit: int) -> tuple[Image.Image, float]:
    """RGB 로 바꾸고 확대한다. 확대 결과가 인식기 제한을 넘지 않도록 배율을 줄인다."""
    longest = max(image.size)
    if longest > limit:
        raise OcrError(
            f"이미지가 너무 큽니다. 긴 변이 {limit}px 이하여야 합니다. "
            f"현재 {image.width}×{image.height}"
        )
    effective = max(1.0, min(scale, limit / longest))
    prepared = flatten_transparency(image)
    if effective > 1.0:
        prepared = prepared.resize(
            (round(prepared.width * effective), round(prepared.height * effective)),
            Image.LANCZOS,
        )
    return prepared, effective


def image_to_text(
    source: Path | str | Image.Image,
    *,
    scale: float = DEFAULT_SCALE,
    timeout: int = DEFAULT_TIMEOUT,
) -> OcrResult:
    image = source if isinstance(source, Image.Image) else load_image(source)
    languages, limit = engine_info(min(timeout, 15))
    language = pick_language(languages)
    prepared, effective = prepare_image(image, scale, limit)

    workspace = Path(tempfile.mkdtemp(prefix="imgocr_"))
    try:
        page = workspace / "page.png"
        prepared.save(page, format="PNG")
        payload = _run_bridge(
            ["-ImagePath", str(page), "-Language", language], timeout)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    lines = []
    for item in payload.get("lines") or ():
        cleaned = filter_characters(str(item.get("text", "")))
        if not cleaned:
            continue
        lines.append(
            OcrLine(
                text=cleaned,
                x=float(item.get("x", 0.0)),
                y=float(item.get("y", 0.0)),
                width=float(item.get("w", 0.0)),
                height=float(item.get("h", 0.0)),
            )
        )
    if not lines:
        raise OcrError("텍스트를 찾지 못했습니다. 글자가 너무 작거나 흐릴 수 있습니다.")
    return OcrResult(
        text=group_lines(lines),
        lines=tuple(lines),
        language=language,
        scale=effective,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="이미지에서 한국어/영어 텍스트를 추출합니다.")
    parser.add_argument(
        "image", nargs="?", help="이미지 파일 경로 (생략하면 클립보드 이미지를 사용합니다)")
    parser.add_argument(
        "--scale", type=float, default=DEFAULT_SCALE,
        help=f"인식 전 확대 배율 (기본: {DEFAULT_SCALE})")
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT,
        help=f"인식 시간 제한(초) (기본: {DEFAULT_TIMEOUT})")
    parser.add_argument("--output", type=Path, help="결과를 저장할 텍스트 파일")
    parser.add_argument("--pdf", type=Path, help="검색 가능한 PDF로 저장할 경로")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        image = load_image(args.image) if args.image else image_from_clipboard()
        result = image_to_text(image, scale=args.scale, timeout=args.timeout)
        if args.pdf:
            from image_to_pdf import build_searchable_pdf

            saved = build_searchable_pdf(image, result, args.pdf, overwrite=True)
            print(f"PDF 저장 완료: {saved}")
    except OcrError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result.text, encoding="utf-8")
        print(f"저장 완료: {args.output}")
    elif not args.pdf:
        sys.stdout.reconfigure(encoding="utf-8")
        print(result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
