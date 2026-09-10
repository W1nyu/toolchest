"""Headless tests for converter_gui.ConverterApp's image tab guards."""

import unittest

from PIL import Image

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


if __name__ == "__main__":
    unittest.main()
