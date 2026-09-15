"""Headless tests for converter_gui.ConverterApp's image tab guards."""

import unittest
import sys
import tempfile
from pathlib import Path

from PIL import Image
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import converter_gui


class ShowImageClearsStaleTextTests(unittest.TestCase):
    def test_new_image_clears_previous_result_text(self):
        app = converter_gui.ConverterApp()
        try:
            app.image_text.insert("1.0", "이전 이미지에서 추출한 텍스트")
            app._show_image(Image.new("RGB", (10, 10)), "새 이미지")
            self.assertEqual(app.image_text.get("1.0", "end-1c"), "")
        finally:
            app.destroy()


class PasteShortcutGuardTests(unittest.TestCase):
    def test_non_image_tab_lets_default_paste_run(self):
        app = converter_gui.ConverterApp()
        try:
            app.notebook.select(0)
            self.assertIsNone(app._on_paste_shortcut(None))
        finally:
            app.destroy()

    def test_focus_inside_result_box_lets_text_paste_run(self):
        app = converter_gui.ConverterApp()
        try:
            app.notebook.select(2)
            app.image_text.focus_force()
            app.update()
            self.assertIs(
                app.focus_get(), app.image_text,
                "focus did not actually land on image_text in this "
                "environment; this test would otherwise pass vacuously")
            self.assertIsNone(app._on_paste_shortcut(None))
        finally:
            app.destroy()

    def test_focus_elsewhere_on_image_tab_pastes_image(self):
        app = converter_gui.ConverterApp()
        try:
            app.notebook.select(2)
            app.preview_label.focus_force()
            app.update()

            calls = []
            app.paste_image = lambda: calls.append(True)

            result = app._on_paste_shortcut(None)

            self.assertEqual(calls, [True])
            self.assertEqual(result, "break")
        finally:
            app.destroy()


class DirectPdfTests(unittest.TestCase):
    def test_direct_pdf_refuses_when_no_image_is_loaded(self):
        # 이미지 없이 눌러도 파일 대화상자를 열거나 예외를 내지 않아야 한다.
        app = converter_gui.ConverterApp()
        try:
            warned = []
            app_messagebox = converter_gui.messagebox
            original = app_messagebox.showwarning
            app_messagebox.showwarning = lambda *a, **k: warned.append(a)
            opened = []
            original_dialog = converter_gui.filedialog.asksaveasfilename
            converter_gui.filedialog.asksaveasfilename = lambda *a, **k: opened.append(a) or ""
            try:
                app.start_direct_pdf()
            finally:
                app_messagebox.showwarning = original
                converter_gui.filedialog.asksaveasfilename = original_dialog
            self.assertTrue(warned, "이미지가 없는데 경고가 뜨지 않았습니다")
            self.assertFalse(opened, "이미지가 없는데 저장 대화상자가 열렸습니다")
        finally:
            app.destroy()


class ClipboardTempFileTests(unittest.TestCase):
    """붙여넣기한 이미지는 임시 PNG 로 떨궈 파일 불러오기와 같은 경로를 타야 한다."""

    def _paste(self, app, image):
        original = converter_gui.image_from_clipboard
        converter_gui.image_from_clipboard = lambda **kwargs: image
        try:
            app.paste_image()
        finally:
            converter_gui.image_from_clipboard = original

    def test_paste_writes_a_temp_png_that_exists(self):
        app = converter_gui.ConverterApp()
        try:
            self._paste(app, Image.new("RGB", (30, 20), "white"))
            self.assertIsNotNone(app.temp_image_path)
            self.assertTrue(app.temp_image_path.is_file())
            self.assertEqual(app.temp_image_path.suffix, ".png")
            self.assertIsNotNone(app.current_image)
        finally:
            app.destroy()

    def test_loading_another_image_removes_the_previous_temp_png(self):
        app = converter_gui.ConverterApp()
        try:
            self._paste(app, Image.new("RGB", (30, 20), "white"))
            first = app.temp_image_path
            self._paste(app, Image.new("RGB", (40, 25), "white"))
            self.assertFalse(first.exists(), "이전 임시 PNG 가 남아 있습니다")
            self.assertTrue(app.temp_image_path.is_file())
        finally:
            app.destroy()

    def test_closing_the_app_removes_the_temp_png(self):
        app = converter_gui.ConverterApp()
        self._paste(app, Image.new("RGB", (30, 20), "white"))
        path = app.temp_image_path
        app.close()
        self.assertFalse(path.exists(), "창을 닫았는데 임시 PNG 가 남아 있습니다")


def make_pdf(folder: Path, name: str, page_count: int) -> Path:
    path = folder / name
    pdf = canvas.Canvas(str(path), pagesize=(300, 400))
    for number in range(1, page_count + 1):
        pdf.drawString(50, 350, f"PAGE {number}")
        pdf.showPage()
    pdf.save()
    return path


class TabLayoutTests(unittest.TestCase):
    def test_five_tabs_in_order(self):
        app = converter_gui.ConverterApp()
        try:
            names = [app.notebook.tab(tab, "text") for tab in app.notebook.tabs()]
            self.assertEqual(names, ["파일 변환", "웹 본문 PDF", "이미지 텍스트", "PDF 합치기", "PDF 분할"])
        finally:
            app.destroy()


class PdfDestinationTests(unittest.TestCase):
    def test_adds_pdf_suffix_when_missing(self):
        self.assertEqual(converter_gui.pdf_destination("C:/out", "name"), Path("C:/out/name.pdf"))

    def test_keeps_existing_suffix_and_strips_spaces(self):
        self.assertEqual(converter_gui.pdf_destination("C:/out", " name.PDF "), Path("C:/out/name.PDF"))


class SplitTabTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.pdf = make_pdf(self.folder, "doc.pdf", 4)
        self.app = converter_gui.ConverterApp()

    def tearDown(self):
        self.app.destroy()
        self.tmp.cleanup()

    def test_choosing_a_file_loads_thumbnails_and_page_count(self):
        self.app.set_split_input(self.pdf)
        self.assertEqual(self.app.split_input.get(), str(self.pdf))
        self.assertEqual(self.app.split_picker.page_count, 4)
        self.assertEqual(self.app.split_info.get(), "전체 4쪽")
        self.assertEqual(self.app.split_pages.get(), "")

    def test_result_name_follows_the_page_field(self):
        self.app.set_split_input(self.pdf)
        self.app.split_pages.set("2-4, 7")
        self.assertEqual(self.app.split_name.get(), "doc_p2-4,7.pdf")
        self.app.split_picker.toggle(1)
        self.assertEqual(self.app.split_pages.get(), "1")
        self.assertEqual(self.app.split_name.get(), "doc_p1.pdf")

    def test_custom_result_name_is_kept(self):
        self.app.set_split_input(self.pdf)
        self.app.mark_split_name_custom()
        self.app.split_name.set("mine.pdf")
        self.app.split_pages.set("2")
        self.assertEqual(self.app.split_name.get(), "mine.pdf")

    def test_new_file_resets_custom_name(self):
        self.app.set_split_input(self.pdf)
        self.app.mark_split_name_custom()
        self.app.split_name.set("mine.pdf")
        other = make_pdf(self.folder, "other.pdf", 2)
        self.app.set_split_input(other)
        self.assertEqual(self.app.split_name.get(), "other_p.pdf")

    def test_unreadable_file_is_reported_and_not_set(self):
        bad = self.folder / "bad.pdf"
        bad.write_text("nope", encoding="utf-8")
        original = converter_gui.messagebox.showerror
        converter_gui.messagebox.showerror = lambda *args, **kwargs: None  # 모달 창이 테스트를 막지 않게
        try:
            self.app.set_split_input(bad)
        finally:
            converter_gui.messagebox.showerror = original
        self.assertEqual(self.app.split_input.get(), "")
        self.assertEqual(self.app.split_status.get(), "PDF 파일을 읽을 수 없습니다: bad.pdf")


if __name__ == "__main__":
    unittest.main()
