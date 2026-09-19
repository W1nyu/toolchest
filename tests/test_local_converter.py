import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import local_converter


class LocalConverterTests(unittest.TestCase):
    def test_output_path_uses_input_stem_and_target_extension(self):
        source = Path("C:/work/my video.mp4")
        self.assertEqual(
            local_converter.output_path(source, "mp3", Path("C:/out")),
            Path("C:/out/my video.mp3"),
        )

    def test_media_command_contains_audio_only_options_for_mp3(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "clip.mp4"
            source.touch()
            with patch.object(local_converter, "find_executable", return_value="ffmpeg"), \
                 patch.object(local_converter, "run_command") as run:
                local_converter.convert_media(source, Path(temp) / "clip.mp3", False)
            command = run.call_args.args[0]
            self.assertIn("-vn", command)
            self.assertIn("libmp3lame", command)

    def test_missing_input_is_reported(self):
        with self.assertRaises(local_converter.ConversionError):
            local_converter.convert(Path("does-not-exist.mp4"), "mp3")

    def test_unknown_media_extension_is_delegated_to_ffmpeg(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "custom.input-format"
            source.touch()
            with patch.object(local_converter, "find_executable", return_value="ffmpeg"), \
                 patch.object(local_converter, "run_command") as run:
                local_converter.convert(source, "custom-output", Path(temp), True)
            self.assertEqual(run.call_args.args[0][-1], str(Path(temp) / "custom.custom-output"))

    def test_office_extensions_match_ms_office_app_mapping(self):
        mapped = set().union(*local_converter.MS_OFFICE_APPS.values())
        self.assertEqual(mapped, local_converter.OFFICE_EXTENSIONS)

    def test_ms_office_app_for_maps_each_family(self):
        self.assertEqual(local_converter.ms_office_app_for(".docx"), "word")
        self.assertEqual(local_converter.ms_office_app_for(".rtf"), "word")
        self.assertEqual(local_converter.ms_office_app_for(".PPTX"), "powerpoint")
        self.assertEqual(local_converter.ms_office_app_for(".odp"), "powerpoint")
        self.assertEqual(local_converter.ms_office_app_for(".xlsx"), "excel")
        self.assertEqual(local_converter.ms_office_app_for(".csv"), "excel")
        self.assertIsNone(local_converter.ms_office_app_for(".mp4"))

    def test_find_ms_office_checks_progid_in_registry(self):
        import types
        opened = []

        class Key:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def open_key(root, name):
            opened.append(name)
            if name == "Word.Application":
                return Key()
            raise OSError("missing")

        fake_winreg = types.SimpleNamespace(HKEY_CLASSES_ROOT=object(), OpenKey=open_key)
        with patch.dict(sys.modules, {"winreg": fake_winreg}):
            self.assertTrue(local_converter.find_ms_office("word"))
            self.assertFalse(local_converter.find_ms_office("excel"))
        self.assertEqual(opened, ["Word.Application", "Excel.Application"])

    def test_find_ms_office_is_false_without_winreg(self):
        with patch.dict(sys.modules, {"winreg": None}):
            self.assertFalse(local_converter.find_ms_office("word"))


if __name__ == "__main__":
    unittest.main()
