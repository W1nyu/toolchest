import re
import tempfile
import unittest
from pathlib import Path

from PIL import Image

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
            self.assertAlmostEqual(float(matches[0][1]), 78.0, places=1)


if __name__ == "__main__":
    unittest.main()
