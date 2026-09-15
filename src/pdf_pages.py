"""PDF 합치기·분할과 쪽 썸네일 렌더링. GUI를 모르는 코어 모듈이며 CLI로도 실행된다."""

from __future__ import annotations

import re
from collections.abc import Iterable

THUMBNAIL_WIDTH = 110  # px

_SEPARATORS = re.compile(r"[,，、]")
_RANGE = re.compile(r"^(\d+)(?:\s*-\s*(\d+))?$")


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
