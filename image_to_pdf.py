"""OCR 결과를 원본 이미지 위 보이지 않는 텍스트 레이어로 얹어 검색 가능한 PDF를 만든다."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from image_to_text import OcrError, OcrResult
from web_to_pdf import korean_font_name

MAX_PDF_POINTS = 14400.0
INVISIBLE_TEXT = 3  # PDF 텍스트 렌더 모드: 그리지 않는다. 선택은 된다.


def page_scale(width: float, height: float) -> float:
    """PDF 한 변의 한계(14400pt)를 넘지 않도록 줄일 비율을 돌려준다."""
    longest = max(width, height)
    if longest <= MAX_PDF_POINTS:
        return 1.0
    return MAX_PDF_POINTS / longest


def build_searchable_pdf(
    image: Image.Image,
    result: OcrResult,
    destination: Path | str,
    *,
    overwrite: bool = False,
) -> Path:
    """원본 이미지 한 장을 한 페이지로 만들고, 인식 위치에 보이지 않는 텍스트를 얹는다."""
    destination = Path(destination)
    if destination.exists() and not overwrite:
        raise OcrError(f"같은 이름의 PDF가 이미 있습니다: {destination}")
    if not result.lines:
        raise OcrError("PDF로 만들 인식 결과가 없습니다.")
    destination.parent.mkdir(parents=True, exist_ok=True)

    factor = page_scale(float(image.width), float(image.height))
    page_width = image.width * factor
    page_height = image.height * factor
    font = korean_font_name()

    # OCR 좌표는 확대된 이미지 기준이므로 원본으로 되돌린 뒤 페이지 배율을 곱한다.
    to_page = factor / (result.scale or 1.0)

    pdf = canvas.Canvas(str(destination), pagesize=(page_width, page_height))
    pdf.drawImage(
        ImageReader(image.convert("RGB")), 0, 0,
        width=page_width, height=page_height,
    )

    # beginText(x, y)는 생성 즉시 "x y Tm"을 내보낸다. beginText() 뒤에 다시
    # setTextOrigin()을 부르면 처음 위치(0, 0)가 헛되이 먼저 찍히므로, 첫 줄의
    # 실제 좌표로 바로 생성해 불필요한 원점 연산자가 남지 않게 한다.
    text_object = None
    for stored in result.lines:
        box_width = stored.width * to_page
        box_height = stored.height * to_page
        if box_width <= 0 or box_height <= 0 or not stored.text:
            continue
        size = max(1.0, box_height * 0.8)
        natural = pdfmetrics.stringWidth(stored.text, font, size)
        if natural <= 0:
            continue
        origin_x = stored.x * to_page
        origin_y = page_height - stored.y * to_page - box_height
        if text_object is None:
            text_object = pdf.beginText(origin_x, origin_y)
            text_object.setTextRenderMode(INVISIBLE_TEXT)
        else:
            text_object.setTextOrigin(origin_x, origin_y)
        text_object.setFont(font, size)
        # 가로 비율을 맞춰야 드래그 범위가 이미지의 글자 위치와 어긋나지 않는다.
        text_object.setHorizScale(100.0 * box_width / natural)
        text_object.textLine(stored.text)
    if text_object is not None:
        pdf.drawText(text_object)
    pdf.showPage()
    pdf.save()
    return destination
