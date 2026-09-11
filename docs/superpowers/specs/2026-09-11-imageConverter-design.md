# imageConverter — 이미지에서 한국어/영어 텍스트 추출

작성일: 2026-09-11
상태: 승인됨 (구현 대기)

## 목적

채용공고·공모전 안내처럼 **이미지로만 배포된 문서**에서 텍스트를 뽑아 복사 가능한 형태로 만든다.
`tools` 프로젝트의 세 번째 기능이며, 기존 `fileConverter`(파일 변환)·`articleConverter`(웹 본문 PDF)와
같은 앱·같은 철학(로컬 처리, 업로드 없음)을 따른다.

기준 샘플: `ex.png` (현대카드/현대커머셜 2026 신입 인재 모집, 920×3323, 한글·영문 혼재, 표 4개)

## 확정된 결정과 근거

| 결정 | 선택 | 근거 |
|---|---|---|
| OCR 엔진 | Windows 내장 OCR (`Windows.Media.Ocr`) | 이 PC에 한국어(`ko`) 인식기가 이미 있음. 추가 설치 0, 오프라인, 빠름 |
| 호출 방식 | PowerShell 브리지 (`subprocess`) | `winsdk` 패키지가 Python 3.14용 휠을 제공하지 않음 (실측 확인). pip 의존성이 늘지 않는 이점도 있음 |
| 전처리 | 2배 LANCZOS 확대 | 실측: `현대하드→현대카드`, `기졸업사→기졸업자`, `시\|용공고→채용공고`, 누락되던 `문의` 행 인식 |
| 표 처리 | 좌표 기반 행 밴드 묶기 | OCR이 표를 열 단위로 뱉어 항목과 내용의 짝이 끊김. 좌표로 재정렬해야 쓸 수 있음 |
| 결과 형태 | 앱 내 편집창 + 복사 버튼, 저장은 선택 | OCR은 반드시 오타가 남으므로 고치는 단계가 있는 쪽이 실제로 빠름 |
| 저장 형식 | `.txt` / `.md` / **검색 가능한 PDF** | PDF는 원본 이미지를 그대로 보여주면서 텍스트를 드래그·복사할 수 있어야 한다는 요구 |
| 문자 범위 | 숫자·한글·영문·공백·문장부호만 남김 | 인식 노이즈(`「`, `回`, `口`)를 걷어내되 `학/석사`, `(대한민국)`, `8월 31일(월)`은 보존 |
| 언어 | 한국어 + 영어만 | 사용자 요구 |

### 정정 사항 (설계 중 확인)

초기 관찰에서 `r`이 `「`로 나오는 현상을 "영어 인식기 미설치 탓"으로 판단했으나 이는 **오판**이다.
한국어 인식기는 라틴 문자도 인식한다(`Commercial`, `Speaking`, `TOEIC`, `PLCC` 정상 인식).
`「`는 해당 인식기 문자셋 내부의 **글자 모양 혼동**이므로 영어 언어팩을 설치해도 개선되지 않는다.
따라서 **영어 언어팩 설치는 요구사항이 아니다.**

이 혼동을 후처리 규칙(`「`→`r` 등)으로 교정하는 안을 검토했으나 **채택하지 않았다**(§4.5).

## 1. 파일 구성

```
image_to_text.py            코어 모듈. GUI 비의존, 단독 CLI 실행 가능
image_to_pdf.py             검색 가능한 PDF 생성. image_to_text 의 결과를 받아 쓴다
win_ocr.ps1                 Windows OCR 호출 브리지. JSON 파일로 결과 반환
converter_gui.py            (수정) "이미지 텍스트" 탭 추가
test_image_to_text.py       테스트
imageConverter_GUIDE.html   가이드 (기존 두 가이드와 동일 톤/구조)
README.md                   (수정) 세 번째 기능 추가
```

기존 `web_to_pdf.py` / `local_converter.py`와 같은 층위다: 코어 로직은 GUI를 모르고,
GUI는 코어 모듈을 호출하기만 한다.

## 2. 코어 모듈 공개 인터페이스

```python
class OcrError(Exception):
    """사용자에게 그대로 보여줄 수 있는 한국어 메시지를 담는다."""

@dataclass(frozen=True)
class OcrLine:
    text: str
    x: float      # 확대된 이미지 기준 좌표
    y: float
    width: float
    height: float

@dataclass(frozen=True)
class OcrResult:
    text: str                      # 레이아웃 복원을 마친 최종 텍스트
    lines: tuple[OcrLine, ...]     # 원본 줄 (디버깅/테스트용)
    language: str                  # 실제 사용한 인식기 태그 (예: "ko")
    scale: float                   # 실제 적용된 확대 배율

DEFAULT_SCALE = 2.0
DEFAULT_TIMEOUT = 60          # 초
ROW_OVERLAP_RATIO = 0.5       # 같은 행으로 볼 세로 겹침 비율
MAX_IMAGE_DIMENSION = 10000   # 브리지가 maxDimension을 못 줄 때의 대체값

def available_languages(timeout: int = 15) -> tuple[str, ...]
def image_from_clipboard() -> Image.Image
def load_image(path: Path) -> Image.Image
def image_to_text(source: Path | Image.Image, *, scale=DEFAULT_SCALE,
                  timeout=DEFAULT_TIMEOUT) -> OcrResult
def group_lines(lines: Sequence[OcrLine]) -> str        # 순수 함수
def filter_characters(text: str) -> str                 # 순수 함수
def main(argv: list[str] | None = None) -> int
```

`group_lines`와 `filter_characters`가 **순수 함수로 분리된 것이 이 설계의 핵심**이다.
파이프라인에서 가장 틀리기 쉬운 두 로직을 OCR 없이 가짜 좌표·문자열만으로 빠르게 테스트할 수 있다.

## 3. PowerShell 브리지 계약

`win_ocr.ps1`은 두 가지 모드로 동작한다.

**언어 목록 조회**
```
powershell -NoProfile -ExecutionPolicy Bypass -File win_ocr.ps1 -ListLanguages -OutPath <json>
```
→ `{"languages": ["ko"]}`

**인식**
```
powershell -NoProfile -ExecutionPolicy Bypass -File win_ocr.ps1 `
    -ImagePath <png> -Language ko -OutPath <json>
```
→ `{"maxDimension": 10000, "lines": [{"text": "...", "x": 0, "y": 0, "w": 0, "h": 0}]}`

규칙:
- 결과는 **stdout이 아니라 `-OutPath` 파일에 `Out-File -Encoding utf8`로 쓴다.**
  PowerShell 5.1의 stdout은 콘솔 코드페이지를 타서 한글이 깨지므로, 파일 경유가 유일하게 안전하다.
- 실패 시 0이 아닌 종료 코드 + stderr에 원인. Python은 이를 `OcrError`로 감싼다.
- 필요한 WinRT 타입(`OcrEngine`, `BitmapDecoder`, `StorageFile`, `Language`)을 모두 명시적으로
  로드한다. `Windows.Globalization.Language` 누락은 실제로 겪은 실패 지점이다.

## 4. 처리 파이프라인

### 4.1 입력
- 파일: `load_image(path)` — Pillow가 여는 모든 형식. 열지 못하면 `OcrError`.
- 클립보드: `ImageGrab.grabclipboard()` — 반환값이 `Image`면 그대로,
  파일 경로 리스트면 첫 번째 파일을 연다. `None`이면 "이미지를 복사한 뒤 다시 붙여넣으세요".

### 4.2 전처리
- `RGB`로 변환 (RGBA/팔레트 이미지의 알파 때문에 인식이 무너지는 것을 막는다)
- `scale`배 LANCZOS 확대
- 확대 결과의 긴 변이 인식기 제한을 넘으면 넘지 않는 선까지 `scale`을 낮춘다 (최소 1.0).
  제한값은 브리지가 돌려준 `maxDimension`을 쓰고, 없으면 `MAX_IMAGE_DIMENSION` 상수로 대체한다
- 원본(확대 전)이 이미 제한을 넘으면 `OcrError`로 제한값과 현재 크기를 함께 알린다
- 임시 디렉터리에 PNG로 저장하고, `finally`에서 반드시 삭제

### 4.3 인식
- 인식기 언어는 `ko` 고정. 한국어 인식기가 한글·라틴 문자를 모두 처리한다.
- `ko`가 없으면 `OcrError`: 설정 경로(`설정 → 시간 및 언어 → 언어 및 지역 → 언어 옵션 → 광학 문자 인식`) 안내

### 4.4 레이아웃 복원 — `group_lines`

```
줄을 y(위쪽 좌표) 오름차순으로 정렬
현재 밴드를 첫 줄로 시작
다음 줄마다:
    밴드의 "첫 줄"과 세로로 겹치는 길이 >= ROW_OVERLAP_RATIO * min(두 줄의 높이) 이면
        같은 밴드에 추가
    아니면
        밴드를 닫고 새 밴드 시작
각 밴드: x 오름차순 정렬 후 "\t"로 연결
밴드들을 "\n"으로 연결
```

밴드 판정을 **누적 범위가 아니라 밴드의 첫 줄** 기준으로 하는 이유는, 줄이 하나씩 붙으면서
밴드의 세로 범위가 계속 늘어나 관계없는 줄까지 연쇄적으로 빨아들이는 것을 막기 위해서다.

일반 문단은 줄끼리 세로로 겹치지 않으므로 각자 한 밴드가 되어 평범한 여러 줄 텍스트로 나온다.
표에서는 `지원자격`과 같은 높이의 내용 줄이 한 밴드로 묶여 `지원자격\t• 학/석사 기졸업자...`가 된다.

### 4.5 후처리 — 허용 문자 필터

**제거만 하고 치환은 하지 않는다.** 허용 목록에 없는 문자는 지우되, 어떤 문자를 다른 문자로
바꾸지는 않는다. (`「`를 `r`로 되돌리는 식의 교정은 §8에서 명시적으로 제외한다.)

허용 문자:

| 분류 | 범위 |
|---|---|
| 숫자 | `0-9` |
| 영문 | `A-Z`, `a-z` |
| 한글 음절 | `U+AC00`–`U+D7A3` |
| 한글 자모 | `U+1100`–`U+11FF`, 호환 자모 `U+3131`–`U+318E` |
| 공백 | `\s` |
| ASCII 문장부호 | `U+0021`–`U+002F`, `U+003A`–`U+0040`, `U+005B`–`U+0060`, `U+007B`–`U+007E` |
| 문서 기호 | `·` `•` `※` |

그 밖의 문자(`「」`, `回`, `口`, `而` 등 인식 노이즈)는 제거한다.
`학/석사`, `국내(대한민국)`, `8월 31일(월) 오전 10시`, `career.hyundai.co.kr`, `1/2금융권`은
모두 그대로 남는다.

**적용 시점이 중요하다.** 필터는 `group_lines`로 행을 묶기 **전에, 줄 단위 텍스트에** 적용한다.
묶은 뒤에 적용하면 공백 정리 과정에서 행 구분자인 탭이 함께 뭉개진다.
필터 후 빈 문자열이 된 줄은 버린다.

각 줄 안에서 연속 공백은 하나로 줄이고 양끝 공백은 없앤다.

### 4.6 검색 가능한 PDF 출력

원본 이미지를 페이지에 그대로 깔고, OCR이 읽은 위치에 **보이지 않는 텍스트 레이어**를 얹는다.
스캔 문서의 "검색 가능한 PDF"와 같은 구조다. 화면에 보이는 것은 원본 이미지 그대로이고,
그 위에서 드래그·복사·`Ctrl+F`가 동작한다.

- 한 이미지는 한 페이지다. 페이지 크기는 **원본**(확대 전) 이미지의 픽셀 수를 그대로 포인트로 쓴다.
  긴 변이 PDF 한계인 14400pt를 넘으면 넘지 않도록 전체를 비례 축소한다.
- OCR 좌표는 확대된 이미지 기준이므로 `OcrResult.scale`로 나눠 원본 좌표로 되돌린다.
  PDF는 원점이 왼쪽 아래이므로 y는 `page_height - y - height`로 뒤집는다.
- 텍스트는 `setTextRenderMode(3)`으로 그리지 않는다. 글자가 화면에 나오지 않지만 선택은 된다.
- 글자 폭을 실제 인식 영역 폭에 맞추기 위해 `setHorizScale`로 가로 비율을 조정한다.
  이렇게 해야 드래그 범위가 이미지의 글자 위치와 어긋나지 않는다.
- 한글 폰트는 `web_to_pdf.py`가 이미 쓰는 맑은 고딕 등록 로직을 **재사용한다**.
  이를 위해 `web_to_pdf._font_name()`을 공개 이름 `korean_font_name()`으로 바꾼다.
  보이지 않는 텍스트라도 한글을 인코딩할 수 있는 폰트가 있어야 복사된 글자가 깨지지 않는다.
- PDF에 넣는 텍스트도 §4.5 필터를 통과한 것이다. 화면 표시와 복사 결과가 같아야 한다.

## 5. GUI 탭

`converter_gui.py`의 노트북에 `"이미지 텍스트"` 탭을 세 번째로 추가한다.
`_build_image_ui(parent)` 메서드로 만들며, 기존 두 탭의 구성 방식(`ttk` 그리드, 스레드 + `after`)을 그대로 따른다.

구성:
- `[이미지 불러오기]` 버튼 (파일 대화상자)
- `[클립보드에서 붙여넣기]` 버튼 + 탭 수준 `<Control-v>` / `<Control-V>` 바인딩
- 미리보기 썸네일 (긴 변 220px) + `파일명 · 너비×높이` 라벨
- `[텍스트 추출]` 버튼 — 백그라운드 스레드에서 실행, 진행 중 비활성화
- 편집 가능한 `ScrolledText` (결과 표시 및 수정)
- `[전체 복사]` `[.txt 저장]` `[.md 저장]` `[PDF 저장]`
- 상태 라벨

**Ctrl+V 처리 규칙:** 포커스가 결과 `ScrolledText`에 있으면 기본 텍스트 붙여넣기를 그대로 두고,
그 외에는 클립보드 이미지 붙여넣기로 처리한다. 결과를 편집하다가 이미지가 튀어나오면 안 된다.

**미리보기를 넣는 이유:** 붙여넣기했을 때 엉뚱한 이미지가 들어왔는지 즉시 보이게 하기 위함이다.

## 6. 오류 처리

| 상황 | 동작 |
|---|---|
| 한국어 인식기 없음 | 설정 경로를 포함한 안내 메시지 |
| 클립보드에 이미지 없음 | "이미지를 복사한 뒤 다시 붙여넣으세요" |
| 이미지 파일을 열 수 없음 | Pillow 오류를 감싼 한국어 메시지 |
| 원본이 인식기 제한(기본 10000px) 초과 | 제한과 현재 크기를 함께 알림 |
| PowerShell 실패 / 타임아웃(60초) | stderr 원인을 그대로 노출 |
| 인식된 글자 0개 | "텍스트를 찾지 못했습니다" — 빈 파일을 저장하지 않는다 |
| 결과가 비었는데 저장 시도 | 저장 버튼이 막고 경고 |
| 이미지 없이 PDF 저장 시도 | PDF는 원본 이미지가 있어야 하므로 경고 후 중단 |

모든 오류는 `OcrError`로 통일하고, GUI는 메시지를 그대로 표시한다.
기존 `ConversionError` / `WebPdfError`와 같은 방식이다.

## 7. 테스트 (`test_image_to_text.py`)

**순수 함수 — OCR 불필요, 빠름**
- `group_lines`: 세로로 떨어진 줄은 각자 한 줄로 나온다
- `group_lines`: 같은 높이의 두 줄은 x 순서대로 탭으로 묶인다
- `group_lines`: 밴드가 연쇄적으로 커지지 않는다 (첫 줄 기준 판정 검증)
- `group_lines`: 빈 입력은 빈 문자열
- `filter_characters`: `학/석사`, `국내(대한민국)`, `8월 31일(월)`, `1/2금융권`이 그대로 남는다
- `filter_characters`: `Ca「d` → `Cad` (제거만, 치환 없음), `回`·`口`가 사라진다
- `filter_characters`: 연속 공백이 하나로 줄고 양끝 공백이 사라진다
- `build_searchable_pdf`: 생성된 PDF에서 추출한 텍스트에 인식 문자열이 들어 있다
- `build_searchable_pdf`: 페이지 크기가 원본 이미지 크기와 같다

**통합 — `ex.png` 골든 테스트**
- 결과에 `2026 신입 인재 모집`, `여의도 본사 근무`, `모집분야`가 포함된다
- OCR은 완벽하지 않으므로 정확 일치가 아니라 **핵심 문자열 포함**으로 검증한다
- 한국어 인식기가 없는 환경에서는 `skip`

**입력 분기**
- 클립보드가 비었을 때 `OcrError`
- 존재하지 않는 파일 경로일 때 `OcrError`

## 8. 이번 범위에서 제외 (YAGNI)

- 한국어·영어 이외 언어
- 영어 인식기 2차 패스 후 병합 — 복잡도 대비 이득이 불확실
- 표 선 검출(OpenCV), 기울기 보정, 여러 이미지 일괄 처리
- 인식 결과 신뢰도 표시
- 글자 혼동 교정·맞춤법 보정 등 결과 텍스트에 대한 일체의 **치환** (§4.5는 제거만 한다)
- 여러 이미지를 한 PDF로 묶기 — 한 이미지 한 PDF만 만든다

## 9. 완료 기준

1. `python image_to_text.py ex.png`가 표의 항목과 내용이 같은 줄에 묶인 텍스트를 출력한다
2. 앱의 "이미지 텍스트" 탭에서 Ctrl+V와 파일 불러오기가 모두 동작한다
3. 결과를 편집하고 복사·저장(.txt/.md/PDF)할 수 있다
4. 저장한 PDF에서 이미지가 보이면서 그 위 텍스트를 드래그·복사할 수 있다
5. 모든 테스트가 통과한다
6. `imageConverter_GUIDE.html`이 실제 파일명·실제 동작과 일치한다
