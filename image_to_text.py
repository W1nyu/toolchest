"""이미지에서 한국어/영어 텍스트를 추출한다. Windows 내장 OCR을 사용한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

ROW_OVERLAP_RATIO = 0.5


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
