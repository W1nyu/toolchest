import re
import tempfile
import unittest
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import image_to_pdf
from image_to_text import OcrLine, OcrResult

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


def sample_result(scale=1.0):
    return OcrResult(
        text="모집구분 Card",
        lines=(OcrLine(text="모집구분 Card", x=10.0, y=20.0, width=180.0, height=24.0),),
        language="ko",
        scale=scale,
    )


class PageScaleTests(unittest.TestCase):
    def test_small_page_is_not_scaled(self):
        self.assertEqual(image_to_pdf.page_scale(920.0, 3323.0), 1.0)

    def test_page_longer_than_the_pdf_limit_is_scaled_down(self):
        factor = image_to_pdf.page_scale(1000.0, 28800.0)
        self.assertAlmostEqual(factor, 0.5)


class BuildSearchablePdfTests(unittest.TestCase):
    def test_existing_file_is_kept_unless_overwrite_is_set(self):
        with tempfile.TemporaryDirectory() as workspace:
            target = Path(workspace) / "out.pdf"
            target.write_bytes("기존 파일".encode("utf-8"))
            with self.assertRaises(image_to_pdf.OcrError):
                image_to_pdf.build_searchable_pdf(
                    Image.new("RGB", (200, 100), "white"), sample_result(), target)
            self.assertEqual(target.read_bytes(), "기존 파일".encode("utf-8"))

    @unittest.skipUnless(PdfReader is not None, "pypdf가 설치되어 있지 않습니다")
    def test_page_matches_the_original_image_size(self):
        with tempfile.TemporaryDirectory() as workspace:
            target = Path(workspace) / "out.pdf"
            image_to_pdf.build_searchable_pdf(
                Image.new("RGB", (200, 100), "white"), sample_result(), target)
            box = PdfReader(str(target)).pages[0].mediabox
            self.assertEqual((float(box.width), float(box.height)), (200.0, 100.0))

    @unittest.skipUnless(PdfReader is not None, "pypdf가 설치되어 있지 않습니다")
    def test_recognized_text_is_selectable_in_the_pdf(self):
        with tempfile.TemporaryDirectory() as workspace:
            target = Path(workspace) / "out.pdf"
            image_to_pdf.build_searchable_pdf(
                Image.new("RGB", (200, 100), "white"), sample_result(), target)
            extracted = PdfReader(str(target)).pages[0].extract_text()
            self.assertIn("모집구분", extracted)
            self.assertIn("Card", extracted)

    @unittest.skipUnless(PdfReader is not None, "pypdf가 설치되어 있지 않습니다")
    def test_upscaled_coordinates_are_mapped_back_to_the_original(self):
        # scale=2.0 이면 OCR 좌표는 원본의 두 배다. y=20,h=24 는 원본에서 y=10,h=12 이므로
        # 200x100 페이지에서 텍스트 기준선은 100 - 10 - 12 = 78 근처여야 한다.
        with tempfile.TemporaryDirectory() as workspace:
            target = Path(workspace) / "out.pdf"
            image_to_pdf.build_searchable_pdf(
                Image.new("RGB", (200, 100), "white"), sample_result(scale=2.0), target)
            stream = PdfReader(str(target)).pages[0].get_contents().get_data()
            matches = re.findall(rb"1 0 0 1 ([\d.]+) ([\d.]+) Tm", stream)
            self.assertTrue(matches, "텍스트 위치 지정 연산자를 찾지 못했습니다")
            self.assertAlmostEqual(float(matches[0][0]), 5.0, places=1)
            # 상자 아래 78.0 에서 내림폭(size 12 * 0.2)만큼 올라간 자리가 기준선이다.
            self.assertAlmostEqual(float(matches[0][1]), 80.4, places=1)


class SelectableAreaTests(unittest.TestCase):
    @unittest.skipUnless(PdfReader is not None, "pypdf가 설치되어 있지 않습니다")
    def test_invisible_text_covers_the_whole_line_height(self):
        # 선택 가능한 구간이 인식된 글자 상자를 덮어야 한다. 아래쪽에만 얹히면
        # 줄 윗부분을 드래그했을 때 아무것도 잡히지 않는다.
        result = OcrResult(
            text="",
            lines=(OcrLine(text="가나다라", x=10.0, y=20.0, width=180.0, height=24.0),),
            language="ko",
            scale=1.0,
        )
        with tempfile.TemporaryDirectory() as workspace:
            target = Path(workspace) / "cover.pdf"
            image_to_pdf.build_searchable_pdf(
                Image.new("RGB", (200, 100), "white"), result, target)
            stream = PdfReader(str(target)).pages[0].get_contents().get_data()
        # reportlab 은 텍스트 객체를 만들 때 기본 "12 Tf" 를 먼저 뱉는다.
        # 우리가 지정한 크기는 그 뒤에 오므로 마지막 것을 본다.
        size = float(re.findall(rb"/\S+ ([\d.]+) Tf", stream)[-1])
        baseline = float(re.findall(rb"1 0 0 1 [\d.]+ ([\d.]+) Tm", stream)[0])
        box_bottom, box_top = 100.0 - 20.0 - 24.0, 100.0 - 20.0
        selectable_bottom = baseline - 0.2 * size
        selectable_top = baseline + 0.8 * size
        covered = min(selectable_top, box_top) - max(selectable_bottom, box_bottom)
        self.assertGreaterEqual(
            covered / 24.0, 0.9,
            "선택 가능한 세로 구간이 글자 상자의 90%%에 못 미칩니다: %.0f%%" % (covered / 24.0 * 100),
        )


class ReadingOrderTests(unittest.TestCase):
    @unittest.skipUnless(PdfReader is not None, "pypdf가 설치되어 있지 않습니다")
    def test_text_is_written_top_to_bottom_not_in_ocr_order(self):
        # Windows OCR 은 표를 열 단위로 뱉어 줄 순서가 뒤섞여 돌아온다.
        # PDF 에 그 순서대로 쓰면 전체 선택 복사가 뒤죽박죽 나오므로,
        # 읽는 순서로 정렬해서 써야 한다.
        lines = (
            OcrLine(text="아래줄", x=10.0, y=200.0, width=80.0, height=20.0),
            OcrLine(text="윗줄", x=10.0, y=10.0, width=80.0, height=20.0),
            OcrLine(text="윗줄오른쪽", x=200.0, y=10.0, width=80.0, height=20.0),
        )
        result = OcrResult(text="", lines=lines, language="ko", scale=1.0)
        with tempfile.TemporaryDirectory() as workspace:
            target = Path(workspace) / "order.pdf"
            image_to_pdf.build_searchable_pdf(
                Image.new("RGB", (400, 300), "white"), result, target)
            seen = []
            PdfReader(str(target)).pages[0].extract_text(
                visitor_text=lambda t, cm, tm, f, sz: (
                    seen.append(t.strip()) if t.strip() else None))
            self.assertEqual(seen, ["윗줄", "윗줄오른쪽", "아래줄"])


if __name__ == "__main__":
    unittest.main()
