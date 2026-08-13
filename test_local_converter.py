import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
