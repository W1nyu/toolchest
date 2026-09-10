"""이미지에서 한국어/영어 텍스트를 추출한다. Windows 내장 OCR을 사용한다."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

ROW_OVERLAP_RATIO = 0.5
DEFAULT_TIMEOUT = 60
MAX_IMAGE_DIMENSION = 10000
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


def group_lines(lines: Sequence[OcrLine]) -> str:
    """줄을 읽는 순서대로 정렬하고, 같은 높이의 줄을 한 행으로 묶는다.

    밴드 판정은 누적 범위가 아니라 밴드의 첫 줄을 기준으로 한다. 줄이 하나씩
    붙으면서 밴드의 세로 범위가 늘어나 관계없는 줄까지 빨아들이는 것을 막는다.
    """
    if not lines:
        return ""
    ordered = sorted(lines, key=lambda item: (item.y, item.x))
    bands: list[list[OcrLine]] = []
    for item in ordered:
        if bands and _same_row(bands[-1][0], item):
            bands[-1].append(item)
        else:
            bands.append([item])
    rows = []
    for band in bands:
        band.sort(key=lambda item: item.x)
        rows.append("\t".join(item.text for item in band))
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
        if completed.returncode != 0 or not out_path.is_file():
            detail = (completed.stderr or b"").decode("utf-8", "replace").strip()
            raise OcrError(f"문자 인식에 실패했습니다. {detail[:300]}".strip())
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
