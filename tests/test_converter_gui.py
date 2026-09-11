"""Headless tests for converter_gui.ConverterApp's image tab guards."""

import unittest
import sys
from pathlib import Path

from PIL import Image

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


if __name__ == "__main__":
    unittest.main()
