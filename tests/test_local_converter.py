import subprocess
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import local_converter


def make_docx_with_word(path: Path, text: str) -> None:
    script = (
        "$w = New-Object -ComObject Word.Application; $w.Visible = $false; "
        "try { $d = $w.Documents.Add(); $d.Content.Text = '" + text + "'; "
        f"$d.SaveAs2('{path}', 16); $d.Close(0) }} finally {{ $w.Quit() }}"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script],
                   check=True, capture_output=True, timeout=120)


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

    def _completed(self, returncode=0, stdout=b"", stderr=b""):
        return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)

    def test_convert_with_ms_office_runs_bridge_with_expected_arguments(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "report.docx"
            source.touch()
            destination = Path(temp) / "report.pdf"

            def fake_run(command, **kwargs):
                destination.write_bytes(b"%PDF-1.4")
                return self._completed()

            with patch.object(local_converter, "OFFICE_BRIDGE_SCRIPT", Path(__file__)), \
                 patch.object(local_converter.subprocess, "run", side_effect=fake_run) as run:
                local_converter.convert_with_ms_office(source, destination, "word")
                command = run.call_args.args[0]
                self.assertEqual(command[:5], ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"])
                self.assertEqual(command[5], str(local_converter.OFFICE_BRIDGE_SCRIPT))
                self.assertEqual(command[command.index("-InputPath") + 1], str(source))
                self.assertEqual(command[command.index("-OutputPath") + 1], str(destination))
                self.assertEqual(command[command.index("-App") + 1], "word")
                self.assertEqual(run.call_args.kwargs["timeout"], local_converter.MS_OFFICE_TIMEOUT)
                self.assertTrue(run.call_args.kwargs["capture_output"])

    def test_convert_with_ms_office_reports_bridge_stderr(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "report.docx"
            source.touch()
            completed = self._completed(returncode=1, stderr="암호로 보호된 문서입니다".encode("utf-8"))
            with patch.object(local_converter, "OFFICE_BRIDGE_SCRIPT", Path(__file__)), \
                 patch.object(local_converter.subprocess, "run", return_value=completed):
                with self.assertRaises(local_converter.ConversionError) as raised:
                    local_converter.convert_with_ms_office(source, Path(temp) / "report.pdf", "word")
            self.assertIn("암호로 보호된 문서입니다", str(raised.exception))

    def test_convert_with_ms_office_reports_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "report.docx"
            source.touch()
            error = subprocess.TimeoutExpired(cmd="powershell", timeout=300)
            with patch.object(local_converter, "OFFICE_BRIDGE_SCRIPT", Path(__file__)), \
                 patch.object(local_converter.subprocess, "run", side_effect=error):
                with self.assertRaises(local_converter.ConversionError) as raised:
                    local_converter.convert_with_ms_office(source, Path(temp) / "report.pdf", "word")
            self.assertIn("300", str(raised.exception))

    def test_convert_with_ms_office_reports_missing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "report.docx"
            source.touch()
            with patch.object(local_converter, "OFFICE_BRIDGE_SCRIPT", Path(__file__)), \
                 patch.object(local_converter.subprocess, "run", return_value=self._completed()):
                with self.assertRaises(local_converter.ConversionError) as raised:
                    local_converter.convert_with_ms_office(source, Path(temp) / "report.pdf", "word")
            self.assertIn("PDF", str(raised.exception))

    def test_bridge_office_pid_parses_marker_line(self):
        self.assertEqual(local_converter.bridge_office_pid(b"noise\r\nOFFICE_PID=4242\r\n"), 4242)
        self.assertIsNone(local_converter.bridge_office_pid(b"no marker"))
        self.assertIsNone(local_converter.bridge_office_pid(None))

    def test_convert_with_ms_office_kills_office_process_on_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "report.docx"
            source.touch()
            error = subprocess.TimeoutExpired(cmd="powershell", timeout=300, output=b"OFFICE_PID=4242\r\n")
            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)
                if command[0] == "powershell":
                    raise error
                return self._completed()

            with patch.object(local_converter, "OFFICE_BRIDGE_SCRIPT", Path(__file__)), \
                 patch.object(local_converter.subprocess, "run", side_effect=fake_run):
                with self.assertRaises(local_converter.ConversionError):
                    local_converter.convert_with_ms_office(source, Path(temp) / "report.pdf", "word")
            self.assertEqual(calls[1], ["taskkill", "/PID", "4242", "/T", "/F"])

    def test_timeout_cleanup_failure_still_raises_conversion_error(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "report.docx"
            source.touch()
            error = subprocess.TimeoutExpired(cmd="powershell", timeout=300, output=b"OFFICE_PID=4242\r\n")

            def fake_run(command, **kwargs):
                if command[0] == "powershell":
                    raise error
                raise FileNotFoundError("taskkill")

            with patch.object(local_converter, "OFFICE_BRIDGE_SCRIPT", Path(__file__)), \
                 patch.object(local_converter.subprocess, "run", side_effect=fake_run):
                with self.assertRaises(local_converter.ConversionError) as raised:
                    local_converter.convert_with_ms_office(source, Path(temp) / "report.pdf", "word")
            self.assertIn("300", str(raised.exception))

    def test_convert_office_falls_back_to_ms_office(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "report.docx"
            source.touch()
            destination = Path(temp) / "out" / "report.pdf"

            def fake_bridge(src, dst, app):
                self.assertEqual(src, source)
                self.assertEqual(app, "word")
                self.assertEqual(dst, destination.parent / ".conversion_report" / "report.pdf")
                dst.write_bytes(b"%PDF-1.4")

            with patch.object(local_converter, "find_libreoffice", return_value=None), \
                 patch.object(local_converter, "find_ms_office", return_value=True), \
                 patch.object(local_converter, "convert_with_ms_office", side_effect=fake_bridge) as bridge:
                result = local_converter.convert_office(source, destination, overwrite=False)
            bridge.assert_called_once()
            self.assertEqual(result, destination)
            self.assertEqual(destination.read_bytes(), b"%PDF-1.4")
            self.assertFalse((destination.parent / ".conversion_report").exists())

    def test_convert_office_prefers_libreoffice_when_available(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "report.docx"
            source.touch()
            destination = Path(temp) / "report.pdf"

            def fake_soffice(command):
                Path(command[command.index("--outdir") + 1], "report.pdf").write_bytes(b"%PDF-1.4")

            with patch.object(local_converter, "find_libreoffice", return_value="soffice"), \
                 patch.object(local_converter, "run_command", side_effect=fake_soffice), \
                 patch.object(local_converter, "convert_with_ms_office") as bridge:
                local_converter.convert_office(source, destination, overwrite=False)
            bridge.assert_not_called()
            self.assertTrue(destination.is_file())

    def test_convert_office_explains_when_no_engine_is_installed(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "report.docx"
            source.touch()
            with patch.object(local_converter, "find_libreoffice", return_value=None), \
                 patch.object(local_converter, "find_ms_office", return_value=False):
                with self.assertRaises(local_converter.ConversionError) as raised:
                    local_converter.convert_office(source, Path(temp) / "report.pdf", overwrite=False)
            message = str(raised.exception)
            self.assertIn("LibreOffice", message)
            self.assertIn("Microsoft Office", message)

    def test_word_bridge_exports_real_docx(self):
        if not local_converter.find_ms_office("word"):
            self.skipTest("Microsoft Word is not installed")
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "sample.docx"
            make_docx_with_word(source, "bridge test 한글")
            with patch.object(local_converter, "find_libreoffice", return_value=None):
                result = local_converter.convert(source, "pdf", Path(temp) / "out", overwrite=True)
            self.assertEqual(result, Path(temp) / "out" / "sample.pdf")
            self.assertTrue(result.read_bytes().startswith(b"%PDF"))

    def test_word_bridge_reports_readable_error_for_broken_file(self):
        if not local_converter.find_ms_office("word"):
            self.skipTest("Microsoft Word is not installed")
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "broken.docx"
            source.write_bytes(b"this is not a docx file")
            with patch.object(local_converter, "find_libreoffice", return_value=None):
                with self.assertRaises(local_converter.ConversionError) as raised:
                    local_converter.convert(source, "pdf", Path(temp) / "out", overwrite=True)
            message = str(raised.exception)
            self.assertIn("Microsoft Office", message)
            self.assertNotIn("�", message)
            self.assertGreater(len(message), len("Microsoft Office 변환에 실패했습니다."))
        leftover = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process WINWORD -ErrorAction SilentlyContinue).Count"],
            capture_output=True, text=True, timeout=60).stdout.strip()
        self.assertIn(leftover, {"", "0"})


if __name__ == "__main__":
    unittest.main()
