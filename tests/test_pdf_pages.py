"""pdf_pages: 페이지 범위 파싱·표기, 합치기·분할, 썸네일 렌더링 테스트."""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pdf_pages
from pdf_pages import PdfPagesError, format_page_range, parse_page_range


def make_pdf(folder: Path, name: str, page_count: int, label: str = "PAGE") -> Path:
    """각 쪽에 "{label} n"이 적힌 page_count쪽짜리 PDF를 만든다. 결과 쪽의 출처를 확인하는 데 쓴다."""
    path = folder / name
    pdf = canvas.Canvas(str(path), pagesize=(300, 400))
    for number in range(1, page_count + 1):
        pdf.drawString(50, 350, f"{label} {number}")
        pdf.showPage()
    pdf.save()
    return path


def page_texts(path: Path) -> list[str]:
    return [page.extract_text().strip() for page in PdfReader(path).pages]


def make_encrypted_pdf(folder: Path, name: str) -> Path:
    plain = make_pdf(folder, f"plain-{name}", 1)
    writer = PdfWriter(clone_from=PdfReader(plain))
    writer.encrypt("secret")
    path = folder / name
    with open(path, "wb") as handle:
        writer.write(handle)
    return path


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


class PageCountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_pages(self):
        self.assertEqual(pdf_pages.pdf_page_count(make_pdf(self.folder, "a.pdf", 3)), 3)

    def test_non_pdf_is_rejected(self):
        bad = self.folder / "bad.pdf"
        bad.write_text("hello", encoding="utf-8")
        with self.assertRaises(PdfPagesError) as caught:
            pdf_pages.pdf_page_count(bad)
        self.assertEqual(str(caught.exception), "PDF 파일을 읽을 수 없습니다: bad.pdf")

    def test_missing_file_is_rejected(self):
        with self.assertRaises(PdfPagesError):
            pdf_pages.pdf_page_count(self.folder / "nope.pdf")

    def test_encrypted_pdf_is_rejected(self):
        locked = make_encrypted_pdf(self.folder, "locked.pdf")
        with self.assertRaises(PdfPagesError) as caught:
            pdf_pages.pdf_page_count(locked)
        self.assertEqual(str(caught.exception), "암호가 걸린 PDF는 지원하지 않습니다: locked.pdf")


class RenderPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_renders_requested_width_and_keeps_aspect(self):
        image = pdf_pages.render_page(make_pdf(self.folder, "a.pdf", 2), 2, width=110)
        self.assertEqual(image.mode, "RGB")
        self.assertEqual(image.width, 110)
        # 300×400pt 쪽이므로 높이는 110 * 400 / 300 ≈ 147
        self.assertTrue(140 <= image.height <= 150, image.height)

    def test_bad_page_number_is_rejected(self):
        with self.assertRaises(PdfPagesError):
            pdf_pages.render_page(make_pdf(self.folder, "a.pdf", 2), 3)


class MergePdfsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.a = make_pdf(self.folder, "a.pdf", 3, "A")
        self.b = make_pdf(self.folder, "b.pdf", 2, "B")
        self.out = self.folder / "out" / "merged.pdf"

    def tearDown(self):
        self.tmp.cleanup()

    def test_merges_whole_files_in_order(self):
        result = pdf_pages.merge_pdfs([(self.a, ""), (self.b, "")], self.out)
        self.assertEqual(result, self.out)
        self.assertEqual(page_texts(self.out), ["A 1", "A 2", "A 3", "B 1", "B 2"])

    def test_merges_selected_pages_only(self):
        pdf_pages.merge_pdfs([(self.a, "1-2"), (self.b, "2")], self.out)
        self.assertEqual(page_texts(self.out), ["A 1", "A 2", "B 2"])

    def test_source_order_is_respected(self):
        pdf_pages.merge_pdfs([(self.b, ""), (self.a, "3,1")], self.out)
        self.assertEqual(page_texts(self.out), ["B 1", "B 2", "A 3", "A 1"])

    def test_originals_are_untouched(self):
        before = [(p.stat().st_size, p.stat().st_mtime_ns) for p in (self.a, self.b)]
        pdf_pages.merge_pdfs([(self.a, ""), (self.b, "")], self.out)
        after = [(p.stat().st_size, p.stat().st_mtime_ns) for p in (self.a, self.b)]
        self.assertEqual(before, after)

    def test_fewer_than_two_sources_is_rejected(self):
        with self.assertRaises(PdfPagesError) as caught:
            pdf_pages.merge_pdfs([(self.a, "")], self.out)
        self.assertEqual(str(caught.exception), "PDF를 2개 이상 지정하세요.")

    def test_bad_page_on_a_later_file_leaves_no_output(self):
        with self.assertRaises(PdfPagesError):
            pdf_pages.merge_pdfs([(self.a, ""), (self.b, "9")], self.out)
        self.assertFalse(self.out.exists())
        self.assertEqual(list(self.folder.glob("out/*")), [])

    def test_existing_destination_needs_overwrite(self):
        pdf_pages.merge_pdfs([(self.a, ""), (self.b, "")], self.out)
        with self.assertRaises(PdfPagesError) as caught:
            pdf_pages.merge_pdfs([(self.a, "1"), (self.b, "1")], self.out)
        self.assertEqual(str(caught.exception), f"같은 이름의 PDF가 이미 있습니다: {self.out}")
        pdf_pages.merge_pdfs([(self.a, "1"), (self.b, "1")], self.out, overwrite=True)
        self.assertEqual(page_texts(self.out), ["A 1", "B 1"])

    def test_no_temporary_file_is_left_behind(self):
        pdf_pages.merge_pdfs([(self.a, ""), (self.b, "")], self.out)
        self.assertEqual([p.name for p in self.out.parent.iterdir()], ["merged.pdf"])


class SplitPdfTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.source = make_pdf(self.folder, "doc.pdf", 5)
        self.out = self.folder / "doc_p2-3.pdf"

    def tearDown(self):
        self.tmp.cleanup()

    def test_keeps_only_selected_pages(self):
        pdf_pages.split_pdf(self.source, "2-3", self.out)
        self.assertEqual(page_texts(self.out), ["PAGE 2", "PAGE 3"])
        self.assertEqual(len(PdfReader(self.source).pages), 5)

    def test_empty_pages_is_rejected(self):
        with self.assertRaises(PdfPagesError) as caught:
            pdf_pages.split_pdf(self.source, "  ", self.out)
        self.assertEqual(str(caught.exception), "분리할 페이지를 입력하세요.")
        self.assertFalse(self.out.exists())

    def test_existing_destination_needs_overwrite(self):
        pdf_pages.split_pdf(self.source, "2-3", self.out)
        with self.assertRaises(PdfPagesError):
            pdf_pages.split_pdf(self.source, "1", self.out)
        pdf_pages.split_pdf(self.source, "1", self.out, overwrite=True)
        self.assertEqual(page_texts(self.out), ["PAGE 1"])


class AutoNameTests(unittest.TestCase):
    def test_merged_name_uses_first_file_stem(self):
        self.assertEqual(pdf_pages.merged_name(Path("C:/x/report.pdf")), "report_합본.pdf")

    def test_split_name_strips_spaces_from_pages(self):
        self.assertEqual(pdf_pages.split_name("doc.pdf", "2-4, 7"), "doc_p2-4,7.pdf")


class SourceArgumentTests(unittest.TestCase):
    def test_plain_path_has_no_pages(self):
        self.assertEqual(pdf_pages._split_source_argument("a.pdf"), ("a.pdf", ""))

    def test_pages_after_last_colon(self):
        self.assertEqual(pdf_pages._split_source_argument("b.pdf:1-3,5"), ("b.pdf", "1-3,5"))

    def test_windows_drive_colon_is_not_a_page_separator(self):
        self.assertEqual(pdf_pages._split_source_argument(r"C:\docs\a.pdf"), (r"C:\docs\a.pdf", ""))
        self.assertEqual(pdf_pages._split_source_argument(r"C:\docs\a.pdf:2"), (r"C:\docs\a.pdf", "2"))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.a = make_pdf(self.folder, "a.pdf", 3, "A")
        self.b = make_pdf(self.folder, "b.pdf", 2, "B")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = pdf_pages.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_merge_with_explicit_output(self):
        out = self.folder / "m.pdf"
        code, stdout, _ = self.run_cli("merge", str(self.a), f"{self.b}:2", "--output", str(out))
        self.assertEqual(code, 0)
        self.assertIn(str(out), stdout)
        self.assertEqual(page_texts(out), ["A 1", "A 2", "A 3", "B 2"])

    def test_merge_default_name_in_output_dir(self):
        code, _, _ = self.run_cli("merge", str(self.a), str(self.b), "--output-dir", str(self.folder / "res"))
        self.assertEqual(code, 0)
        self.assertTrue((self.folder / "res" / "a_합본.pdf").exists())

    def test_split_default_name(self):
        code, _, _ = self.run_cli("split", str(self.a), "--pages", "1, 3", "--output-dir", str(self.folder))
        self.assertEqual(code, 0)
        self.assertEqual(page_texts(self.folder / "a_p1,3.pdf"), ["A 1", "A 3"])

    def test_error_goes_to_stderr_with_exit_1(self):
        code, _, stderr = self.run_cli("split", str(self.a), "--pages", "9", "--output-dir", str(self.folder))
        self.assertEqual(code, 1)
        self.assertIn("1부터 3 사이의 페이지만 지정할 수 있습니다: 9", stderr)


if __name__ == "__main__":
    unittest.main()
