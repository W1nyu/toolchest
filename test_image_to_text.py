import unittest

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


if __name__ == "__main__":
    unittest.main()
