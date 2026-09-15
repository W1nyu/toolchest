"""page_picker.PagePicker 헤드리스 테스트. 썸네일 클릭과 페이지 칸이 서로 맞물리는지 본다."""

import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path

from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import page_picker
from page_picker import PagePicker


def make_pdf(folder: Path, name: str, page_count: int) -> Path:
    path = folder / name
    pdf = canvas.Canvas(str(path), pagesize=(300, 400))
    for number in range(1, page_count + 1):
        pdf.drawString(50, 350, f"PAGE {number}")
        pdf.showPage()
    pdf.save()
    return path


def pump(widget, condition, timeout=5.0):
    """메인 루프 없이 after 콜백을 돌려 condition이 참이 될 때까지 기다린다."""
    deadline = time.time() + timeout
    while not condition():
        widget.update()
        time.sleep(0.02)
        if time.time() > deadline:
            raise AssertionError("timed out waiting for the picker")


class PagePickerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pdf = make_pdf(Path(self.tmp.name), "doc.pdf", 3)
        self.root = tk.Tk()
        self.pages = tk.StringVar(master=self.root)
        self.status = tk.StringVar(master=self.root)
        self.picker = PagePicker(self.root, self.pages, self.status)
        self.picker.pack()
        self.picker.load(self.pdf)

    def tearDown(self):
        pump(self.root, lambda: not self.picker.is_rendering())
        self.root.destroy()
        self.tmp.cleanup()

    def test_load_reports_page_count_and_starts_empty(self):
        self.assertEqual(self.picker.page_count, 3)
        self.assertEqual(self.picker.selected_pages(), set())

    def test_typing_in_the_field_selects_thumbnails(self):
        self.pages.set("1-2")
        self.assertEqual(self.picker.selected_pages(), {1, 2})

    def test_clicking_thumbnails_fills_the_field(self):
        self.picker.toggle(3)
        self.picker.toggle(1)
        self.assertEqual(self.pages.get(), "1, 3")
        self.picker.toggle(2)
        self.assertEqual(self.pages.get(), "1-3")
        self.picker.toggle(1)
        self.assertEqual(self.pages.get(), "2-3")

    def test_invalid_text_keeps_last_selection_and_reports(self):
        self.pages.set("1-2")
        self.pages.set("9")
        self.assertEqual(self.picker.selected_pages(), {1, 2})
        self.assertEqual(self.status.get(), "1부터 3 사이의 페이지만 지정할 수 있습니다: 9")

    def test_empty_text_clears_selection(self):
        self.pages.set("1-2")
        self.pages.set("")
        self.assertEqual(self.picker.selected_pages(), set())

    def test_thumbnails_are_rendered_in_the_background(self):
        pump(self.root, lambda: len(self.picker._photos) == 3)
        self.assertEqual(sorted(self.picker._photos), [1, 2, 3])

    def test_load_none_clears_everything(self):
        self.pages.set("1")
        self.picker.load(None)
        self.assertEqual(self.picker.page_count, 0)
        self.assertEqual(self.picker.selected_pages(), set())
        self.assertEqual(self.picker._cells, [])

    def test_missing_renderer_reports_once_without_crashing(self):
        original = page_picker.render_page

        def broken(*args, **kwargs):
            raise ImportError("no pypdfium2")

        page_picker.render_page = broken
        try:
            self.picker._cache.clear()  # setUp이 이미 그린 썸네일이 캐시에 있으면 render_page가 불리지 않는다
            self.picker.load(self.pdf)
            pump(self.root, lambda: not self.picker.is_rendering())
            pump(self.root, lambda: self.status.get() == page_picker.MISSING_RENDERER_MESSAGE)
        finally:
            page_picker.render_page = original


if __name__ == "__main__":
    unittest.main()
