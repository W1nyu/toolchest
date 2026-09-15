"""pdf_pages: 페이지 범위 파싱·표기, 합치기·분할, 썸네일 렌더링 테스트."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pdf_pages
from pdf_pages import PdfPagesError, format_page_range, parse_page_range


class ParsePageRangeTests(unittest.TestCase):
    def test_empty_text_means_every_page(self):
        self.assertEqual(parse_page_range("", 4), [1, 2, 3, 4])
        self.assertEqual(parse_page_range("   ", 2), [1, 2])

    def test_ranges_and_single_pages(self):
        self.assertEqual(parse_page_range("1-3, 5, 8-10", 12), [1, 2, 3, 5, 8, 9, 10])

    def test_keeps_the_written_order(self):
        self.assertEqual(parse_page_range("3,1,2", 3), [3, 1, 2])

    def test_allows_duplicates(self):
        self.assertEqual(parse_page_range("1,1", 3), [1, 1])

    def test_accepts_fullwidth_and_ideographic_commas(self):
        self.assertEqual(parse_page_range("1，2、3", 3), [1, 2, 3])

    def test_ignores_spaces_around_hyphen(self):
        self.assertEqual(parse_page_range(" 2 - 3 ", 3), [2, 3])

    def test_reversed_range_is_rejected(self):
        with self.assertRaises(PdfPagesError) as caught:
            parse_page_range("5-3", 12)
        self.assertEqual(str(caught.exception), "페이지 범위는 작은 수에서 큰 수 순서여야 합니다: 5-3")

    def test_out_of_range_is_rejected(self):
        with self.assertRaises(PdfPagesError) as caught:
            parse_page_range("13", 12)
        self.assertEqual(str(caught.exception), "1부터 12 사이의 페이지만 지정할 수 있습니다: 13")
        with self.assertRaises(PdfPagesError):
            parse_page_range("0", 12)

    def test_garbage_is_rejected(self):
        for text in ("a", "1-", "-3", "1--3"):
            with self.assertRaises(PdfPagesError, msg=text) as caught:
                parse_page_range(text, 12)
            self.assertTrue(str(caught.exception).startswith("페이지 지정을 이해할 수 없습니다: "), text)


class FormatPageRangeTests(unittest.TestCase):
    def test_compresses_consecutive_pages(self):
        self.assertEqual(format_page_range({1, 2, 3, 5}), "1-3, 5")

    def test_single_page(self):
        self.assertEqual(format_page_range({2}), "2")

    def test_two_consecutive_pages_use_a_hyphen(self):
        self.assertEqual(format_page_range({4, 5}), "4-5")

    def test_empty_set_is_empty_string(self):
        self.assertEqual(format_page_range(set()), "")

    def test_ignores_duplicates_and_sorts(self):
        self.assertEqual(format_page_range([5, 1, 1, 2]), "1-2, 5")

    def test_round_trip(self):
        pages = {1, 2, 3, 7, 9, 10}
        self.assertEqual(parse_page_range(format_page_range(pages), 10), sorted(pages))


if __name__ == "__main__":
    unittest.main()
