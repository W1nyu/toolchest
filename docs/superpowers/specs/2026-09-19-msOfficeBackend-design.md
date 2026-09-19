# MS Office 백엔드 — Office 문서 → PDF 변환 설계

날짜: 2026-09-19

## 배경

`local_converter.py`는 DOC/DOCX, PPT/PPTX, XLS/XLSX, ODT/ODP/ODS, RTF/CSV → PDF 변환을
LibreOffice(`soffice --headless --convert-to pdf`)에만 의존한다. LibreOffice가 없고
Microsoft Office만 설치된 PC에서는 변환이 바로 실패한다.

이 작업은 LibreOffice가 없을 때 설치된 Microsoft Word/PowerPoint/Excel을 COM 자동화로
구동해 PDF를 만드는 대체 경로를 추가한다. HWP/HWPX는 범위에서 제외한다.

## 목표

- LibreOffice가 없어도 MS Office가 있으면 기존 Office 확장자 전부를 PDF로 변환한다.
- LibreOffice가 있으면 지금과 완전히 같은 동작을 유지한다.
- pip 의존성을 추가하지 않는다. 기존 `win_ocr.ps1`처럼 PowerShell 브리지를 쓴다.
- 원본 파일은 읽기 전용으로만 열고 절대 수정하지 않는다.
- 실패해도 Office 프로세스가 백그라운드에 남지 않는다.

## 비목표

- HWP/HWPX 지원.
- LibreOffice 경로 제거나 변경.
- MS Office 전용 옵션(페이지 범위, 시트 선택 등).

## 구성 요소

### 1. `src/local_converter.py`

**상수**

```python
MS_OFFICE_APPS = {
    "word":       {".doc", ".docx", ".odt", ".rtf"},
    "powerpoint": {".ppt", ".pptx", ".odp"},
    "excel":      {".xls", ".xlsx", ".ods", ".csv"},
}
MS_OFFICE_PROGIDS = {"word": "Word.Application", "powerpoint": "PowerPoint.Application", "excel": "Excel.Application"}
OFFICE_BRIDGE_SCRIPT = Path(__file__).with_name("win_office.ps1")
MS_OFFICE_TIMEOUT = 300  # seconds
```

`OFFICE_EXTENSIONS`는 `MS_OFFICE_APPS` 값의 합집합과 같아야 한다(테스트로 고정).

**새 함수**

- `ms_office_app_for(suffix: str) -> str | None`
  확장자(소문자, 점 포함)를 받아 `"word"|"powerpoint"|"excel"` 또는 `None`을 돌려준다.
- `find_ms_office(app: str) -> bool`
  `winreg`로 `HKEY_CLASSES_ROOT\<ProgID>` 키 존재 여부만 확인한다. Windows가 아니거나
  `winreg`를 불러올 수 없으면 `False`. 앱을 실행하지 않는다.
- `convert_with_ms_office(source: Path, destination: Path, app: str) -> None`
  `powershell -NoProfile -ExecutionPolicy Bypass -File win_office.ps1 -InputPath <source>
  -OutputPath <destination> -App <app>`를 `subprocess.run(capture_output=True,
  timeout=MS_OFFICE_TIMEOUT)`으로 실행한다.
  - `TimeoutExpired` → `ConversionError("Microsoft Office 변환이 300초 안에 끝나지 않았습니다 …")`
  - 종료 코드 ≠ 0 → `ConversionError(stderr.strip() or stdout.strip() or 기본 메시지)`
  - 종료 코드 0인데 `destination`이 없음 → `ConversionError("Microsoft Office가 PDF를 만들지 않았습니다.")`
  - stdout/stderr는 `utf-8`, `errors="replace"`로 디코드한다.

**`convert_office` 변경**

```
soffice = find_libreoffice()
if soffice:
    (기존 LibreOffice 경로 그대로)
else:
    app = ms_office_app_for(source.suffix.lower())
    if app and find_ms_office(app):
        temp_dir 안의 <stem>.pdf 로 convert_with_ms_office 호출
    else:
        raise ConversionError(
            "Office 문서를 PDF로 바꾸려면 LibreOffice 또는 Microsoft Office(Word/PowerPoint/Excel)가 필요합니다. "
            "LibreOffice: https://www.libreoffice.org/download/download/")
```

이후 임시 PDF를 최종 경로로 옮기는 부분(덮어쓰기 검사, `--compress` 시 Ghostscript 압축)은
두 경로가 공유한다. 즉 LibreOffice든 MS Office든 "임시 폴더에 PDF 생성"까지만 다르고
그 다음은 동일하다.

### 2. `src/win_office.ps1`

```
param(
    [Parameter(Mandatory)][string]$InputPath,
    [Parameter(Mandatory)][string]$OutputPath,
    [Parameter(Mandatory)][ValidateSet('word','powerpoint','excel')][string]$App
)
```

- `$ErrorActionPreference = 'Stop'`. 입력 경로는 `Resolve-Path`로 절대 경로화한다
  (COM은 상대 경로를 프로세스 작업 폴더 기준으로 해석하지 않는다).
- 앱별 처리:
  - **word**: `New-Object -ComObject Word.Application`; `Visible=$false`; `DisplayAlerts=0`;
    `Documents.Open($in, $false, $true)` (ConfirmConversions=false, ReadOnly=true);
    `ExportAsFixedFormat($out, 17)`; `Close(0)`.
  - **powerpoint**: `New-Object -ComObject PowerPoint.Application`; `DisplayAlerts=1`(ppAlertsNone);
    `Presentations.Open($in, $true, $false, $false)` (ReadOnly, Untitled=false, WithWindow=false);
    `SaveAs($out, 32)`; `Close()`. PowerPoint는 `Visible=$false` 설정이 예외를 내므로 건드리지 않는다.
  - **excel**: `New-Object -ComObject Excel.Application`; `Visible=$false`; `DisplayAlerts=$false`;
    `Workbooks.Open($in, 0, $true)` (UpdateLinks=0, ReadOnly=true);
    `ExportAsFixedFormat(0, $out)`; `Close($false)`.
- `try/finally`: 문서가 열렸으면 저장 없이 닫고, 앱 객체가 있으면 `Quit()`한 뒤
  `[System.Runtime.InteropServices.Marshal]::ReleaseComObject`로 해제한다.
- 예외는 `catch`에서 `$_.Exception.Message`를 stderr(`[Console]::Error.WriteLine`)로 쓰고 `exit 1`.
  정상이면 `exit 0`.
- 파일은 UTF-8 BOM으로 저장한다(`win_ocr.ps1`과 같음. 한글 주석이 깨지지 않게).

### 3. `src/converter_gui.py`

- `choose_input`의 하드코딩된 확장자 집합을 `OFFICE_EXTENSIONS`로 바꾼다.
  이 변경으로 `.rtf`, `.csv`도 선택 시 변환 형식이 `pdf`로 자동 설정된다.
- 그 외 로직 변경 없음. 에러는 이미 `ConversionError` 메시지를 그대로 보여주므로
  새 안내 문구가 자연스럽게 노출된다.

### 4. 테스트 `tests/test_local_converter.py`

기존 테스트 스타일(unittest, `unittest.mock.patch`)을 따른다.

- `OFFICE_EXTENSIONS == MS_OFFICE_APPS 값의 합집합`
- `ms_office_app_for`: 대표 확장자마다 앱 매핑, 미지원 확장자는 `None`
- `find_ms_office`: `winreg.OpenKey` 성공/`OSError` 를 patch해 True/False
- `convert_office`, LibreOffice 없음 + MS Office 있음:
  `subprocess.run`을 patch해 (a) 호출 인자에 `win_office.ps1`, `-App word`, 입력 경로,
  임시 폴더 안 `<stem>.pdf` 가 들어가는지, (b) side effect로 임시 PDF를 만들면 최종
  경로로 옮겨지는지 확인
- LibreOffice 없음 + MS Office 없음 → `ConversionError` 메시지에 "LibreOffice"와
  "Microsoft Office" 모두 포함
- PowerShell 종료 코드 1 + stderr → `ConversionError` 메시지에 stderr 포함
- `TimeoutExpired` → `ConversionError`
- 종료 코드 0이지만 PDF 없음 → `ConversionError`
- 통합 테스트(실제 Word 필요): `find_ms_office("word")`가 True일 때만 실행.
  Word COM으로 임시 `.docx`를 만든 뒤 `convert(...)`로 PDF를 만들고 `%PDF` 헤더를 확인.
  LibreOffice가 있으면 `find_libreoffice`를 `None`으로 patch해 MS Office 경로를 강제한다.
  Word가 없으면 `skipTest`.

### 5. 문서

- `README.md`
  - 지원 범위: "(LibreOffice 필요)" → "(LibreOffice 또는 Microsoft Office 필요)"
  - 설치 절: 2번 항목을 "LibreOffice 또는 Microsoft Office(Word/PowerPoint/Excel). 둘 다
    있으면 LibreOffice를 먼저 사용합니다"로 바꾼다.
- `docs/guides/fileConverter_GUIDE.html`
  - 엔진 표의 Office 문서 행에 Microsoft Office를 추가.
  - 문제해결 "Office PDF 변환이 시작되지 않습니다" 항목에 MS Office 대안을 추가.

## 오류 처리 요약

| 상황 | 결과 |
|---|---|
| LibreOffice 있음 | 기존 동작 |
| LibreOffice 없음, 해당 앱 있음 | PowerShell 브리지로 변환 |
| LibreOffice 없음, 해당 앱 없음 (예: Word만 있고 xlsx 변환) | "LibreOffice 또는 Microsoft Office 필요" 에러 |
| 브리지 실패 (손상 파일, 암호 문서 등) | stderr 메시지를 담은 ConversionError |
| 브리지 300초 초과 | 타임아웃 ConversionError, 프로세스는 subprocess가 종료 |
| 출력 경로에 파일 있음, `--overwrite` 없음 | 기존과 같은 "Output already exists" 에러 |

## 검증 방법

1. `python -m unittest discover tests` 전부 통과.
2. 이 PC(LibreOffice 없음, Office 있음)에서
   `python src/local_converter.py sample.docx --to pdf --output-dir output` 성공.
   `.pptx`, `.xlsx`, `.csv`도 각각 확인.
3. 변환 후 작업 관리자에 WINWORD/POWERPNT/EXCEL 프로세스가 남지 않음.
4. GUI에서 docx 선택 → 변환 형식이 pdf로 자동 설정 → 변환 성공.
