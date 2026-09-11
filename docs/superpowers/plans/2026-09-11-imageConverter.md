# imageConverter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 이미지(파일 또는 클립보드)에서 한국어·영어 텍스트를 추출해 앱에서 편집·복사하고, `.txt` / `.md` / **검색 가능한 PDF**로 저장하는 `tools` 프로젝트의 세 번째 기능을 만든다.

**Architecture:** 코어 모듈 `image_to_text.py`가 Pillow로 이미지를 2배 확대해 임시 PNG로 저장하고, PowerShell 브리지 `win_ocr.ps1`을 통해 Windows 내장 OCR(`Windows.Media.Ocr`)을 호출한다. 브리지는 줄별 텍스트와 좌표를 JSON 파일로 돌려주고, 코어는 허용 문자만 남긴 뒤 좌표로 행을 재구성해 탭 구분 텍스트를 만든다. `image_to_pdf.py`는 같은 좌표를 써서 원본 이미지 위에 보이지 않는 텍스트 레이어를 얹은 PDF를 만든다. GUI는 `converter_gui.py`에 세 번째 탭으로 붙는다.

**Tech Stack:** Python 3.14, Pillow, reportlab, tkinter/ttk, Windows PowerShell 5.1, `unittest`, (테스트 전용) pypdf

## Global Constraints

- **테스트 러너는 `unittest`다.** 이 저장소에 pytest는 설치되어 있지 않다. 모든 테스트 명령은 `python -m unittest ...` 형태다.
- **새 런타임 의존성을 추가하지 않는다.** `requirements.txt`는 그대로 둔다. Pillow와 reportlab은 이미 있다. `pypdf`는 이미 설치되어 있지만 **테스트에서만** 쓰고, 없으면 skip 한다.
- 코어 모듈은 tkinter를 import 하지 않는다. GUI가 코어를 호출하는 단방향이다.
- 모든 오류는 `OcrError`로 통일하고, 메시지는 **사용자에게 그대로 보여줄 수 있는 한국어**로 쓴다. 기존 `ConversionError`(`local_converter.py`) / `WebPdfError`(`web_to_pdf.py`)와 같은 방식이다.
- **문자는 제거만 하고 치환하지 않는다.** 허용 목록 밖의 문자는 지우되, 어떤 문자를 다른 문자로 바꾸는 교정(`「`→`r` 등)은 하지 않는다.
- 허용 문자: 숫자, 영문 `A-Za-z`, 한글 음절 `U+AC00`–`U+D7A3`, 한글 자모 `U+1100`–`U+11FF`·`U+3131`–`U+318E`, 공백, ASCII 문장부호(`U+0021`–`U+002F`, `U+003A`–`U+0040`, `U+005B`–`U+0060`, `U+007B`–`U+007E`), 그리고 `·` `•` `※`
- 인식기 언어는 `ko` 계열 하나만 쓴다. `AvailableRecognizerLanguages`에서 `ko`로 시작하는 첫 태그를 고른다.
- 상수 고정값: `DEFAULT_SCALE = 2.0`, `DEFAULT_TIMEOUT = 60`, `ROW_OVERLAP_RATIO = 0.5`, `MAX_IMAGE_DIMENSION = 10000`, `MAX_PDF_POINTS = 14400.0`
- 파일 인코딩은 전부 UTF-8. PowerShell이 쓴 JSON은 BOM이 붙으므로 Python은 `encoding="utf-8-sig"`로 읽는다.

**작업 시작 전 브랜치를 만든다** (현재 `main`에 커밋되지 않은 변경이 이미 있다):

```bash
git checkout -b feat/image-converter
```

---

### Task 1: `group_lines` — 좌표 기반 행 재구성

파이프라인에서 가장 틀리기 쉬운 순수 함수를 OCR 없이 먼저 만든다. 이 태스크는 Windows OCR을 전혀 호출하지 않는다.

**Files:**
- Create: `image_to_text.py`
- Test: `test_image_to_text.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `OcrError(Exception)`
  - `OcrLine` — `frozen dataclass`, 필드 `text: str, x: float, y: float, width: float, height: float`
  - `group_lines(lines: Sequence[OcrLine]) -> str`
  - 상수 `ROW_OVERLAP_RATIO: float = 0.5`

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`test_image_to_text.py`를 새로 만든다:

```python
import unittest

import image_to_text
from image_to_text import OcrLine


def line(text, x, y, height=10.0, width=50.0):
    return OcrLine(text=text, x=x, y=y, width=width, height=height)


class GroupLinesTests(unittest.TestCase):
    def test_empty_input_returns_empty_string(self):
        self.assertEqual(image_to_text.group_lines([]), "")

    def test_vertically_separated_lines_become_separate_rows(self):
        lines = [line("위", 0, 0), line("아래", 0, 20)]
        self.assertEqual(image_to_text.group_lines(lines), "위\n아래")

    def test_lines_at_same_height_are_joined_by_tab_in_x_order(self):
        lines = [line("내용", 100, 0), line("구분", 0, 0)]
        self.assertEqual(image_to_text.group_lines(lines), "구분\t내용")

    def test_band_does_not_chain_beyond_its_first_line(self):
        # A(y 0~10)와 B(y 5~15)는 5만큼 겹쳐 같은 행이다.
        # C(y 10~20)는 B와는 겹치지만 밴드의 첫 줄인 A와는 겹치지 않으므로 새 행이어야 한다.
        # 누적 범위(0~15)로 판정하면 C까지 빨려 들어가 이 테스트가 깨진다.
        lines = [line("A", 0, 0), line("B", 100, 5), line("C", 0, 10)]
        self.assertEqual(image_to_text.group_lines(lines), "A\tB\nC")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m unittest test_image_to_text -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'image_to_text'`

- [ ] **Step 3: 최소 구현을 작성한다**

`image_to_text.py`를 새로 만든다:

```python
"""이미지에서 한국어/영어 텍스트를 추출한다. Windows 내장 OCR을 사용한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

ROW_OVERLAP_RATIO = 0.5


class OcrError(Exception):
    """사용자에게 그대로 보여줄 수 있는 한국어 메시지를 담는다."""


@dataclass(frozen=True)
class OcrLine:
    text: str
    x: float
    y: float
    width: float
    height: float


def _same_row(first: OcrLine, other: OcrLine) -> bool:
    overlap = min(first.y + first.height, other.y + other.height) - max(first.y, other.y)
    if overlap <= 0:
        return False
    return overlap >= ROW_OVERLAP_RATIO * min(first.height, other.height)


def group_lines(lines: Sequence[OcrLine]) -> str:
    """줄을 읽는 순서대로 정렬하고, 같은 높이의 줄을 한 행으로 묶는다.

    밴드 판정은 누적 범위가 아니라 밴드의 첫 줄을 기준으로 한다. 줄이 하나씩
    붙으면서 밴드의 세로 범위가 늘어나 관계없는 줄까지 빨아들이는 것을 막는다.
    """
    if not lines:
        return ""
    ordered = sorted(lines, key=lambda item: (item.y, item.x))
    bands: list[list[OcrLine]] = []
    for item in ordered:
        if bands and _same_row(bands[-1][0], item):
            bands[-1].append(item)
        else:
            bands.append([item])
    rows = []
    for band in bands:
        band.sort(key=lambda item: item.x)
        rows.append("\t".join(item.text for item in band))
    return "\n".join(rows)
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m unittest test_image_to_text -v`
Expected: PASS — 4 tests OK

- [ ] **Step 5: 커밋한다**

```bash
git add image_to_text.py test_image_to_text.py
git commit -m "feat: add coordinate-based line grouping for image OCR"
```

---

### Task 2: `filter_characters` — 허용 문자만 남기기

**Files:**
- Modify: `image_to_text.py`
- Test: `test_image_to_text.py` (추가)

**Interfaces:**
- Consumes: 없음
- Produces: `filter_characters(text: str) -> str` — 허용 목록 밖 문자를 **제거**하고, 연속 공백을 하나로 줄이고, 양끝 공백을 없앤다. 치환은 하지 않는다.

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`test_image_to_text.py`의 `if __name__ == "__main__":` 위에 추가한다:

```python
class FilterCharactersTests(unittest.TestCase):
    def test_korean_english_digits_and_punctuation_survive(self):
        for text in [
            "학/석사 기졸업자 또는 2027년 2월 졸업예정자",
            "국내(대한민국) 취업 및 해외 출장",
            "8월 31일(월) 오전 10시 ~ 9월 14일(월)",
            "career.hyundai.co.kr",
            "1/2금융권 대출 금액의 연 1% 이자지원",
            "영어 Speaking 성적(TOEIC Speaking 또는 OPIc) 필수 제출",
        ]:
            with self.subTest(text=text):
                self.assertEqual(image_to_text.filter_characters(text), text)

    def test_document_symbols_survive(self):
        self.assertEqual(image_to_text.filter_characters("※ 상기 모집 직무"), "※ 상기 모집 직무")
        self.assertEqual(image_to_text.filter_characters("• 전공 무관"), "• 전공 무관")

    def test_noise_characters_are_removed_not_replaced(self):
        # 제거만 한다. 「 를 r 로 되돌리지 않는다.
        self.assertEqual(image_to_text.filter_characters("Ca「d"), "Cad")
        self.assertEqual(image_to_text.filter_characters("回 口 而"), "")

    def test_hangul_jamo_survives(self):
        self.assertEqual(image_to_text.filter_characters("ㄱㄴㄷ"), "ㄱㄴㄷ")

    def test_runs_of_whitespace_collapse_and_edges_are_trimmed(self):
        self.assertEqual(image_to_text.filter_characters("  모집  구분  "), "모집 구분")

    def test_text_of_only_noise_becomes_empty(self):
        self.assertEqual(image_to_text.filter_characters("「」回"), "")
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m unittest test_image_to_text -v`
Expected: FAIL — `AttributeError: module 'image_to_text' has no attribute 'filter_characters'`

- [ ] **Step 3: 최소 구현을 작성한다**

`image_to_text.py`의 import 블록에 추가한다:

```python
import re
```

상수 블록 아래에 추가한다:

```python
# 허용 문자: 숫자, 영문, 한글 음절/자모, 공백, ASCII 문장부호, 문서 기호(· • ※)
_ALLOWED_CHARACTERS = (
    "0-9A-Za-z"
    "가-힣"                    # 한글 음절
    "ᄀ-ᇿㄱ-ㆎ"       # 한글 자모, 호환 자모
    "!-/:-@"       # ASCII 문장부호 앞쪽
    "[-`{-~"       # ASCII 문장부호 뒤쪽
    "·•※"               # · • ※
    " \t"
)
_DISALLOWED = re.compile(f"[^{_ALLOWED_CHARACTERS}]")
_WHITESPACE_RUN = re.compile(r"\s+")
```

`group_lines` 정의 앞에 추가한다:

```python
def filter_characters(text: str) -> str:
    """허용 목록에 없는 문자를 제거한다.

    제거만 하고 치환은 하지 않는다. 인식이 틀린 글자를 다른 글자로 바꿔 추측하면
    맞았던 글자까지 틀리게 만들 수 있어서, 노이즈를 지우는 데까지만 한다.
    """
    return _WHITESPACE_RUN.sub(" ", _DISALLOWED.sub("", text)).strip()
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m unittest test_image_to_text -v`
Expected: PASS — 10 tests OK

- [ ] **Step 5: 커밋한다**

```bash
git add image_to_text.py test_image_to_text.py
git commit -m "feat: keep only digits, Hangul, Latin letters and punctuation"
```

---

### Task 3: PowerShell 브리지 — Windows OCR 호출

**Files:**
- Create: `win_ocr.ps1`

**Interfaces:**
- Consumes: 없음
- Produces: 두 가지 호출 모드를 가진 스크립트. Task 4의 `_run_bridge`가 이 계약에 의존한다.
  - `-ListLanguages -OutPath <json>` → `{"languages":["ko"],"maxDimension":10000}`
  - `-ImagePath <png> -Language ko -OutPath <json>` → `{"lines":[{"text":"...","x":0,"y":0,"w":0,"h":0}],"maxDimension":10000}`
  - 실패 시 종료 코드 1 + stderr에 원인

이 태스크는 PowerShell 스크립트라 `unittest`가 아니라 직접 실행으로 검증한다.

- [ ] **Step 1: 브리지 스크립트를 작성한다**

`win_ocr.ps1`을 새로 만든다:

```powershell
param(
    [string]$ImagePath,
    [string]$Language = 'ko',
    [Parameter(Mandatory = $true)][string]$OutPath,
    [switch]$ListLanguages
)

$ErrorActionPreference = 'Stop'

try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime

    # 네 타입 모두 명시적으로 로드해야 한다. Windows.Globalization.Language 를
    # 빠뜨리면 TryCreateFromLanguage 호출에서 TypeNotFound 로 죽는다.
    $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]

    $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and
        $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]

    function Await($operation, $resultType) {
        $task = $asTask.MakeGenericMethod($resultType).Invoke($null, @($operation))
        $task.Wait(-1) | Out-Null
        $task.Result
    }

    $maxDimension = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension

    if ($ListLanguages) {
        $tags = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages |
            ForEach-Object { $_.LanguageTag })
        $payload = [pscustomobject]@{ languages = $tags; maxDimension = $maxDimension }
        $payload | ConvertTo-Json -Depth 5 -Compress | Out-File -FilePath $OutPath -Encoding utf8
        exit 0
    }

    if (-not $ImagePath) { throw '-ImagePath 인자가 필요합니다.' }

    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage(
        [Windows.Globalization.Language]::new($Language))
    if ($null -eq $engine) { throw "'$Language' 인식기를 만들 수 없습니다." }

    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) `
        ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) `
        ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) `
        ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

    $lines = @()
    foreach ($ocrLine in $result.Lines) {
        $words = @($ocrLine.Words)
        if ($words.Count -eq 0) { continue }
        $minX = [double]::MaxValue
        $minY = [double]::MaxValue
        $maxX = [double]::MinValue
        $maxY = [double]::MinValue
        foreach ($word in $words) {
            $rect = $word.BoundingRect
            if ($rect.X -lt $minX) { $minX = $rect.X }
            if ($rect.Y -lt $minY) { $minY = $rect.Y }
            if (($rect.X + $rect.Width) -gt $maxX) { $maxX = $rect.X + $rect.Width }
            if (($rect.Y + $rect.Height) -gt $maxY) { $maxY = $rect.Y + $rect.Height }
        }
        $lines += [pscustomobject]@{
            text = $ocrLine.Text
            x    = $minX
            y    = $minY
            w    = $maxX - $minX
            h    = $maxY - $minY
        }
    }

    $payload = [pscustomobject]@{ lines = @($lines); maxDimension = $maxDimension }
    $payload | ConvertTo-Json -Depth 5 -Compress | Out-File -FilePath $OutPath -Encoding utf8
    exit 0
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
```

- [ ] **Step 2: 언어 조회 모드를 직접 실행해 확인한다**

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File win_ocr.ps1 -ListLanguages -OutPath "$TEMP/langs.json"
cat "$TEMP/langs.json"
```

Expected: 종료 코드 0, 파일 내용에 `"languages":["ko"]`와 `"maxDimension":10000`이 들어 있다.
`ko`가 없으면 이 PC에 한국어 인식기가 없는 것이므로 진행 전에 사용자에게 알린다.

- [ ] **Step 3: 인식 모드를 `ex.png`로 실행해 확인한다**

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File win_ocr.ps1 -ImagePath "$(pwd)/ex.png" -Language ko -OutPath "$TEMP/ocr.json"
python -c "import json,io; d=json.load(io.open(r'$TEMP/ocr.json',encoding='utf-8-sig')); print(len(d['lines']),'lines'); print(d['lines'][1])"
```

Expected: 종료 코드 0. 줄 수가 100개 이상이고, 각 줄에 `text`, `x`, `y`, `w`, `h` 키가 모두 있다.
한글이 `?`나 깨진 글자가 아니라 제대로 보여야 한다 — 깨져 보이면 `Out-File -Encoding utf8`이나
Python 쪽 `utf-8-sig` 중 하나가 잘못된 것이다.

- [ ] **Step 4: 잘못된 인자로 실패 경로를 확인한다**

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File win_ocr.ps1 -ImagePath "없는파일.png" -Language ko -OutPath "$TEMP/fail.json"; echo "exit=$?"
```

Expected: `exit=1`, stderr에 오류 메시지가 찍힌다.

- [ ] **Step 5: 커밋한다**

```bash
git add win_ocr.ps1
git commit -m "feat: add PowerShell bridge for Windows built-in OCR"
```

---

### Task 4: 브리지 호출과 언어 선택

**Files:**
- Modify: `image_to_text.py`
- Test: `test_image_to_text.py` (추가)

**Interfaces:**
- Consumes: Task 1의 `OcrError`. Task 3의 `win_ocr.ps1` 계약
- Produces:
  - `BRIDGE_SCRIPT: Path` — `win_ocr.ps1`의 절대 경로
  - `_run_bridge(args: list[str], timeout: int) -> dict`
  - `engine_info(timeout: int = 15) -> tuple[tuple[str, ...], int]` — `(언어 태그들, 최대 이미지 크기)`
  - `pick_language(languages: Sequence[str]) -> str` — `ko`로 시작하는 첫 태그, 없으면 `OcrError`
  - 상수 `DEFAULT_TIMEOUT = 60`, `MAX_IMAGE_DIMENSION = 10000`

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`test_image_to_text.py`의 `if __name__ == "__main__":` 위에 추가한다:

```python
class PickLanguageTests(unittest.TestCase):
    def test_plain_ko_tag_is_selected(self):
        self.assertEqual(image_to_text.pick_language(["en-US", "ko"]), "ko")

    def test_regional_korean_tag_is_selected(self):
        self.assertEqual(image_to_text.pick_language(["en-US", "ko-KR"]), "ko-KR")

    def test_missing_korean_recognizer_raises_with_setup_guidance(self):
        with self.assertRaises(image_to_text.OcrError) as caught:
            image_to_text.pick_language(["en-US"])
        self.assertIn("광학 문자 인식", str(caught.exception))

    def test_bridge_script_exists_next_to_module(self):
        self.assertTrue(image_to_text.BRIDGE_SCRIPT.is_file())
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m unittest test_image_to_text -v`
Expected: FAIL — `AttributeError: module 'image_to_text' has no attribute 'pick_language'`

- [ ] **Step 3: 최소 구현을 작성한다**

`image_to_text.py`의 import 블록을 다음으로 교체한다:

```python
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
```

상수 블록의 `ROW_OVERLAP_RATIO = 0.5` 줄을 다음으로 교체한다:

```python
ROW_OVERLAP_RATIO = 0.5
DEFAULT_TIMEOUT = 60
MAX_IMAGE_DIMENSION = 10000
BRIDGE_SCRIPT = Path(__file__).with_name("win_ocr.ps1")
```

파일 끝에 추가한다:

```python
def _run_bridge(args: list[str], timeout: int) -> dict:
    """win_ocr.ps1 을 실행하고 JSON 결과를 돌려준다.

    결과를 stdout 이 아니라 임시 파일로 주고받는다. PowerShell 5.1 의 stdout 은
    콘솔 코드페이지를 타서 한글이 깨지므로 파일 경유가 유일하게 안전하다.
    """
    if not BRIDGE_SCRIPT.is_file():
        raise OcrError(f"OCR 브리지 스크립트를 찾을 수 없습니다: {BRIDGE_SCRIPT}")
    with tempfile.TemporaryDirectory(prefix="imgocr_") as workspace:
        out_path = Path(workspace) / "result.json"
        command = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(BRIDGE_SCRIPT), "-OutPath", str(out_path), *args,
        ]
        try:
            completed = subprocess.run(command, capture_output=True, timeout=timeout)
        except FileNotFoundError as exc:
            raise OcrError("PowerShell을 찾지 못했습니다. Windows에서 실행해야 합니다.") from exc
        except subprocess.TimeoutExpired as exc:
            raise OcrError(f"문자 인식이 {timeout}초 안에 끝나지 않았습니다.") from exc
        if completed.returncode != 0 or not out_path.is_file():
            detail = (completed.stderr or b"").decode("utf-8", "replace").strip()
            raise OcrError(f"문자 인식에 실패했습니다. {detail[:300]}".strip())
        try:
            return json.loads(out_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OcrError(f"인식 결과를 읽지 못했습니다. {exc}") from exc


def engine_info(timeout: int = 15) -> tuple[tuple[str, ...], int]:
    """사용 가능한 인식기 언어 태그와 최대 이미지 크기를 돌려준다."""
    payload = _run_bridge(["-ListLanguages"], timeout)
    languages = tuple(str(tag) for tag in (payload.get("languages") or ()))
    limit = int(payload.get("maxDimension") or MAX_IMAGE_DIMENSION)
    return languages, limit


def pick_language(languages: Sequence[str]) -> str:
    """한국어 인식기 태그를 고른다. ko-KR 처럼 지역이 붙은 태그도 받아들인다."""
    for tag in languages:
        if tag.lower().startswith("ko"):
            return tag
    raise OcrError(
        "Windows에 한국어 문자 인식기가 없습니다. "
        "설정 → 시간 및 언어 → 언어 및 지역 → 한국어의 언어 옵션에서 "
        "'광학 문자 인식'을 설치한 뒤 다시 시도하세요."
    )
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m unittest test_image_to_text -v`
Expected: PASS — 14 tests OK

- [ ] **Step 5: 실제 브리지 호출을 확인한다**

```bash
python -c "import image_to_text; print(image_to_text.engine_info())"
```

Expected: `(('ko',), 10000)` 형태의 출력

- [ ] **Step 6: 커밋한다**

```bash
git add image_to_text.py test_image_to_text.py
git commit -m "feat: call Windows OCR bridge and select Korean recognizer"
```

---

### Task 5: 이미지 입력·전처리·`image_to_text()`·CLI

**Files:**
- Modify: `image_to_text.py`
- Test: `test_image_to_text.py` (추가)

**Interfaces:**
- Consumes: Task 1의 `OcrLine`·`group_lines`, Task 2의 `filter_characters`, Task 4의 `_run_bridge`·`engine_info`·`pick_language`
- Produces:
  - `OcrResult` — `frozen dataclass`, 필드 `text: str, lines: tuple[OcrLine, ...], language: str, scale: float`
  - `load_image(path) -> Image.Image`
  - `image_from_clipboard() -> Image.Image`
  - `prepare_image(image, scale, limit) -> tuple[Image.Image, float]`
  - `image_to_text(source, *, scale=DEFAULT_SCALE, timeout=DEFAULT_TIMEOUT) -> OcrResult`
  - `main(argv=None) -> int`
  - 상수 `DEFAULT_SCALE = 2.0`

`OcrResult.lines`의 각 `text`는 **이미 `filter_characters`를 통과한 값**이다. Task 6의 PDF 생성이 이 값을 그대로 쓴다.

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`test_image_to_text.py`의 맨 위 import 아래에 추가한다:

```python
import tempfile
from pathlib import Path

from PIL import Image
```

그리고 `if __name__ == "__main__":` 위에 추가한다:

```python
HAS_KOREAN_RECOGNIZER = False
try:
    HAS_KOREAN_RECOGNIZER = any(
        tag.lower().startswith("ko") for tag in image_to_text.engine_info()[0]
    )
except image_to_text.OcrError:
    HAS_KOREAN_RECOGNIZER = False


class PrepareImageTests(unittest.TestCase):
    def test_image_is_upscaled_by_the_requested_factor(self):
        prepared, scale = image_to_text.prepare_image(
            Image.new("RGB", (100, 200)), 2.0, 10000)
        self.assertEqual(prepared.size, (200, 400))
        self.assertEqual(scale, 2.0)

    def test_scale_is_reduced_so_the_result_fits_the_limit(self):
        prepared, scale = image_to_text.prepare_image(
            Image.new("RGB", (100, 400)), 2.0, 600)
        self.assertLessEqual(max(prepared.size), 600)
        self.assertEqual(scale, 1.5)

    def test_palette_image_is_converted_to_rgb(self):
        prepared, _ = image_to_text.prepare_image(
            Image.new("P", (50, 50)), 1.0, 10000)
        self.assertEqual(prepared.mode, "RGB")

    def test_oversized_original_is_rejected_with_both_numbers(self):
        with self.assertRaises(image_to_text.OcrError) as caught:
            image_to_text.prepare_image(Image.new("RGB", (12000, 10)), 2.0, 10000)
        message = str(caught.exception)
        self.assertIn("10000", message)
        self.assertIn("12000", message)


class LoadImageTests(unittest.TestCase):
    def test_missing_file_raises_ocr_error(self):
        with self.assertRaises(image_to_text.OcrError):
            image_to_text.load_image(Path("존재하지_않는_이미지.png"))

    def test_non_image_file_raises_ocr_error(self):
        with tempfile.TemporaryDirectory() as workspace:
            broken = Path(workspace) / "broken.png"
            broken.write_text("이건 이미지가 아닙니다", encoding="utf-8")
            with self.assertRaises(image_to_text.OcrError):
                image_to_text.load_image(broken)


@unittest.skipUnless(HAS_KOREAN_RECOGNIZER, "한국어 인식기가 설치되어 있지 않습니다")
class SamplePosterTests(unittest.TestCase):
    def test_recruitment_poster_yields_its_key_phrases(self):
        result = image_to_text.image_to_text(Path("ex.png"))
        self.assertIn("2026 신입 인재 모집", result.text)
        self.assertIn("여의도 본사 근무", result.text)
        self.assertIn("모집분야", result.text)

    def test_table_label_and_content_land_on_the_same_row(self):
        result = image_to_text.image_to_text(Path("ex.png"))
        rows = [row for row in result.text.splitlines() if row.startswith("근무지\t")]
        self.assertTrue(rows, "'근무지' 항목이 내용과 같은 행으로 묶이지 않았습니다")

    def test_every_stored_line_is_already_filtered(self):
        result = image_to_text.image_to_text(Path("ex.png"))
        for stored in result.lines:
            with self.subTest(text=stored.text):
                self.assertEqual(
                    stored.text, image_to_text.filter_characters(stored.text))
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m unittest test_image_to_text -v`
Expected: FAIL — `AttributeError: module 'image_to_text' has no attribute 'prepare_image'`

- [ ] **Step 3: 최소 구현을 작성한다**

`image_to_text.py`의 import 블록에 추가한다:

```python
import argparse
import shutil
import sys

from PIL import Image, ImageGrab
```

상수 블록에 추가한다:

```python
DEFAULT_SCALE = 2.0
```

파일 끝에 추가한다:

```python
@dataclass(frozen=True)
class OcrResult:
    text: str
    lines: tuple[OcrLine, ...]
    language: str
    scale: float


def load_image(path: Path | str) -> Image.Image:
    path = Path(path)
    if not path.is_file():
        raise OcrError(f"이미지를 찾을 수 없습니다: {path}")
    try:
        with Image.open(path) as opened:
            return opened.convert("RGB")
    except (OSError, ValueError) as exc:
        raise OcrError(f"이미지를 열지 못했습니다: {path.name} ({exc})") from exc


def image_from_clipboard() -> Image.Image:
    try:
        data = ImageGrab.grabclipboard()
    except OSError as exc:
        raise OcrError(f"클립보드를 읽지 못했습니다. {exc}") from exc
    if isinstance(data, Image.Image):
        return data.convert("RGB")
    if isinstance(data, list) and data:
        return load_image(Path(data[0]))
    raise OcrError("클립보드에 이미지가 없습니다. 이미지를 복사한 뒤 다시 붙여넣으세요.")


def prepare_image(image: Image.Image, scale: float, limit: int) -> tuple[Image.Image, float]:
    """RGB 로 바꾸고 확대한다. 확대 결과가 인식기 제한을 넘지 않도록 배율을 줄인다."""
    longest = max(image.size)
    if longest > limit:
        raise OcrError(
            f"이미지가 너무 큽니다. 긴 변이 {limit}px 이하여야 합니다. "
            f"현재 {image.width}×{image.height}"
        )
    effective = max(1.0, min(scale, limit / longest))
    prepared = image.convert("RGB")
    if effective > 1.0:
        prepared = prepared.resize(
            (round(prepared.width * effective), round(prepared.height * effective)),
            Image.LANCZOS,
        )
    return prepared, effective


def image_to_text(
    source: Path | str | Image.Image,
    *,
    scale: float = DEFAULT_SCALE,
    timeout: int = DEFAULT_TIMEOUT,
) -> OcrResult:
    image = source if isinstance(source, Image.Image) else load_image(source)
    languages, limit = engine_info(min(timeout, 15))
    language = pick_language(languages)
    prepared, effective = prepare_image(image, scale, limit)

    workspace = Path(tempfile.mkdtemp(prefix="imgocr_"))
    try:
        page = workspace / "page.png"
        prepared.save(page, format="PNG")
        payload = _run_bridge(
            ["-ImagePath", str(page), "-Language", language], timeout)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    lines = []
    for item in payload.get("lines") or ():
        cleaned = filter_characters(str(item.get("text", "")))
        if not cleaned:
            continue
        lines.append(
            OcrLine(
                text=cleaned,
                x=float(item.get("x", 0.0)),
                y=float(item.get("y", 0.0)),
                width=float(item.get("w", 0.0)),
                height=float(item.get("h", 0.0)),
            )
        )
    if not lines:
        raise OcrError("텍스트를 찾지 못했습니다. 글자가 너무 작거나 흐릴 수 있습니다.")
    return OcrResult(
        text=group_lines(lines),
        lines=tuple(lines),
        language=language,
        scale=effective,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="이미지에서 한국어/영어 텍스트를 추출합니다.")
    parser.add_argument(
        "image", nargs="?", help="이미지 파일 경로 (생략하면 클립보드 이미지를 사용합니다)")
    parser.add_argument(
        "--scale", type=float, default=DEFAULT_SCALE,
        help=f"인식 전 확대 배율 (기본: {DEFAULT_SCALE})")
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT,
        help=f"인식 시간 제한(초) (기본: {DEFAULT_TIMEOUT})")
    parser.add_argument("--output", type=Path, help="결과를 저장할 텍스트 파일")
    parser.add_argument("--pdf", type=Path, help="검색 가능한 PDF로 저장할 경로")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        image = load_image(args.image) if args.image else image_from_clipboard()
        result = image_to_text(image, scale=args.scale, timeout=args.timeout)
        if args.pdf:
            from image_to_pdf import build_searchable_pdf

            saved = build_searchable_pdf(image, result, args.pdf, overwrite=True)
            print(f"PDF 저장 완료: {saved}")
    except OcrError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result.text, encoding="utf-8")
        print(f"저장 완료: {args.output}")
    elif not args.pdf:
        sys.stdout.reconfigure(encoding="utf-8")
        print(result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`--pdf`가 `image_to_pdf`를 함수 안에서 import 하는 것은 의도적이다. Task 6이 아직 없어도
텍스트 추출은 동작해야 하고, `image_to_pdf`가 `image_to_text`를 import 하므로 모듈 최상단에서
서로를 부르면 순환 import 가 된다.

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m unittest test_image_to_text -v`
Expected: PASS — 23 tests OK (한국어 인식기가 없는 환경이면 `SamplePosterTests` 3건 skip)

- [ ] **Step 5: CLI를 실제로 실행해 확인한다**

```bash
python image_to_text.py ex.png --output "$TEMP/ex.txt"
python -c "import io; print(io.open(r'$TEMP/ex.txt',encoding='utf-8').read()[:400])"
```

Expected: `저장 완료: ...` 출력. 저장된 텍스트에 `2026 신입 인재 모집`이 있고,
`근무지`와 `여의도 본사 근무`가 탭으로 이어진 한 줄로 나온다.

- [ ] **Step 6: 커밋한다**

```bash
git add image_to_text.py test_image_to_text.py
git commit -m "feat: extract filtered text from image files and clipboard with CLI"
```

---

### Task 6: 검색 가능한 PDF

원본 이미지를 페이지에 깔고 그 위에 **보이지 않는 텍스트 레이어**를 얹는다. 보이는 것은 이미지 그대로인데 드래그·복사·`Ctrl+F`가 된다.

**Files:**
- Create: `image_to_pdf.py`
- Modify: `web_to_pdf.py:397` (`_font_name` → `korean_font_name`), `web_to_pdf.py:494` (호출부)
- Test: `test_image_to_pdf.py`

**Interfaces:**
- Consumes: Task 5의 `OcrResult`·`OcrLine`·`OcrError`, `web_to_pdf.korean_font_name()`
- Produces:
  - `MAX_PDF_POINTS: float = 14400.0`
  - `page_scale(width: float, height: float) -> float`
  - `build_searchable_pdf(image, result, destination, *, overwrite=False) -> Path`

- [ ] **Step 1: `web_to_pdf`의 폰트 헬퍼를 공개 이름으로 바꾼다**

`web_to_pdf.py`에서 `def _font_name() -> str:`를 `def korean_font_name() -> str:`로 바꾸고,
같은 파일의 유일한 호출부 `font = _font_name()`을 `font = korean_font_name()`으로 바꾼다.
동작은 그대로다. 새 소비자(`image_to_pdf`)가 생겨 비공개 이름을 건너 쓰지 않도록 공개하는 것이다.

바뀐 게 없는지 확인한다:

```bash
grep -n "_font_name\|korean_font_name" web_to_pdf.py
python -m unittest test_web_to_pdf -v
```

Expected: `korean_font_name`만 두 번 보이고 `_font_name`은 없다. 기존 테스트 전부 통과.

- [ ] **Step 2: 실패하는 테스트를 작성한다**

`test_image_to_pdf.py`를 새로 만든다:

```python
import re
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import image_to_pdf
from image_to_text import OcrLine, OcrResult

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


def sample_result(scale=1.0):
    return OcrResult(
        text="모집구분 Card",
        lines=(OcrLine(text="모집구분 Card", x=10.0, y=20.0, width=180.0, height=24.0),),
        language="ko",
        scale=scale,
    )


class PageScaleTests(unittest.TestCase):
    def test_small_page_is_not_scaled(self):
        self.assertEqual(image_to_pdf.page_scale(920.0, 3323.0), 1.0)

    def test_page_longer_than_the_pdf_limit_is_scaled_down(self):
        factor = image_to_pdf.page_scale(1000.0, 28800.0)
        self.assertAlmostEqual(factor, 0.5)


class BuildSearchablePdfTests(unittest.TestCase):
    def test_existing_file_is_kept_unless_overwrite_is_set(self):
        with tempfile.TemporaryDirectory() as workspace:
            target = Path(workspace) / "out.pdf"
            target.write_bytes(b"기존 파일")
            with self.assertRaises(image_to_pdf.OcrError):
                image_to_pdf.build_searchable_pdf(
                    Image.new("RGB", (200, 100), "white"), sample_result(), target)
            self.assertEqual(target.read_bytes(), b"기존 파일")

    @unittest.skipUnless(PdfReader is not None, "pypdf가 설치되어 있지 않습니다")
    def test_page_matches_the_original_image_size(self):
        with tempfile.TemporaryDirectory() as workspace:
            target = Path(workspace) / "out.pdf"
            image_to_pdf.build_searchable_pdf(
                Image.new("RGB", (200, 100), "white"), sample_result(), target)
            box = PdfReader(str(target)).pages[0].mediabox
            self.assertEqual((float(box.width), float(box.height)), (200.0, 100.0))

    @unittest.skipUnless(PdfReader is not None, "pypdf가 설치되어 있지 않습니다")
    def test_recognized_text_is_selectable_in_the_pdf(self):
        with tempfile.TemporaryDirectory() as workspace:
            target = Path(workspace) / "out.pdf"
            image_to_pdf.build_searchable_pdf(
                Image.new("RGB", (200, 100), "white"), sample_result(), target)
            extracted = PdfReader(str(target)).pages[0].extract_text()
            self.assertIn("모집구분", extracted)
            self.assertIn("Card", extracted)

    @unittest.skipUnless(PdfReader is not None, "pypdf가 설치되어 있지 않습니다")
    def test_upscaled_coordinates_are_mapped_back_to_the_original(self):
        # scale=2.0 이면 OCR 좌표는 원본의 두 배다. y=20,h=24 는 원본에서 y=10,h=12 이므로
        # 200x100 페이지에서 텍스트 기준선은 100 - 10 - 12 = 78 근처여야 한다.
        with tempfile.TemporaryDirectory() as workspace:
            target = Path(workspace) / "out.pdf"
            image_to_pdf.build_searchable_pdf(
                Image.new("RGB", (200, 100), "white"), sample_result(scale=2.0), target)
            stream = PdfReader(str(target)).pages[0].get_contents().get_data()
            matches = re.findall(rb"1 0 0 1 ([\d.]+) ([\d.]+) Tm", stream)
            self.assertTrue(matches, "텍스트 위치 지정 연산자를 찾지 못했습니다")
            self.assertAlmostEqual(float(matches[0][0]), 5.0, places=1)
            self.assertAlmostEqual(float(matches[0][1]), 78.0, places=1)


if __name__ == "__main__":
    unittest.main()
```

마지막 테스트는 pypdf 로 콘텐츠 스트림을 직접 읽는다. 설치된 pypdf 버전에서
`page.get_contents().get_data()`가 동작하지 않으면 `page["/Contents"].get_data()`로 바꿔 쓴다.
좌표 검증이 핵심이므로 접근 방법만 바꾸고 단언은 그대로 둔다.

- [ ] **Step 3: 테스트가 실패하는지 확인한다**

Run: `python -m unittest test_image_to_pdf -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'image_to_pdf'`

- [ ] **Step 4: 최소 구현을 작성한다**

`image_to_pdf.py`를 새로 만든다:

```python
"""OCR 결과를 원본 이미지 위 보이지 않는 텍스트 레이어로 얹어 검색 가능한 PDF를 만든다."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from image_to_text import OcrError, OcrResult
from web_to_pdf import korean_font_name

MAX_PDF_POINTS = 14400.0
INVISIBLE_TEXT = 3  # PDF 텍스트 렌더 모드: 그리지 않는다. 선택은 된다.


def page_scale(width: float, height: float) -> float:
    """PDF 한 변의 한계(14400pt)를 넘지 않도록 줄일 비율을 돌려준다."""
    longest = max(width, height)
    if longest <= MAX_PDF_POINTS:
        return 1.0
    return MAX_PDF_POINTS / longest


def build_searchable_pdf(
    image: Image.Image,
    result: OcrResult,
    destination: Path | str,
    *,
    overwrite: bool = False,
) -> Path:
    """원본 이미지 한 장을 한 페이지로 만들고, 인식 위치에 보이지 않는 텍스트를 얹는다."""
    destination = Path(destination)
    if destination.exists() and not overwrite:
        raise OcrError(f"같은 이름의 PDF가 이미 있습니다: {destination}")
    if not result.lines:
        raise OcrError("PDF로 만들 인식 결과가 없습니다.")
    destination.parent.mkdir(parents=True, exist_ok=True)

    factor = page_scale(float(image.width), float(image.height))
    page_width = image.width * factor
    page_height = image.height * factor
    font = korean_font_name()

    # OCR 좌표는 확대된 이미지 기준이므로 원본으로 되돌린 뒤 페이지 배율을 곱한다.
    to_page = factor / (result.scale or 1.0)

    pdf = canvas.Canvas(str(destination), pagesize=(page_width, page_height))
    pdf.drawImage(
        ImageReader(image.convert("RGB")), 0, 0,
        width=page_width, height=page_height,
    )

    text_object = pdf.beginText()
    text_object.setTextRenderMode(INVISIBLE_TEXT)
    for stored in result.lines:
        box_width = stored.width * to_page
        box_height = stored.height * to_page
        if box_width <= 0 or box_height <= 0 or not stored.text:
            continue
        size = max(1.0, box_height * 0.8)
        natural = pdfmetrics.stringWidth(stored.text, font, size)
        if natural <= 0:
            continue
        text_object.setFont(font, size)
        # 가로 비율을 맞춰야 드래그 범위가 이미지의 글자 위치와 어긋나지 않는다.
        text_object.setHorizScale(100.0 * box_width / natural)
        text_object.setTextOrigin(
            stored.x * to_page,
            page_height - stored.y * to_page - box_height,
        )
        text_object.textLine(stored.text)
    pdf.drawText(text_object)
    pdf.showPage()
    pdf.save()
    return destination
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `python -m unittest test_image_to_pdf -v`
Expected: PASS — 6 tests OK

- [ ] **Step 6: `ex.png`로 실제 PDF를 만들고 눈으로 확인한다**

```bash
python image_to_text.py ex.png --pdf "$TEMP/ex.pdf"
python -c "from pypdf import PdfReader; t=PdfReader(r'$TEMP/ex.pdf').pages[0].extract_text(); print(len(t),'chars'); print('2026' in t, '여의도' in t)"
```

Expected: `PDF 저장 완료: ...`, 추출 글자 수가 1000자 이상, 두 검사 모두 `True`.

그다음 PDF를 뷰어에서 직접 연다. 확인 항목:
1. 원본 포스터 이미지가 그대로 보인다 (글자가 이중으로 겹쳐 보이지 않는다)
2. 본문 글자 위를 드래그하면 선택 영역이 글자 위치와 대체로 맞는다
3. 선택한 내용을 복사해 붙여넣으면 한글이 깨지지 않는다
4. `Ctrl+F`로 `여의도`를 찾으면 해당 위치가 잡힌다

- [ ] **Step 7: 커밋한다**

```bash
git add image_to_pdf.py test_image_to_pdf.py web_to_pdf.py
git commit -m "feat: export image OCR result as searchable PDF"
```

---

### Task 7: GUI 세 번째 탭

**Files:**
- Modify: `converter_gui.py`

**Interfaces:**
- Consumes: Task 5의 `image_to_text`·`image_from_clipboard`·`load_image`·`OcrError`, Task 6의 `build_searchable_pdf`
- Produces: 없음 (최종 사용자 인터페이스)

- [ ] **Step 1: import와 창 크기, 상태 변수를 고친다**

`converter_gui.py`의 import 블록을 다음으로 교체한다:

```python
"""Simple Windows-friendly desktop UI for the local converter."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from PIL import Image, ImageTk

from image_to_pdf import build_searchable_pdf
from image_to_text import OcrError, image_from_clipboard, image_to_text, load_image
from local_converter import ConversionError, convert
from web_to_pdf import WebPdfError, webpage_to_pdf
```

`__init__`에서 창 크기 두 줄을 교체한다 (세 번째 탭은 결과 편집창 때문에 더 큰 창이 필요하다):

```python
        self.geometry("820x640")
        self.minsize(720, 560)
```

`__init__`의 `self.web_status = ...` 줄 **다음에** 추가한다:

```python
        self.image_info = tk.StringVar(value="이미지를 불러오거나 Ctrl+V로 붙여넣으세요.")
        self.image_status = tk.StringVar(value="한국어·영어 텍스트를 인식합니다.")
        self.current_image: Image.Image | None = None
        self.last_result = None
        self.preview_photo: ImageTk.PhotoImage | None = None
```

- [ ] **Step 2: 탭을 등록한다**

`_build_ui`를 다음으로 교체한다:

```python
    def _build_ui(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        file_tab = ttk.Frame(self.notebook)
        web_tab = ttk.Frame(self.notebook)
        image_tab = ttk.Frame(self.notebook)
        self.notebook.add(file_tab, text="파일 변환")
        self.notebook.add(web_tab, text="웹 본문 PDF")
        self.notebook.add(image_tab, text="이미지 텍스트")
        self._build_file_ui(file_tab)
        self._build_web_ui(web_tab)
        self._build_image_ui(image_tab)
        self.bind_all("<Control-v>", self._on_paste_shortcut)
        self.bind_all("<Control-V>", self._on_paste_shortcut)
```

- [ ] **Step 3: 탭 화면을 만든다**

`_build_web_ui` 메서드 **다음에** 추가한다:

```python
    def _build_image_ui(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(2, weight=1)
        frame.rowconfigure(3, weight=1)

        ttk.Button(frame, text="이미지 불러오기", command=self.choose_image).grid(
            row=0, column=0, sticky="w")
        ttk.Button(frame, text="클립보드에서 붙여넣기", command=self.paste_image).grid(
            row=0, column=1, sticky="w", padx=8)
        ttk.Label(frame, textvariable=self.image_info, wraplength=420).grid(
            row=0, column=2, sticky="w", padx=8)

        self.preview_label = ttk.Label(frame)
        self.preview_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=10)

        self.image_button = ttk.Button(
            frame, text="텍스트 추출", command=self.start_image_conversion)
        self.image_button.grid(row=2, column=2, sticky="e")

        self.image_text = scrolledtext.ScrolledText(frame, wrap="word", height=12)
        self.image_text.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=10)

        actions = ttk.Frame(frame)
        actions.grid(row=4, column=0, columnspan=3, sticky="w")
        ttk.Button(actions, text="전체 복사", command=self.copy_image_text).pack(side="left")
        ttk.Button(actions, text=".txt 저장",
                   command=lambda: self.save_image_text("txt")).pack(side="left", padx=8)
        ttk.Button(actions, text=".md 저장",
                   command=lambda: self.save_image_text("md")).pack(side="left")
        ttk.Button(actions, text="PDF 저장",
                   command=self.save_image_pdf).pack(side="left", padx=8)

        ttk.Label(frame, textvariable=self.image_status, wraplength=740).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=12)
```

- [ ] **Step 4: 동작 메서드를 추가한다**

`converter_gui.py`의 `ConverterApp` 클래스 맨 끝(마지막 메서드 다음)에 추가한다:

```python
    def _on_paste_shortcut(self, event: tk.Event) -> str | None:
        """Ctrl+V. 결과 편집창 안에서는 평범한 텍스트 붙여넣기로 남겨둔다."""
        if self.notebook.index("current") != 2:
            return None
        if self.focus_get() is self.image_text:
            return None
        self.paste_image()
        return "break"

    def _show_image(self, image: Image.Image, label: str) -> None:
        self.current_image = image
        self.last_result = None
        preview = image.copy()
        preview.thumbnail((220, 220))
        self.preview_photo = ImageTk.PhotoImage(preview)
        self.preview_label.configure(image=self.preview_photo)
        self.image_info.set(f"{label} · {image.width}×{image.height}")

    def choose_image(self) -> None:
        path = filedialog.askopenfilename(
            title="텍스트를 추출할 이미지 선택",
            filetypes=[("이미지", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff"),
                       ("모든 파일", "*.*")],
        )
        if not path:
            return
        try:
            image = load_image(Path(path))
        except OcrError as exc:
            messagebox.showerror("이미지 열기 실패", str(exc))
            return
        self._show_image(image, Path(path).name)
        self.image_status.set("텍스트 추출을 누르세요.")

    def paste_image(self) -> None:
        try:
            image = image_from_clipboard()
        except OcrError as exc:
            messagebox.showwarning("붙여넣기 실패", str(exc))
            return
        self._show_image(image, "클립보드 이미지")
        self.image_status.set("텍스트 추출을 누르세요.")

    def start_image_conversion(self) -> None:
        if self.current_image is None:
            messagebox.showwarning("이미지 필요", "이미지를 불러오거나 Ctrl+V로 붙여넣으세요.")
            return
        self.image_button.configure(state="disabled")
        self.image_status.set("문자를 인식하는 중입니다...")
        threading.Thread(target=self._extract_image_text, daemon=True).start()

    def _extract_image_text(self) -> None:
        try:
            result = image_to_text(self.current_image)
        except OcrError as exc:
            self.after(0, self._finish_image_error, str(exc))
        else:
            self.after(0, self._finish_image_success, result)

    def _finish_image_success(self, result) -> None:
        self.image_button.configure(state="normal")
        self.last_result = result
        self.image_text.delete("1.0", "end")
        self.image_text.insert("1.0", result.text)
        self.image_status.set(
            f"{len(result.lines)}줄 인식 완료. 오타를 고친 뒤 복사하거나 저장하세요.")

    def _finish_image_error(self, error: str) -> None:
        self.image_button.configure(state="normal")
        self.image_status.set(f"인식 실패: {error}")
        messagebox.showerror("인식 실패", error)

    def _current_image_text(self) -> str:
        return self.image_text.get("1.0", "end-1c")

    def copy_image_text(self) -> None:
        text = self._current_image_text()
        if not text.strip():
            messagebox.showwarning("복사할 내용 없음", "먼저 텍스트를 추출하세요.")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self.image_status.set("클립보드에 복사했습니다.")

    def save_image_text(self, extension: str) -> None:
        text = self._current_image_text()
        if not text.strip():
            messagebox.showwarning("저장할 내용 없음", "먼저 텍스트를 추출하세요.")
            return
        path = filedialog.asksaveasfilename(
            title="텍스트 저장",
            defaultextension=f".{extension}",
            filetypes=[(f"{extension.upper()} 파일", f"*.{extension}")],
        )
        if not path:
            return
        try:
            Path(path).write_text(text, encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("저장 실패", str(exc))
            return
        self.image_status.set(f"저장 완료: {path}")

    def save_image_pdf(self) -> None:
        if self.current_image is None or self.last_result is None:
            messagebox.showwarning("추출 필요", "먼저 이미지를 불러와 텍스트를 추출하세요.")
            return
        path = filedialog.asksaveasfilename(
            title="검색 가능한 PDF 저장",
            defaultextension=".pdf",
            filetypes=[("PDF 파일", "*.pdf")],
        )
        if not path:
            return
        try:
            build_searchable_pdf(
                self.current_image, self.last_result, Path(path), overwrite=True)
        except (OcrError, OSError) as exc:
            messagebox.showerror("PDF 저장 실패", str(exc))
            return
        self.image_status.set(
            f"PDF 저장 완료: {path} · PDF에는 인식 원본이 들어갑니다. "
            "편집창에서 고친 내용은 반영되지 않습니다."
        )
```

**PDF는 인식 원본(`result.lines`)을 쓴다.** 텍스트 레이어가 이미지의 글자 위치에 정확히 얹혀야
하는데, 편집창에서 고친 글자는 대응하는 좌표를 알 수 없기 때문이다. 위 상태 메시지가 이 사실을
사용자에게 알린다. 이 동작은 가이드에도 적는다(Task 8).

- [ ] **Step 5: 앱을 열어 손으로 확인한다**

Run: `python converter_gui.py`

확인 항목 — 하나라도 어긋나면 고치고 다시 연다:
1. 탭이 `파일 변환` / `웹 본문 PDF` / `이미지 텍스트` 세 개다
2. `이미지 텍스트` 탭에서 `이미지 불러오기`로 `ex.png`를 열면 썸네일과 `ex.png · 920×3323`이 뜬다
3. `텍스트 추출`을 누르면 버튼이 잠시 비활성화되고, 결과가 편집창에 채워진다
4. 결과에 `근무지`와 `여의도 본사 근무`가 탭으로 이어진 행이 있다
5. 결과에 `학/석사`, `(대한민국)` 같은 문장부호가 살아 있고, `「`·`回` 같은 문자는 없다
6. 편집창에서 글자를 직접 고칠 수 있다
7. 편집창 **바깥**을 클릭한 뒤 Ctrl+V를 누르면 클립보드 이미지가 붙는다
8. 편집창 **안**에 커서를 두고 Ctrl+V를 누르면 이미지가 아니라 평범한 텍스트가 붙는다
9. `전체 복사` 후 메모장에 붙여넣으면 같은 내용이 나온다
10. `.txt 저장` / `.md 저장`이 동작하고, 빈 상태에서 누르면 경고가 뜬다
11. `PDF 저장`으로 만든 PDF에서 이미지가 보이고 글자를 드래그·복사할 수 있다
12. 추출 전에 `PDF 저장`을 누르면 경고가 뜬다
13. 앞의 두 탭이 예전과 같이 동작한다

- [ ] **Step 6: 기존 테스트가 깨지지 않았는지 확인한다**

Run: `python -m unittest discover -p "test_*.py" -v`
Expected: `test_local_converter` / `test_web_to_pdf` / `test_image_to_text` / `test_image_to_pdf` 전부 통과 (환경에 따라 skip 포함)

- [ ] **Step 7: 커밋한다**

```bash
git add converter_gui.py
git commit -m "feat: add image-to-text tab with clipboard paste and PDF export"
```

---

### Task 8: 가이드와 README

**Files:**
- Create: `imageConverter_GUIDE.html`
- Modify: `articleConverter_GUIDE.html` (상단 nav, 푸터에 링크 추가)
- Modify: `fileConverter_GUIDE.html` (상단 nav, 푸터에 링크 추가)
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 5의 CLI 인자, Task 7의 탭 이름과 버튼 이름
- Produces: 없음

- [ ] **Step 1: 가이드를 만든다**

`fileConverter_GUIDE.html`을 복사해 `imageConverter_GUIDE.html`을 만들고, `<style>` 블록은
그대로 둔 채 본문만 바꾼다. 기존 두 가이드와 **같은 구조**를 지킨다:
`global-nav` → `sub-nav` → `hero` → `THREE STEPS` → `DESKTOP APP` → `COMMAND LINE` →
`PRIVACY & LIMITS` → `TROUBLESHOOTING` → `footer`.

내용은 **실제 동작과 일치해야 한다.** 반드시 지킬 사실:

- 실행: `로컬_변환기_실행.bat` 더블클릭 → `이미지 텍스트` 탭 (별도 실행 파일이 아니다)
- 입력: `이미지 불러오기` 버튼 또는 `Ctrl+V` 붙여넣기
- 버튼 이름: `텍스트 추출`, `전체 복사`, `.txt 저장`, `.md 저장`, `PDF 저장`
- 표는 탭 구분으로 나오므로 엑셀·노션에 붙여넣기 좋다
- PDF는 **원본 이미지를 그대로 보여주면서 그 위 텍스트를 드래그·복사·`Ctrl+F`** 할 수 있는
  형태다. 다만 **편집창에서 고친 내용은 PDF에 반영되지 않는다** — 텍스트 레이어가 인식된
  좌표에 얹히기 때문이다. 이 제약을 숨기지 말고 쓴다
- 인식 문자: 숫자, 한글, 영문, 공백, 문장부호. 그 밖의 인식 노이즈는 제거된다.
  **틀리게 읽은 글자를 다른 글자로 고쳐주지는 않는다**고 명시한다 — 없는 기능을 있다고 쓰지 않는다
- 명령줄:
  - `python image_to_text.py ex.png`
  - `python image_to_text.py ex.png --output result.txt`
  - `python image_to_text.py ex.png --pdf result.pdf`
  - `python image_to_text.py --scale 3` (클립보드 이미지, 확대 배율 올리기)
- 인식 언어는 한국어·영어. Windows 내장 OCR을 쓰므로 추가 설치가 필요 없다
- 한국어 인식기가 없으면: `설정 → 시간 및 언어 → 언어 및 지역 → 한국어 언어 옵션 → 광학 문자 인식`
- 업로드 없음 · 전부 로컬 처리
- 링크는 같은 폴더 기준: `./README.md`, `./fileConverter_GUIDE.html`, `./articleConverter_GUIDE.html`

- [ ] **Step 2: 기존 두 가이드에 상호 링크를 추가한다**

`articleConverter_GUIDE.html`의 `global-nav`와 푸터에 `imageConverter` 링크를 넣는다:

```html
<nav class="global-nav"><a href="./README.md">Toolchest</a><a href="./fileConverter_GUIDE.html">File Converter</a><a href="./imageConverter_GUIDE.html">Image Converter</a><strong>Local tools. No upload.</strong></nav>
```

`fileConverter_GUIDE.html`에도 같은 방식으로 넣는다 (그쪽 nav는 `Article Converter` 링크를 갖고 있다).
두 파일의 푸터에도 `<a href="./imageConverter_GUIDE.html">Image Converter 가이드</a>`를 추가한다.

- [ ] **Step 3: README를 갱신한다**

`README.md`에 세 번째 기능을 기존 두 기능과 같은 형식으로 추가한다. 담을 내용:
`image_to_text.py`, `image_to_pdf.py`, `win_ocr.ps1`, `이미지 텍스트` 탭, CLI 예시,
검색 가능한 PDF 출력, Windows 내장 OCR 사용(추가 설치 없음), 한국어 인식기 요구사항.

- [ ] **Step 4: 링크가 전부 살아 있는지 확인한다**

```bash
grep -o 'href="\./[^"]*"' *_GUIDE.html | sort -u
ls README.md fileConverter_GUIDE.html articleConverter_GUIDE.html imageConverter_GUIDE.html
```

Expected: `href="./..."`로 참조된 파일 이름이 전부 실제로 존재한다. 404가 없어야 한다.

- [ ] **Step 5: 가이드에 적은 명령을 실제로 실행해 본다**

```bash
python image_to_text.py ex.png --output "$TEMP/guide-check.txt"
python image_to_text.py ex.png --pdf "$TEMP/guide-check.pdf"
```

Expected: 둘 다 성공. 가이드에 적힌 명령 중 하나라도 실패하면 **가이드를 고친다** —
앞서 `articleConverter_GUIDE.html`이 없는 파일 이름을 안내하던 것과 같은 문제를 반복하지 않는다.

- [ ] **Step 6: 커밋한다**

```bash
git add imageConverter_GUIDE.html articleConverter_GUIDE.html fileConverter_GUIDE.html README.md
git commit -m "docs: add imageConverter guide and cross-links"
```

---

## 완료 확인

모든 태스크가 끝난 뒤 스펙 §9의 완료 기준을 하나씩 확인한다.

- [ ] `python image_to_text.py ex.png`가 표의 항목과 내용이 같은 줄에 묶인 텍스트를 출력한다
- [ ] 결과에 숫자·한글·영문·문장부호만 남아 있고 인식 노이즈 문자가 없다
- [ ] 앱의 `이미지 텍스트` 탭에서 Ctrl+V와 파일 불러오기가 모두 동작한다
- [ ] 결과를 편집하고 복사·저장(.txt/.md/PDF)할 수 있다
- [ ] 저장한 PDF에서 이미지가 보이면서 그 위 텍스트를 드래그·복사할 수 있다
- [ ] `python -m unittest discover -p "test_*.py" -v`가 전부 통과한다
- [ ] `imageConverter_GUIDE.html`이 실제 파일명·실제 동작과 일치한다
