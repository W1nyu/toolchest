import tempfile
import unittest
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import image_to_text
from image_to_text import OcrLine


def line(text, x, y, height=10.0, width=50.0):
    return OcrLine(text=text, x=x, y=y, width=width, height=height)


class GroupLinesTests(unittest.TestCase):
    def test_empty_input_returns_empty_string(self):
        self.assertEqual(image_to_text.group_lines([]), "")

    def test_vertically_separated_lines_become_separate_rows(self):
        lines = [line("위", 0, 0), line("아래", 0, 20)]
        self.assertEqual(image_to_text.group_lines(lines), "위\n아래")

    def test_lines_at_same_height_are_joined_by_tab_in_x_order(self):
        lines = [line("내용", 100, 0), line("구분", 0, 0)]
        self.assertEqual(image_to_text.group_lines(lines), "구분\t내용")

    def test_orphan_content_keeps_its_column(self):
        # 라벨과 내용이 나란히 잡힌 행이 열 위치를 알려주므로,
        # 라벨 없이 혼자 있는 내용 줄도 같은 열에 들어가야 한다.
        lines = [
            line("지원자격", 0, 0),
            line("병역필 또는 면제자", 400, 0),
            line("전공 무관", 400, 20),
        ]
        self.assertEqual(
            image_to_text.group_lines(lines),
            "지원자격\t병역필 또는 면제자\n\t전공 무관",
        )

    def test_third_column_content_is_padded_to_its_own_column(self):
        lines = [
            line("모집분야", 0, 0),
            line("세부직무", 300, 0),
            line("직무내용", 700, 0),
            line("카드 상품별 기획", 700, 20),
        ]
        self.assertEqual(
            image_to_text.group_lines(lines),
            "모집분야\t세부직무\t직무내용\n\t\t카드 상품별 기획",
        )

    def test_text_without_any_paired_row_is_left_unpadded(self):
        # 열 정보를 알려주는 행이 하나도 없으면 그대로 둔다.
        lines = [line("첫 줄", 100, 0), line("둘째 줄", 100, 20)]
        self.assertEqual(image_to_text.group_lines(lines), "첫 줄\n둘째 줄")

    def test_band_does_not_chain_beyond_its_first_line(self):
        # A(y 0~10)와 B(y 5~15)는 5만큼 겹쳐 같은 행이다.
        # C(y 10~20)는 B와는 겹치지만 밴드의 첫 줄인 A와는 겹치지 않으므로 새 행이어야 한다.
        # 누적 범위(0~15)로 판정하면 C까지 빨려 들어가 이 테스트가 깨진다.
        lines = [line("A", 0, 0), line("B", 100, 5), line("C", 0, 10)]
        self.assertEqual(image_to_text.group_lines(lines), "A\tB\nC")


class FilterCharactersTests(unittest.TestCase):
    def test_korean_english_digits_and_punctuation_survive(self):
        for text in [
            "학/석사 기졸업자 또는 2027년 2월 졸업예정자",
            "국내(대한민국) 취업 및 해외 출장",
            "8월 31일(월) 오전 10시 ~ 9월 14일(월)",
            "career.hyundai.co.kr",
            "1/2금융권 대출 금액의 연 1% 이자지원",
            "영어 Speaking 성적(TOEIC Speaking 또는 OPIc) 필수 제출",
        ]:
            with self.subTest(text=text):
                self.assertEqual(image_to_text.filter_characters(text), text)

    def test_document_symbols_survive(self):
        self.assertEqual(image_to_text.filter_characters("※ 상기 모집 직무"), "※ 상기 모집 직무")
        self.assertEqual(image_to_text.filter_characters("• 전공 무관"), "• 전공 무관")

    def test_noise_characters_are_removed_not_replaced(self):
        # 제거만 한다. 「 를 r 로 되돌리지 않는다.
        self.assertEqual(image_to_text.filter_characters("Ca「d"), "Cad")
        self.assertEqual(image_to_text.filter_characters("回 口 而"), "")

    def test_hangul_jamo_survives(self):
        self.assertEqual(image_to_text.filter_characters("ㄱㄴㄷ"), "ㄱㄴㄷ")

    def test_runs_of_whitespace_collapse_and_edges_are_trimmed(self):
        self.assertEqual(image_to_text.filter_characters("  모집  구분  "), "모집 구분")

    def test_text_of_only_noise_becomes_empty(self):
        self.assertEqual(image_to_text.filter_characters("「」回"), "")


class PickLanguageTests(unittest.TestCase):
    def test_plain_ko_tag_is_selected(self):
        self.assertEqual(image_to_text.pick_language(["en-US", "ko"]), "ko")

    def test_regional_korean_tag_is_selected(self):
        self.assertEqual(image_to_text.pick_language(["en-US", "ko-KR"]), "ko-KR")

    def test_missing_korean_recognizer_raises_with_setup_guidance(self):
        with self.assertRaises(image_to_text.OcrError) as caught:
            image_to_text.pick_language(["en-US"])
        self.assertIn("광학 문자 인식", str(caught.exception))

    def test_bridge_script_exists_next_to_module(self):
        self.assertTrue(image_to_text.BRIDGE_SCRIPT.is_file())


HAS_KOREAN_RECOGNIZER = False
try:
    HAS_KOREAN_RECOGNIZER = any(
        tag.lower().startswith("ko") for tag in image_to_text.engine_info()[0]
    )
except image_to_text.OcrError:
    HAS_KOREAN_RECOGNIZER = False


class PrepareImageTests(unittest.TestCase):
    def test_image_is_upscaled_by_the_requested_factor(self):
        prepared, scale = image_to_text.prepare_image(
            Image.new("RGB", (100, 200)), 2.0, 10000)
        self.assertEqual(prepared.size, (200, 400))
        self.assertEqual(scale, 2.0)

    def test_scale_is_reduced_so_the_result_fits_the_limit(self):
        prepared, scale = image_to_text.prepare_image(
            Image.new("RGB", (100, 400)), 2.0, 600)
        self.assertLessEqual(max(prepared.size), 600)
        self.assertEqual(scale, 1.5)

    def test_palette_image_is_converted_to_rgb(self):
        prepared, _ = image_to_text.prepare_image(
            Image.new("P", (50, 50)), 1.0, 10000)
        self.assertEqual(prepared.mode, "RGB")

    def test_oversized_original_is_rejected_with_both_numbers(self):
        with self.assertRaises(image_to_text.OcrError) as caught:
            image_to_text.prepare_image(Image.new("RGB", (12000, 10)), 2.0, 10000)
        message = str(caught.exception)
        self.assertIn("10000", message)
        self.assertIn("12000", message)


class TransparencyTests(unittest.TestCase):
    def test_transparent_background_becomes_white_not_black(self):
        # 클립보드 이미지는 알파 채널을 달고 오는 경우가 있다. 알파를 그냥 버리면
        # 투명했던 자리가 검게 남아 그 위의 어두운 글자를 OCR 이 못 읽는다.
        image = Image.new("RGBA", (20, 10), (0, 0, 0, 0))
        image.putpixel((5, 5), (0, 0, 0, 255))          # 불투명한 검은 글자 한 점
        prepared, _ = image_to_text.prepare_image(image, 1.0, 10000)
        self.assertEqual(prepared.mode, "RGB")
        self.assertEqual(prepared.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(prepared.getpixel((5, 5)), (0, 0, 0))

    def test_opaque_image_is_untouched(self):
        # 불투명 이미지는 손대지 않는다. 지금 잘 되는 경우가 나빠지면 안 된다.
        image = Image.new("RGB", (8, 8), (8, 4, 4))
        prepared, _ = image_to_text.prepare_image(image, 1.0, 10000)
        self.assertEqual(prepared.getpixel((0, 0)), (8, 4, 4))

    def test_palette_image_with_transparency_is_flattened(self):
        image = Image.new("P", (8, 8), 0)
        image.info["transparency"] = 0
        prepared, _ = image_to_text.prepare_image(image, 1.0, 10000)
        self.assertEqual(prepared.mode, "RGB")
        self.assertEqual(prepared.getpixel((0, 0)), (255, 255, 255))


class LoadImageTests(unittest.TestCase):
    def test_missing_file_raises_ocr_error(self):
        with self.assertRaises(image_to_text.OcrError):
            image_to_text.load_image(Path("존재하지_않는_이미지.png"))

    def test_non_image_file_raises_ocr_error(self):
        with tempfile.TemporaryDirectory() as workspace:
            broken = Path(workspace) / "broken.png"
            broken.write_text("이건 이미지가 아닙니다", encoding="utf-8")
            with self.assertRaises(image_to_text.OcrError):
                image_to_text.load_image(broken)


@unittest.skipUnless(HAS_KOREAN_RECOGNIZER, "한국어 인식기가 설치되어 있지 않습니다")
class SamplePosterTests(unittest.TestCase):
    def test_recruitment_poster_yields_its_key_phrases(self):
        result = image_to_text.image_to_text(Path(__file__).resolve().parents[1] / "assets" / "samples" / "ex.png")
        self.assertIn("2026 신입 인재 모집", result.text)
        self.assertIn("여의도 본사 근무", result.text)
        self.assertIn("모집분야", result.text)

    def test_table_label_and_content_land_on_the_same_row(self):
        result = image_to_text.image_to_text(Path(__file__).resolve().parents[1] / "assets" / "samples" / "ex.png")
        rows = [row for row in result.text.splitlines() if row.startswith("근무지\t")]
        self.assertTrue(rows, "'근무지' 항목이 내용과 같은 행으로 묶이지 않았습니다")

    def test_every_stored_line_is_already_filtered(self):
        result = image_to_text.image_to_text(Path(__file__).resolve().parents[1] / "assets" / "samples" / "ex.png")
        for stored in result.lines:
            with self.subTest(text=stored.text):
                self.assertEqual(
                    stored.text, image_to_text.filter_characters(stored.text))


if __name__ == "__main__":
    unittest.main()
