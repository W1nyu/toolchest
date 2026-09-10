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


if __name__ == "__main__":
    unittest.main()
