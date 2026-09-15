# pdfPages — PDF 합치기 · PDF 분할

작성일: 2026-09-15
상태: 승인됨 (구현 대기)

## 목적

여러 PDF를 원하는 순서·원하는 페이지만 골라 하나로 합치고(4번째 기능),
한 PDF에서 원하는 페이지만 뽑아 새 PDF로 만든다(5번째 기능).
`tools` 프로젝트의 기존 세 기능(`fileConverter`, `articleConverter`, `imageConverter`)과
같은 앱·같은 철학(로컬 처리, 업로드 없음)을 따른다.

**어느 페이지를 쓸지 눈으로 보고 고를 수 있어야 한다.** 페이지마다 썸네일을 보여주고,
썸네일을 클릭해 선택하면 페이지 칸이 채워진다. 원본 파일은 절대 수정하지 않고 항상 새 PDF를 만든다.

## 확정된 결정과 근거

| 결정 | 선택 | 근거 |
|---|---|---|
| 합치기·분할 엔진 | `pypdf` | 순수 Python, 이미 설치됨(6.14.2). 원본 페이지 객체를 그대로 복사하므로 화질·글자·링크 손실이 없다. Ghostscript는 이 PC에 없고 재렌더링으로 결과가 바뀐다 |
| 썸네일 렌더링 | `pypdfium2` | 이 PC에 Poppler·Ghostscript가 없다. pypdfium2는 `pip install`만으로 끝나고(Python 3.14용 `py3-none-win_amd64` 휠 확인) 외부 프로그램이 필요 없다 |
| 분할 결과 형태 | 지정 페이지를 모아 **PDF 1개** | 구간마다 파일을 나누는 방식은 이번 범위에서 제외. 원하는 부분만 뽑는 용도에 가장 단순하다 |
| 합치기 순서 UI | 목록 + `↑`/`↓` 버튼 | Tkinter에서 드래그 정렬은 직접 구현해야 하고 불안정하다 |
| 페이지 지정 | 텍스트 칸 `"1-3, 5, 8-10"` + 썸네일 클릭 **양방향 동기화** | 클릭이 직관적이고, 순서를 바꾸고 싶을 때(`3,1,2`)는 칸에 직접 적는다 |
| 저장 방식 | 저장 폴더 + 자동 이름 + 덮어쓰기 체크박스 | 기존 탭과 동일한 방식 |
| 원본 보호 | 읽기 전용으로만 열고, 결과는 임시 파일에 쓴 뒤 최종 이름으로 이동 | 중간에 실패해도 반쯤 쓰인 파일이 남지 않는다 |

## 1. 파일 구성

```
src/pdf_pages.py              코어 모듈. 페이지 범위 파싱, 합치기, 분할, 썸네일 렌더링. GUI 비의존, 단독 CLI 실행 가능
src/page_picker.py            공용 GUI 위젯 PagePicker. 썸네일 격자 + 클릭 선택 + 페이지 칸 양방향 동기화
src/converter_gui.py          (수정) "PDF 합치기", "PDF 분할" 탭 추가. 두 탭 모두 PagePicker를 쓴다
tests/test_pdf_pages.py       코어 테스트
tests/test_page_picker.py     위젯 헤드리스 테스트
tests/test_converter_gui.py   (수정) 새 탭 테스트
docs/guides/pdfPages_GUIDE.html   가이드 (기존 세 가이드와 같은 톤/구조)
README.md                     (수정) 4·5번째 기능 추가
requirements.txt              (수정) pypdf, pypdfium2 추가
```

`PagePicker`를 별도 파일로 두는 이유: 두 탭이 똑같이 쓰는 데다 `converter_gui.py`가 이미 466줄이라,
격자 렌더링·스크롤·선택 로직까지 넣으면 한 파일이 너무 커진다.
`pdf_pages.py`는 기존 `web_to_pdf.py` / `local_converter.py`와 같은 층위다: 코어는 GUI를 모르고
GUI는 코어를 호출만 한다.

## 2. 코어 모듈 공개 인터페이스 (`pdf_pages.py`)

```python
class PdfPagesError(Exception):
    """사용자에게 그대로 보여줄 수 있는 한국어 메시지를 담는다."""

THUMBNAIL_WIDTH = 110   # px

def parse_page_range(text: str, page_count: int) -> list[int]
def format_page_range(pages: Iterable[int]) -> str
def pdf_page_count(path: Path | str) -> int
def render_page(path: Path | str, page_number: int, width: int = THUMBNAIL_WIDTH) -> PIL.Image.Image
def merge_pdfs(sources: Sequence[tuple[Path | str, str]], destination: Path | str, *, overwrite: bool = False) -> Path
def split_pdf(source: Path | str, pages: str, destination: Path | str, *, overwrite: bool = False) -> Path
def main(argv: list[str] | None = None) -> int
```

페이지 번호는 **모두 1부터 시작하는 사람 기준**이다. pypdf/pypdfium2의 0 기준 인덱스는 모듈 안에서만 쓴다.

### 2.1 `parse_page_range(text, page_count)` — 순수 함수

| 입력 | 결과 |
|---|---|
| `""`, `"   "` | `[1, 2, ..., page_count]` (전체) |
| `"1-3, 5, 8-10"` | `[1, 2, 3, 5, 8, 9, 10]` |
| `"3,1,2"` | `[3, 1, 2]` (적은 순서 유지) |
| `"1,1"` | `[1, 1]` (중복 허용 — 같은 쪽을 두 번 넣을 수 있다) |
| `"5-3"` | `PdfPagesError`: "페이지 범위는 작은 수에서 큰 수 순서여야 합니다: 5-3" |
| `"0"`, `"13"` (전체 12쪽) | `PdfPagesError`: "1부터 12 사이의 페이지만 지정할 수 있습니다: 13" |
| `"a"`, `"1-"`, `"-3"`, `"1--3"` | `PdfPagesError`: "페이지 지정을 이해할 수 없습니다: a" |

구분자는 쉼표. 쉼표·하이픈 주위 공백은 무시한다. 전각 쉼표(`，`)와 한글 입력기의 `、`도 쉼표로 받는다.

### 2.2 `format_page_range(pages)` — 순수 함수

집합을 **오름차순 압축 표기**로 바꾼다. `parse_page_range`의 역함수 역할이며 썸네일 클릭 → 칸 채우기에 쓴다.

| 입력 | 결과 |
|---|---|
| `{1, 2, 3, 5}` | `"1-3, 5"` |
| `{2}` | `"2"` |
| `{4, 5}` | `"4-5"` |
| `set()` | `""` |

중복은 무시하고 순서는 항상 오름차순이다. 따라서 칸에 `3,1,2`를 적은 뒤 썸네일을 클릭하면 `1-3`으로 정규화된다. 가이드에 명시한다.

### 2.3 `pdf_page_count(path)` / `render_page(path, page_number, width)`

- `pdf_page_count`: pypdf로 열어 쪽 수를 돌려준다. 열 수 없으면 §6의 규칙대로 `PdfPagesError`.
- `render_page`: pypdfium2로 해당 쪽을 폭 `width`px에 맞춰 렌더링한 RGB `PIL.Image`를 돌려준다.
  높이는 페이지 비율에 따른다. 배율은 `width / 페이지 폭(pt)`으로 계산한다.
  문서는 호출마다 열고 닫는다(호출자가 캐시한다).
  `pypdfium2`는 이 함수 안에서 지연 임포트한다. 미설치여도 합치기·분할(pypdf)은 동작해야 한다(§6).

### 2.4 `merge_pdfs(sources, destination, *, overwrite)`

- `sources`는 `(경로, 페이지 문자열)`의 순서 있는 목록. 페이지 문자열이 빈 문자열이면 전체.
- 원소가 2개 미만이면 `PdfPagesError`: "PDF를 2개 이상 지정하세요."
- 모든 파일을 먼저 열어 쪽 수를 확인하고 모든 페이지 문자열을 파싱한 뒤에 쓰기 시작한다.
  (3번째 파일의 오류 때문에 1·2번째를 쓰다 마는 일이 없다.)
- 순서대로 `PdfWriter.add_page`로 원본 페이지 객체를 복사한다.
- 결과 쪽 수가 0이면 `PdfPagesError`: "합칠 페이지가 없습니다."
- 저장 규칙은 §2.6.

### 2.5 `split_pdf(source, pages, destination, *, overwrite)`

- `pages`가 비어 있으면(공백만 포함) `PdfPagesError`: "분리할 페이지를 입력하세요." — 전체를 다시 쓰는 것은 분할이 아니다.
- 그 외는 `merge_pdfs([(source, pages)], ...)`와 같은 로직으로 새 PDF 1개를 만든다.

### 2.6 저장 규칙 (merge·split 공통)

1. `destination`이 이미 있고 `overwrite=False`면 `PdfPagesError`: "같은 이름의 PDF가 이미 있습니다: {경로}"
2. `destination.parent`를 만든다(`mkdir(parents=True, exist_ok=True)`).
3. 같은 폴더의 `.{stem}.writing.pdf` 임시 파일에 쓴 뒤 `os.replace`로 최종 이름으로 옮긴다.
   실패하면 임시 파일을 지운다.
4. 반환값은 최종 경로.

### 2.7 CLI

```
python src/pdf_pages.py merge a.pdf "b.pdf:1-3,5" c.pdf --output output/pdf/a_합본.pdf [--overwrite]
python src/pdf_pages.py split in.pdf --pages "2-4,7" [--output-dir output/pdf] [--output 이름.pdf] [--overwrite]
```

- `merge`의 각 입력은 `경로` 또는 `경로:페이지`. 마지막 콜론 뒤를 페이지 문자열로 본다
  (`C:\a.pdf` 같은 드라이브 문자 콜론은 확장자 `.pdf`로 끝나는지 보고 구분한다: 문자열이 `.pdf`로 끝나면 페이지 없음).
- `--output`을 생략하면 §5.3의 자동 이름 규칙을 쓴다.
- 성공 시 결과 경로를 출력하고 0, `PdfPagesError`면 메시지를 stderr에 쓰고 1을 돌려준다. 기존 CLI들과 같다.

## 3. PagePicker 위젯 (`page_picker.py`)

```python
class PagePicker(ttk.Frame):
    def __init__(self, master, pages_var: tk.StringVar, status_var: tk.StringVar | None = None)
    def load(self, path: Path | None) -> None      # None이면 비운다
    def selected_pages(self) -> set[int]
    page_count: int                                # 현재 문서 쪽 수 (없으면 0)
```

### 3.1 구성

- 가로로 흐르는 썸네일 격자. `Canvas` + 내부 `Frame` + 세로 `Scrollbar`. 폭에 맞춰 열 수를 자동 계산하고
  창 크기가 바뀌면 다시 배치한다. 마우스 휠로 스크롤된다.
- 썸네일 하나 = `Label`(이미지) + 아래 쪽 번호 `Label`. 선택된 쪽은 파란 테두리(두께 3), 아니면 연한 회색 테두리.
- 렌더링 전에는 회색 자리표시자(110×150). 렌더링에 실패한 쪽은 `?`를 표시하되 클릭·선택은 된다.

### 3.2 양방향 동기화

- **썸네일 클릭 → 칸**: 선택 집합을 토글하고 `pages_var`에 `format_page_range(선택)`을 쓴다.
- **칸 → 썸네일**: `pages_var` 추적(`trace_add("write")`). `parse_page_range(text, page_count)`가 성공하면
  그 집합대로 강조한다. **빈 문자열이면 아무것도 강조하지 않는다.** (합치기의 "비우면 전체"는 코어의 의미이고,
  위젯이 전체를 강조해 두면 첫 클릭이 "한 쪽 빼기"가 되어 혼란스럽다. 빈 상태에서 클릭하면 그 쪽 하나만 선택된다.)
  실패하면 `status_var`에 메시지를 쓰고 강조는 마지막 유효 상태를 유지한다.
- 순환 방지: 위젯이 스스로 `pages_var`를 쓸 때는 플래그를 세워 추적 콜백을 건너뛴다.

### 3.3 렌더링과 캐시

- `load(path)`가 불리면 쪽 수만큼 자리표시자를 먼저 그리고, 백그라운드 스레드가 1쪽부터
  `render_page`로 그려 `after`로 하나씩 채운다. 기존 탭의 스레드 + `after` 패턴과 같다.
- 캐시 키는 `(절대 경로, 수정 시각)`. 캐시는 PagePicker 인스턴스 안에 두어 합치기 목록에서 행을 오갈 때 다시 그리지 않는다.
- 로드 중에 다른 파일을 `load`하면 이전 스레드의 결과는 세대 번호로 걸러 버린다.
- 썸네일 하나는 약 50KB(110×150 RGB)이므로 수백 쪽도 메모리 부담이 없다.

## 4. GUI 탭 — PDF 합치기 (4번째 탭)

```
[PDF 추가] [제거] [↑ 위로] [↓ 아래로]
┌ 파일 목록 (Treeview) ───────────────────────┐
│ 순서 │ 파일명   │ 전체 쪽 │ 사용할 페이지     │
│  1   │ a.pdf    │   12    │ 전체              │
│  2   │ b.pdf    │    5    │ 1-3, 5            │
└─────────────────────────────────────────────┘
선택한 파일의 페이지 [1-3, 5           ]  비우면 전체
┌ PagePicker ─────────────────────────────────┐
│  [1]  [2]  [3]  [4]  [5]  [6] ...           │
└─────────────────────────────────────────────┘
저장 폴더 [output/pdf          ] [폴더 선택]
결과 이름 [a_합본.pdf           ]  □ 같은 이름이면 덮어쓰기
                                       [PDF 합치기]
상태 메시지
```

- `[PDF 추가]`: 여러 파일 선택 대화상자(`askopenfilenames`). 각 파일을 `pdf_page_count`로 확인해 목록에 넣고,
  열 수 없는 파일은 상태줄에 이유를 쓰고 건너뛴다. 첫 파일이 추가되면 결과 이름을 `{첫 파일 stem}_합본.pdf`로 채운다.
- 목록 행을 고르면 PagePicker가 그 파일을 `load`하고 페이지 칸이 그 행의 값으로 바뀐다.
- 페이지 칸을 고치면 현재 행의 "사용할 페이지" 열이 즉시 바뀐다(빈 칸은 `전체`로 표시).
- `↑`/`↓`는 선택 행을 한 칸 옮기고 순서 열을 다시 매긴다. `[제거]`는 선택 행을 지운다.
- `[PDF 합치기]`: 목록 순서대로 `(경로, 페이지 문자열)`을 만들어 `merge_pdfs`를 스레드에서 실행.
  실행 중 버튼 비활성화, 완료 시 상태줄에 결과 경로, 실패 시 메시지.

## 5. GUI 탭 — PDF 분할 (5번째 탭)

```
입력 PDF [                        ] [파일 선택]
분리할 페이지 [2-4, 7             ]  전체 12쪽
┌ PagePicker ─────────────────────────────────┐
저장 폴더 [output/pdf          ] [폴더 선택]
결과 이름 [원본_p2-4,7.pdf       ]  □ 같은 이름이면 덮어쓰기
                                       [PDF 분할]
상태 메시지
```

### 5.1 동작
- `[파일 선택]` 후 PagePicker가 로드되고 "전체 n쪽"이 표시된다. 페이지 칸은 비운다.
- `[PDF 분할]`은 `split_pdf`를 스레드에서 실행한다. 페이지 칸이 비어 있으면 코어가 거부한 메시지를 그대로 보여준다.

### 5.2 결과 이름 자동 갱신
- 페이지 칸이 바뀔 때마다 결과 이름을 `{원본 stem}_p{페이지}.pdf`로 다시 쓴다. `{페이지}`는 칸의 값에서 공백을 뺀 것(`2-4,7`).
- **사용자가 결과 이름 칸을 직접 고친 뒤에는 자동 갱신하지 않는다.** 결과 이름 칸에 사용자가 입력하면
  `name_is_custom` 플래그를 세우고, 새 입력 PDF를 고르면 플래그를 내린다.
- 합치기 탭도 같은 규칙: 첫 파일이 바뀌면 자동 이름을 다시 쓰되 사용자가 고친 뒤에는 건드리지 않는다.

### 5.3 자동 이름 규칙 (CLI와 GUI 공통)
- 합치기: `{첫 파일 stem}_합본.pdf`
- 분할: `{원본 stem}_p{페이지 문자열에서 공백 제거}.pdf`

쉼표와 하이픈은 Windows 파일명에 허용된다.

### 5.4 공통
- 기본 저장 폴더는 웹 본문 PDF 탭과 같은 `output/pdf`.
- 두 탭 모두 기존 탭의 `ttk` 그리드 + 스레드 + `after` 패턴을 따른다.
- 창 기본 크기를 `820x640`에서 `900x720`으로 키운다. 썸네일 격자가 목록과 함께 보여야 한다.

## 6. 오류 처리

| 상황 | 동작 |
|---|---|
| PDF가 아닌 파일 / 손상된 PDF | `PdfPagesError("PDF 파일을 읽을 수 없습니다: {파일명}")` — 합치기 목록에 추가되지 않음 |
| 암호 걸린 PDF (`reader.is_encrypted`) | `PdfPagesError("암호가 걸린 PDF는 지원하지 않습니다: {파일명}")` |
| 페이지 칸 오류 | §2.1의 메시지. 칸을 고칠 때는 상태줄에만, 실행 버튼을 누르면 같은 메시지로 중단 |
| 합치기 파일이 2개 미만 | "PDF를 2개 이상 지정하세요." |
| 분할 페이지 칸이 비어 있음 | "분리할 페이지를 입력하세요." |
| 결과 파일이 이미 있음 + 덮어쓰기 해제 | "같은 이름의 PDF가 이미 있습니다: {경로}" |
| 결과 쪽 수 0 | "합칠 페이지가 없습니다." |
| 썸네일 렌더링 실패 (특정 쪽) | 그 칸만 `?`. 합치기·분할은 pypdf가 처리하므로 영향 없음 |
| pypdfium2 미설치 | 앱 시작 시 `ImportError`를 잡아 두 탭의 상태줄에 "pip install -r requirements.txt를 실행하세요" 표시. 썸네일 없이 칸 입력만으로 동작한다 |

모든 오류는 `PdfPagesError`로 통일하고 GUI는 메시지를 그대로 표시한다. 기존 `ConversionError` / `WebPdfError` / `OcrError`와 같은 방식이다.

## 7. 테스트

테스트용 PDF는 reportlab으로 임시 폴더에 만든다. 각 쪽에 `"PAGE n"` 텍스트를 찍어 결과 쪽의 출처를 확인할 수 있게 한다.

**`test_pdf_pages.py` — 순수 함수**
- `parse_page_range`: §2.1 표의 모든 행
- `format_page_range`: §2.2 표의 모든 행, `parse(format(s)) == sorted(s)` 왕복

**`test_pdf_pages.py` — 파일 처리**
- `pdf_page_count`가 쪽 수를 돌려준다; 비PDF·암호 PDF는 `PdfPagesError`
- `merge_pdfs`: 전체+전체 → 쪽 수 합, 텍스트 순서 확인
- `merge_pdfs`: 부분 지정 `(a, "1-2"), (b, "3")` → 3쪽, 각 쪽 텍스트가 `PAGE 1, PAGE 2, PAGE 3(b)`
- `merge_pdfs`: 순서 `b, a`로 주면 결과도 그 순서
- `merge_pdfs`: 원본의 크기·수정 시각이 변하지 않는다
- `merge_pdfs`: 파일 1개면 에러, 3번째 파일 페이지 오류 시 결과 파일이 생기지 않는다
- `split_pdf`: `"2-3"` → 2쪽, 텍스트 `PAGE 2, PAGE 3`; 빈 문자열 거부; 덮어쓰기 가드; `overwrite=True`면 성공
- `render_page`: 반환 이미지 폭이 요청 폭과 같고 높이 > 0

**`test_page_picker.py` — 헤드리스 Tk**
- `pages_var`에 `"1-2"`를 쓰면 `selected_pages() == {1, 2}`
- 썸네일 클릭 핸들러 호출 → `pages_var`가 `format_page_range` 결과가 된다
- 잘못된 값(`"9"` in 3쪽)을 쓰면 선택은 유지되고 `status_var`에 메시지

**`test_converter_gui.py` — 추가**
- 노트북에 탭이 5개이고 순서가 `파일 변환, 웹 본문 PDF, 이미지 텍스트, PDF 합치기, PDF 분할`
- 분할 탭: 입력 경로와 페이지 칸을 세팅하면 결과 이름이 `stem_p2-4,7.pdf`; 결과 이름을 직접 고친 뒤 페이지를 바꿔도 유지

기존 `test_converter_gui.py`의 `_on_paste_shortcut` 테스트가 탭 인덱스 `2`를 쓰므로 새 탭은 그 뒤에 붙여 기존 테스트를 깨지 않는다.

## 8. 이번 범위에서 제외 (YAGNI)

- 구간마다 파일을 나누는 분할 (`1-3 → 파일1, 5 → 파일2`)
- 드래그로 순서 바꾸기, 썸네일 드래그로 페이지 순서 바꾸기
- 썸네일 더블클릭 확대 보기
- 페이지 회전, 삭제, 북마크 편집
- 암호 PDF 열기(비밀번호 입력)
- 합치기 결과 압축(기존 파일 변환 탭의 PDF 압축을 이어서 쓰면 된다)

## 9. 완료 기준

1. `python src/pdf_pages.py merge a.pdf "b.pdf:1-3" --output out.pdf`가 지정 순서·지정 쪽만 담은 새 PDF를 만들고 원본은 그대로다
2. `python src/pdf_pages.py split in.pdf --pages 2-4`가 3쪽짜리 새 PDF를 만든다
3. 앱의 "PDF 합치기" 탭에서 파일 추가·순서 변경·행별 페이지 지정·썸네일 클릭 선택이 동작하고 결과 PDF가 생긴다
4. "PDF 분할" 탭에서 썸네일 클릭 또는 칸 입력으로 페이지를 고르고 결과 PDF가 생긴다
5. 모든 테스트가 통과한다
6. `pdfPages_GUIDE.html`과 README가 실제 파일명·실제 동작과 일치한다
