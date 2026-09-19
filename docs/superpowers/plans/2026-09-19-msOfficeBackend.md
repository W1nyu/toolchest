# MS Office 백엔드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LibreOffice가 없는 PC에서도 설치된 Microsoft Word/PowerPoint/Excel로 Office 문서를 PDF로 변환한다.

**Architecture:** `local_converter.convert_office`가 LibreOffice를 못 찾으면 확장자에 맞는 MS Office 앱을 `winreg`로 감지하고, 새 PowerShell 브리지 `src/win_office.ps1`을 subprocess로 실행해 임시 폴더에 PDF를 만든다. 임시 PDF를 최종 경로로 옮기고 압축하는 기존 코드는 두 경로가 공유한다.

**Tech Stack:** Python 3.10+ 표준 라이브러리(`winreg`, `subprocess`), Windows PowerShell 5.1 + Office COM 자동화, `unittest`.

## Global Constraints

- pip 의존성 추가 금지. `requirements.txt` 변경 없음.
- 원본 파일은 읽기 전용으로만 열고 절대 수정하지 않는다.
- 실패해도 Office 프로세스(WINWORD/POWERPNT/EXCEL)가 남지 않아야 한다.
- LibreOffice가 있으면 기존 동작을 그대로 유지한다.
- HWP/HWPX는 범위 밖.
- 테스트는 `unittest` + `unittest.mock.patch` 스타일(기존 `tests/test_local_converter.py`와 동일).
- PowerShell 스크립트는 UTF-8 BOM으로 저장한다(한글 주석 보호).
- 테스트 실행 명령: `python -m unittest tests.test_local_converter -v` (프로젝트 루트에서).
- 커밋 메시지는 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` 줄로 끝낸다.

---

## File Structure

- Modify `src/local_converter.py` — 상수 `MS_OFFICE_APPS`, `MS_OFFICE_PROGIDS`, `OFFICE_BRIDGE_SCRIPT`, `MS_OFFICE_TIMEOUT`; 새 함수 `ms_office_app_for`, `find_ms_office`, `convert_with_ms_office`; `convert_office` 분기 변경.
- Create `src/win_office.ps1` — Word/PowerPoint/Excel COM으로 PDF 내보내기.
- Modify `src/converter_gui.py:18,286` — 확장자 집합을 `OFFICE_EXTENSIONS`로 교체.
- Modify `tests/test_local_converter.py` — 단위 테스트 + Word 통합 테스트.
- Modify `README.md`, `docs/guides/fileConverter_GUIDE.html` — 문서.

---

### Task 1: 확장자 → 앱 매핑과 MS Office 감지

**Files:**
- Modify: `src/local_converter.py:12` (상수 추가), `:36` 근처 (`find_libreoffice` 아래 함수 추가)
- Test: `tests/test_local_converter.py`

**Interfaces:**
- Produces:
  - `MS_OFFICE_APPS: dict[str, set[str]]` — 키 `"word" | "powerpoint" | "excel"`, 값은 소문자 확장자(점 포함) 집합
  - `MS_OFFICE_PROGIDS: dict[str, str]`
  - `OFFICE_BRIDGE_SCRIPT: Path`, `MS_OFFICE_TIMEOUT: int = 300`
  - `ms_office_app_for(suffix: str) -> str | None`
  - `find_ms_office(app: str) -> bool`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_local_converter.py`의 `LocalConverterTests` 클래스 안, `test_unknown_media_extension_is_delegated_to_ffmpeg` 아래에 추가:

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `python -m unittest tests.test_local_converter -v`
Expected: 새 테스트 4개 ERROR — `AttributeError: module 'local_converter' has no attribute 'MS_OFFICE_APPS'` 등.

- [ ] **Step 3: 구현**

`src/local_converter.py`의 `OFFICE_EXTENSIONS` 줄 바로 아래에 추가:

```python
MS_OFFICE_APPS = {
    "word": {".doc", ".docx", ".odt", ".rtf"},
    "powerpoint": {".ppt", ".pptx", ".odp"},
    "excel": {".xls", ".xlsx", ".ods", ".csv"},
}
MS_OFFICE_PROGIDS = {"word": "Word.Application", "powerpoint": "PowerPoint.Application", "excel": "Excel.Application"}
OFFICE_BRIDGE_SCRIPT = Path(__file__).with_name("win_office.ps1")
MS_OFFICE_TIMEOUT = 300
```

`find_libreoffice` 함수 바로 아래에 추가:

```python
def ms_office_app_for(suffix: str) -> str | None:
    """Return which Microsoft Office application opens files with this extension."""
    for app, extensions in MS_OFFICE_APPS.items():
        if suffix.lower() in extensions:
            return app
    return None


def find_ms_office(app: str) -> bool:
    """Check whether the Office application's COM ProgID is registered, without launching it."""
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, MS_OFFICE_PROGIDS[app]):
            return True
    except OSError:
        return False
```

참고: `patch.dict(sys.modules, {"winreg": None})`이면 `import winreg`가 `ImportError`를 내므로 첫 `except`에서 잡힌다.

- [ ] **Step 4: 통과 확인**

Run: `python -m unittest tests.test_local_converter -v`
Expected: `Ran 8 tests` OK.

- [ ] **Step 5: 커밋**

```bash
git add src/local_converter.py tests/test_local_converter.py
git commit -m "feat: detect installed Microsoft Office apps by extension

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: PowerShell 브리지 호출 `convert_with_ms_office`

**Files:**
- Modify: `src/local_converter.py` (`convert_media` 아래, `compress_pdf` 위에 추가)
- Test: `tests/test_local_converter.py`

**Interfaces:**
- Consumes: `OFFICE_BRIDGE_SCRIPT`, `MS_OFFICE_TIMEOUT` (Task 1), `ConversionError` (기존)
- Produces: `convert_with_ms_office(source: Path, destination: Path, app: str) -> None` — 성공 시 `destination`에 PDF가 존재. 실패 시 `ConversionError`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_local_converter.py` 상단 import에 `import subprocess`를 추가한다. 클래스 안에 추가:

```python
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
```

참고: `OFFICE_BRIDGE_SCRIPT` 파일은 Task 4에서 만들어지므로, 여기서는 존재하는 아무 파일(`Path(__file__)`)로 patch해 구현의 '스크립트 없음' 검사를 통과시킨다.

- [ ] **Step 2: 실패 확인**

Run: `python -m unittest tests.test_local_converter -v`
Expected: 새 테스트 4개 ERROR — `AttributeError: ... has no attribute 'convert_with_ms_office'`.

- [ ] **Step 3: 구현**

`src/local_converter.py`의 `convert_media` 함수 바로 아래에 추가:

```python
def convert_with_ms_office(source: Path, destination: Path, app: str) -> None:
    """Export a document to PDF with the installed Microsoft Office app via win_office.ps1."""
    if not OFFICE_BRIDGE_SCRIPT.is_file():
        raise ConversionError(f"Office 브리지 스크립트를 찾을 수 없습니다: {OFFICE_BRIDGE_SCRIPT}")
    command = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(OFFICE_BRIDGE_SCRIPT),
        "-InputPath", str(source), "-OutputPath", str(destination), "-App", app,
    ]
    try:
        completed = subprocess.run(command, capture_output=True, timeout=MS_OFFICE_TIMEOUT)
    except FileNotFoundError as exc:
        raise ConversionError("PowerShell을 찾지 못했습니다. Windows에서 실행해야 합니다.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ConversionError(f"Microsoft Office 변환이 {MS_OFFICE_TIMEOUT}초 안에 끝나지 않았습니다. "
                              "문서를 직접 열어 경고 창이 뜨는지 확인하세요.") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", "replace").strip() \
            or (completed.stdout or b"").decode("utf-8", "replace").strip()
        raise ConversionError(f"Microsoft Office 변환에 실패했습니다. {detail[:300]}".strip())
    if not destination.is_file():
        raise ConversionError("Microsoft Office가 PDF를 만들지 않았습니다.")
```

- [ ] **Step 4: 통과 확인**

Run: `python -m unittest tests.test_local_converter -v`
Expected: `Ran 12 tests` OK.

- [ ] **Step 5: 커밋**

```bash
git add src/local_converter.py tests/test_local_converter.py
git commit -m "feat: run win_office.ps1 bridge for Microsoft Office PDF export

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

#### Task 2 보강: 타임아웃 시 Office 프로세스 정리

리뷰에서 확인된 빈틈: `subprocess.run`의 타임아웃은 `powershell.exe`만 죽이므로, 브리지가 띄운 WINWORD/POWERPNT/EXCEL은 고아 프로세스로 남는다(ps1의 `finally`는 실행되지 않는다). 브리지는 COM 객체를 만든 직후 stdout에 `OFFICE_PID=<pid>` 한 줄을 출력하고(Task 4), Python은 타임아웃 시 부분 stdout에서 그 PID를 읽어 `taskkill`로 끝낸다.

- [ ] **Step 6: 실패하는 테스트 작성**

```python
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
```

- [ ] **Step 7: 실패 확인**

Run: `python -m unittest tests.test_local_converter -v`
Expected: 2개 ERROR — `AttributeError: ... has no attribute 'bridge_office_pid'`; 두 번째 테스트는 `IndexError`(taskkill 호출 없음) 또는 같은 AttributeError.

- [ ] **Step 8: 구현**

`src/local_converter.py` 상단 import에 `import re`를 추가하고, `convert_with_ms_office` 바로 위에 추가:

```python
OFFICE_PID_MARKER = re.compile(rb"^OFFICE_PID=(\d+)\s*$", re.MULTILINE)


def bridge_office_pid(stdout: bytes | None) -> int | None:
    """Read the Office process id that win_office.ps1 prints right after it launches the app."""
    match = OFFICE_PID_MARKER.search(stdout or b"")
    return int(match.group(1)) if match else None


def kill_process_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
```

`convert_with_ms_office`의 `TimeoutExpired` 처리를 다음으로 교체:

```python
    except subprocess.TimeoutExpired as exc:
        # powershell.exe 만 죽고 브리지가 띄운 Office 는 남으므로, 브리지가 알려준 PID 로 직접 끝낸다.
        pid = bridge_office_pid(exc.stdout)
        if pid:
            kill_process_tree(pid)
        raise ConversionError(f"Microsoft Office 변환이 {MS_OFFICE_TIMEOUT}초 안에 끝나지 않았습니다. "
                              "문서를 직접 열어 경고 창이 뜨는지 확인하세요.") from exc
```

- [ ] **Step 9: 통과 확인**

Run: `python -m unittest tests.test_local_converter -v`
Expected: `Ran 14 tests` OK.

- [ ] **Step 10: 커밋**

```bash
git add src/local_converter.py tests/test_local_converter.py
git commit -m "fix: kill the Office process the bridge launched when the conversion times out

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `convert_office` 분기 — LibreOffice 없으면 MS Office

**Files:**
- Modify: `src/local_converter.py` `convert_office` (현재 141-165행)
- Test: `tests/test_local_converter.py`

**Interfaces:**
- Consumes: `find_libreoffice`, `ms_office_app_for`, `find_ms_office`, `convert_with_ms_office`
- Produces: `convert_office` 시그니처 불변 `(source, destination, overwrite, compress=False, quality="ebook") -> Path`

- [ ] **Step 1: 실패하는 테스트 작성**

클래스 안에 추가:

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `python -m unittest tests.test_local_converter -v`
Expected: `test_convert_office_falls_back_to_ms_office` ERROR(`ConversionError: LibreOffice was not found`), `test_convert_office_explains_when_no_engine_is_installed` FAIL(메시지에 "Microsoft Office" 없음). `prefers_libreoffice`는 통과.

- [ ] **Step 3: 구현**

`convert_office` 전체를 다음으로 교체:

```python
def convert_office(source: Path, destination: Path, overwrite: bool, compress: bool = False, quality: str = "ebook") -> Path:
    soffice = find_libreoffice()
    ms_app = None if soffice else ms_office_app_for(source.suffix)
    if not soffice and not (ms_app and find_ms_office(ms_app)):
        raise ConversionError(
            "Office 문서를 PDF로 바꾸려면 LibreOffice 또는 Microsoft Office(Word/PowerPoint/Excel)가 필요합니다. "
            "LibreOffice: https://www.libreoffice.org/download/download/")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = destination.parent / f".conversion_{source.stem}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        generated = temp_dir / f"{source.stem}.pdf"
        if soffice:
            run_command([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(temp_dir), str(source)])
            if not generated.exists():
                raise ConversionError("LibreOffice did not create a PDF file.")
        else:
            convert_with_ms_office(source, generated, ms_app)
        if destination.exists() and not overwrite:
            raise ConversionError(f"Output already exists: {destination} (use --overwrite to replace it)")
        if destination.exists():
            destination.unlink()
        generated.replace(destination)
        if compress:
            compress_pdf(destination, destination, True, quality)
        return destination
    finally:
        try:
            temp_dir.rmdir()
        except OSError:
            pass
```

- [ ] **Step 4: 통과 확인**

Run: `python -m unittest tests.test_local_converter -v`
Expected: `Ran 15 tests` OK.

- [ ] **Step 5: 커밋**

```bash
git add src/local_converter.py tests/test_local_converter.py
git commit -m "feat: fall back to Microsoft Office when LibreOffice is missing

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: PowerShell 브리지 `src/win_office.ps1` + Word 통합 테스트

**Files:**
- Create: `src/win_office.ps1`
- Test: `tests/test_local_converter.py`

**Interfaces:**
- Consumes: Task 2의 호출 규약 `-InputPath <file> -OutputPath <pdf> -App word|powerpoint|excel`
- Produces: 종료 코드 0 + `OutputPath`에 PDF. 실패 시 stderr 메시지 + 종료 코드 1.

- [ ] **Step 1: 통합 테스트 작성 (Word 없으면 skip)**

클래스 안에 추가:

```python
    def test_word_bridge_exports_real_docx(self):
        if not local_converter.find_ms_office("word"):
            self.skipTest("Microsoft Word is not installed")
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "sample.docx"
            make_docx = (
                "$w = New-Object -ComObject Word.Application; $w.Visible = $false; "
                "$d = $w.Documents.Add(); $d.Content.Text = 'bridge test 한글'; "
                f"$d.SaveAs2('{source}', 16); $d.Close(0); $w.Quit()"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", make_docx],
                           check=True, capture_output=True, timeout=120)
            with patch.object(local_converter, "find_libreoffice", return_value=None):
                result = local_converter.convert(source, "pdf", Path(temp) / "out", overwrite=True)
            self.assertEqual(result, Path(temp) / "out" / "sample.pdf")
            self.assertTrue(result.read_bytes().startswith(b"%PDF"))
```

- [ ] **Step 2: 실패 확인**

Run: `python -m unittest tests.test_local_converter.LocalConverterTests.test_word_bridge_exports_real_docx -v`
Expected: ERROR — `ConversionError: Office 브리지 스크립트를 찾을 수 없습니다: ...win_office.ps1`.

- [ ] **Step 3: 브리지 작성**

`src/win_office.ps1`을 UTF-8 BOM으로 생성한다. Write 도구로 만든 뒤 BOM을 보장하려면 프로젝트 루트에서:

```powershell
$p = "src\win_office.ps1"; $t = Get-Content $p -Raw -Encoding UTF8; [System.IO.File]::WriteAllText((Resolve-Path $p), $t, (New-Object System.Text.UTF8Encoding $true))
```

내용:

```powershell
param(
    [Parameter(Mandatory = $true)][string]$InputPath,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [Parameter(Mandatory = $true)][ValidateSet('word', 'powerpoint', 'excel')][string]$App
)

# Word/PowerPoint/Excel 을 COM 으로 띄워 문서를 PDF 로 내보낸다.
# 원본은 읽기 전용으로만 열고, 어떤 경우에도 finally 에서 앱을 종료한다.

$ErrorActionPreference = 'Stop'
$processNames = @{ word = 'WINWORD'; powerpoint = 'POWERPNT'; excel = 'EXCEL' }
$application = $null
$document = $null
$ownsApplication = $false
$exitCode = 1

function Get-OfficePids([string]$name) {
    @(Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
}

try {
    # COM 은 현재 작업 폴더를 기준으로 상대 경로를 풀지 않으므로 절대 경로로 바꾼다.
    $inputFile = (Resolve-Path -LiteralPath $InputPath).Path
    $outputFile = [System.IO.Path]::GetFullPath($OutputPath)

    # New-Object 가 새 프로세스를 만들었는지 프로세스 목록 차이로 알아낸다.
    # Word/Excel 은 항상 새 인스턴스를 만들지만 PowerPoint 는 이미 떠 있는 인스턴스에 붙는다.
    # 그 경우 사용자의 PowerPoint 를 Quit 하면 안 되므로 $ownsApplication 으로 구분한다.
    $before = Get-OfficePids $processNames[$App]
    switch ($App) {
        'word' { $application = New-Object -ComObject Word.Application }
        'powerpoint' { $application = New-Object -ComObject PowerPoint.Application }
        'excel' { $application = New-Object -ComObject Excel.Application }
    }
    $launched = @(Get-OfficePids $processNames[$App] | Where-Object { $before -notcontains $_ })
    $ownsApplication = $launched.Count -gt 0
    if ($ownsApplication) {
        # Python 이 타임아웃으로 이 스크립트를 죽일 때 이 PID 로 Office 를 정리한다.
        [Console]::Out.WriteLine("OFFICE_PID=$($launched[0])")
        [Console]::Out.Flush()
    }

    switch ($App) {
        'word' {
            $application.Visible = $false
            $application.DisplayAlerts = 0          # wdAlertsNone
            # Open(FileName, ConfirmConversions, ReadOnly)
            $document = $application.Documents.Open($inputFile, $false, $true)
            $document.ExportAsFixedFormat($outputFile, 17)   # wdExportFormatPDF
        }
        'powerpoint' {
            # PowerPoint 는 Visible=$false 설정이 예외를 내므로 WithWindow=$false 로 창만 숨긴다.
            $previousAlerts = $application.DisplayAlerts
            $application.DisplayAlerts = 1          # ppAlertsNone
            # Open(FileName, ReadOnly, Untitled, WithWindow)
            $document = $application.Presentations.Open($inputFile, $true, $false, $false)
            $document.SaveAs($outputFile, 32)                # ppSaveAsPDF
        }
        'excel' {
            $application.Visible = $false
            $application.DisplayAlerts = $false
            # Open(FileName, UpdateLinks, ReadOnly)
            $document = $application.Workbooks.Open($inputFile, 0, $true)
            $document.ExportAsFixedFormat(0, $outputFile)    # xlTypePDF
        }
    }

    if (-not (Test-Path -LiteralPath $outputFile)) {
        throw "PDF was not created: $outputFile"
    }
    $exitCode = 0
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    $exitCode = 1
}
finally {
    if ($null -ne $document) {
        try {
            switch ($App) {
                'word' { $document.Close(0) }        # wdDoNotSaveChanges
                'powerpoint' { $document.Close() }
                'excel' { $document.Close($false) }
            }
        } catch {}
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($document)
    }
    if ($null -ne $application) {
        if ($ownsApplication) {
            try { $application.Quit() } catch {}
        } elseif ($App -eq 'powerpoint' -and $null -ne $previousAlerts) {
            # 사용자의 PowerPoint 에 붙었던 경우: 종료하지 않고 바꾼 설정만 되돌린다.
            try { $application.DisplayAlerts = $previousAlerts } catch {}
        }
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($application)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

exit $exitCode
```

브리지 stdout 규약: 새 Office 프로세스를 만들었으면 첫 줄에 `OFFICE_PID=<pid>`를 출력한다. Python 쪽(`bridge_office_pid`, Task 2 보강)이 타임아웃 때 이 값을 읽는다.

- [ ] **Step 3b: 타임아웃 정리 수동 확인**

PowerShell에서 스크립트를 직접 실행해 PID 줄이 나오는지 확인한다:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File src\win_office.ps1 -InputPath <scratch>\sample.docx -OutputPath <scratch>\pid_check.pdf -App word
```

Expected: 첫 줄 `OFFICE_PID=<숫자>`, 종료 코드 0, `pid_check.pdf` 생성, 이후 `Get-Process WINWORD`가 비어 있음.

그리고 PowerPoint 싱글턴 보호를 확인한다: PowerPoint를 수동으로 먼저 열어둔 상태에서 `.pptx` 변환을 실행하면, 변환은 성공하고 사용자의 PowerPoint 창은 닫히지 않아야 하며 stdout에 `OFFICE_PID` 줄이 없어야 한다. 확인 후 PowerPoint를 닫는다. (자동 테스트 대상이 아니므로 결과를 보고서에 적는다.)

- [ ] **Step 4: 통과 확인**

Run: `python -m unittest tests.test_local_converter -v`
Expected: `Ran 16 tests` OK (Word가 있는 PC). 이어서 `powershell -Command "Get-Process WINWORD -ErrorAction SilentlyContinue"`가 아무것도 출력하지 않아야 한다.

- [ ] **Step 5: 수동 확인 — PowerPoint·Excel·CSV 경로**

PowerShell에서 (`<scratch>`는 세션 스크래치 폴더):

```powershell
$dir = "<scratch>"
$p = New-Object -ComObject PowerPoint.Application; $pres = $p.Presentations.Add(0); $null = $pres.Slides.Add(1, 12); $pres.SaveAs("$dir\t.pptx"); $pres.Close(); $p.Quit()
$x = New-Object -ComObject Excel.Application; $x.Visible = $false; $wb = $x.Workbooks.Add(); $wb.Worksheets.Item(1).Cells.Item(1,1).Value2 = "hello"; $wb.SaveAs("$dir\t.xlsx", 51); $wb.Close($false); $x.Quit()
"a,b`n1,2" | Set-Content "$dir\t.csv" -Encoding utf8
python src/local_converter.py "$dir\t.pptx" --to pdf --output-dir "$dir\out" --overwrite
python src/local_converter.py "$dir\t.xlsx" --to pdf --output-dir "$dir\out" --overwrite
python src/local_converter.py "$dir\t.csv"  --to pdf --output-dir "$dir\out" --overwrite
Get-ChildItem "$dir\out"
Get-Process WINWORD, POWERPNT, EXCEL -ErrorAction SilentlyContinue
```

Expected: `Conversion complete:` 3회, `out\t.pdf` 존재(마지막 변환으로 덮어씀), 남은 Office 프로세스 없음. 문제가 있으면 브리지를 고친 뒤 Step 4를 다시 실행한다.

- [ ] **Step 6: 커밋**

```bash
git add src/win_office.ps1 tests/test_local_converter.py
git commit -m "feat: add win_office.ps1 COM bridge for Word/PowerPoint/Excel PDF export

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: GUI 확장자 집합 정리 + 문서

**Files:**
- Modify: `src/converter_gui.py:18` (import), `:286` (`choose_input`)
- Modify: `README.md:20`, `README.md:34`, `README.md:44`
- Modify: `docs/guides/fileConverter_GUIDE.html:45`, `:78`, `:107`
- Test: `tests/test_converter_gui.py` (기존 테스트가 계속 통과하는지만 확인)

**Interfaces:**
- Consumes: `local_converter.OFFICE_EXTENSIONS`

- [ ] **Step 1: GUI 수정**

`src/converter_gui.py:18`의

```python
from local_converter import ConversionError, convert
```

를

```python
from local_converter import OFFICE_EXTENSIONS, ConversionError, convert
```

로 바꾸고, `choose_input`의

```python
            if suffix in {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".odt", ".odp", ".ods"}:
```

를

```python
            if suffix in OFFICE_EXTENSIONS:
```

로 바꾼다.

- [ ] **Step 2: GUI 테스트 실행**

Run: `python -m unittest tests.test_converter_gui -v`
Expected: 모두 OK (기존 테스트 수와 같음).

- [ ] **Step 3: README 수정**

- 20행: `- 문서: DOC/DOCX, PPT/PPTX, XLS/XLSX, ODT/ODP/ODS, RTF/CSV -> PDF (LibreOffice 필요)`
  → `- 문서: DOC/DOCX, PPT/PPTX, XLS/XLSX, ODT/ODP/ODS, RTF/CSV -> PDF (LibreOffice 또는 Microsoft Office 필요)`
- 34행: `2. [LibreOffice](https://www.libreoffice.org/download/download/): Office 문서 -> PDF용`
  → `2. [LibreOffice](https://www.libreoffice.org/download/download/) 또는 Microsoft Office(Word/PowerPoint/Excel): Office 문서 -> PDF용. 둘 다 있으면 LibreOffice를 먼저 사용합니다.`
- 44행 끝에 문장 추가: `LibreOffice가 없으면 설치된 Microsoft Office를 백그라운드로 잠시 실행해 PDF를 만듭니다.`

- [ ] **Step 4: 가이드 HTML 수정**

- 45행 카드: `FFmpeg, LibreOffice, Ghostscript 또는 Poppler를 설치합니다.` → `FFmpeg, LibreOffice(또는 Microsoft Office), Ghostscript 또는 Poppler를 설치합니다.`
- 78행 표 셀: `<td><a href="https://www.libreoffice.org/download/download/">LibreOffice</a></td>` → `<td><a href="https://www.libreoffice.org/download/download/">LibreOffice</a> 또는 Microsoft Office</td>`
- 107행 문제해결 `<p>` 내용: `LibreOffice를 설치하세요. 프로그램은 PATH와 기본 Windows 설치 경로를 자동으로 확인합니다. 이미 설치했다면 프로그램을 완전히 종료한 뒤 다시 시도하세요.` → `LibreOffice 또는 Microsoft Office(Word/PowerPoint/Excel)가 필요합니다. LibreOffice는 PATH와 기본 Windows 설치 경로를 자동으로 확인하고, 없으면 설치된 Microsoft Office를 사용합니다. 이미 설치했다면 프로그램을 완전히 종료한 뒤 다시 시도하세요.`

- [ ] **Step 5: 전체 테스트**

Run: `python -m unittest discover tests`
Expected: 모두 OK.

- [ ] **Step 6: 커밋**

```bash
git add src/converter_gui.py README.md docs/guides/fileConverter_GUIDE.html
git commit -m "docs: document Microsoft Office as an Office-to-PDF engine; reuse OFFICE_EXTENSIONS in GUI

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```
