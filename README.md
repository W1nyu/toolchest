# Local Converter

인터넷에 파일을 업로드하지 않고 PC에서 미디어와 문서를 변환하는 로컬 도구입니다. CLI와 Windows GUI를 제공합니다. 웹페이지는 주소만 입력하면 광고·메뉴·댓글을 제외한 본문과 본문 이미지를 PDF로 저장할 수 있습니다. 이미지 속 글자는 Windows 내장 OCR로 추출해 텍스트나 검색 가능한 PDF로 저장할 수 있습니다. 여러 PDF를 원하는 순서·원하는 쪽만 골라 합치거나, 한 PDF에서 필요한 쪽만 뽑아 새 PDF로 만들 수도 있습니다. 쪽마다 썸네일을 보고 클릭해 고를 수 있으며 원본은 수정되지 않습니다.

## 폴더 구조

~~~text
src/            실행 코드와 Windows OCR 브리지
scripts/        Windows 실행 스크립트
tests/          자동 테스트
docs/guides/    도구별 HTML 사용 가이드
docs/design/    디자인 참고 자료
assets/samples/ 예제 이미지
output/         생성된 결과물 (Git 추적 제외)
~~~

## 지원 범위

- 미디어: FFmpeg가 지원하는 모든 입력/출력 형식. 하드코딩된 확장자 목록으로 제한하지 않으므로 FFmpeg 버전에 포함된 형식을 그대로 사용할 수 있습니다.
- 문서: DOC/DOCX, PPT/PPTX, XLS/XLSX, ODT/ODP/ODS, RTF/CSV -> PDF (LibreOffice 필요)
- EXE/BAT도 파일 선택 창에서 선택할 수 있습니다. 다만 변환 자체는 FFmpeg가 해당 파일을 미디어로 해석할 수 있을 때만 가능합니다.
- PDF 압축: Ghostscript의 `screen`/`ebook`/`printer` 품질을 지원합니다.
- PDF -> JPG/PNG: 여러 페이지를 페이지별 이미지로 자동 저장합니다. 기본 해상도는 150 DPI입니다.
- Office 문서 압축: `DOCX/PPTX/XLSX -> PDF` 변환과 동시에 PDF를 압축합니다. Office 원본 내부 이미지까지 재압축하는 작업은 원본 레이아웃 손상 위험 때문에 자동 처리하지 않습니다.
- 웹 본문 PDF: 일반 기사·블로그 본문을 자동 탐지하고, DCInside 게시글은 본문 영역을 우선 인식합니다. 본문 안의 이미지도 순서대로 넣습니다.
- 이미지 텍스트: `src/image_to_text.py`가 Windows 내장 OCR(`src/win_ocr.ps1`)로 이미지에서 한국어·영어 텍스트를 추출합니다. 표처럼 같은 줄에 배치된 항목은 탭으로 구분되어 나오므로 엑셀·노션에 붙여넣기 좋습니다. `src/image_to_pdf.py`로 원본 이미지 위에 보이지 않는 텍스트 레이어를 얹은 검색 가능한 PDF도 만들 수 있습니다.
- PDF 합치기·분할: `src/pdf_pages.py`가 pypdf로 원본 쪽을 그대로 복사해 새 PDF를 만듭니다. 합치기는 파일 순서와 파일별 쪽(`1-3, 5`)을 지정할 수 있고, 분할은 지정한 쪽만 모아 PDF 1개를 만듭니다. GUI에서는 pypdfium2로 그린 쪽 썸네일을 클릭해 고를 수 있습니다. 원본은 읽기만 하며 결과는 항상 새 파일입니다.

## 설치

Python 3.10 이상과 다음 프로그램을 설치하세요.

1. [FFmpeg](https://ffmpeg.org/download.html): 미디어 변환용
2. [LibreOffice](https://www.libreoffice.org/download/download/): Office 문서 -> PDF용

웹 본문 PDF와 PDF 합치기·분할 기능에는 아래 Python 패키지도 필요합니다.

```powershell
python -m pip install -r requirements.txt
```

캣치처럼 본문을 자바스크립트로 나중에 채우는 사이트는 PC에 설치된 Microsoft Edge 또는 Google Chrome을 백그라운드로 잠시 사용합니다. Windows 기본 Edge가 있으면 별도 설치가 필요 없습니다.

FFmpeg와 LibreOffice를 설치한 뒤 새 터미널을 열어주세요. 프로그램이 PATH에 없어도 LibreOffice의 기본 Windows 설치 경로는 자동으로 확인합니다.

이미지 텍스트 기능은 Windows 내장 OCR(Windows.Media.Ocr)만 사용하므로 별도 프로그램 설치가 필요 없습니다. 다만 한국어 인식기가 없다면 설정 → 시간 및 언어 → 언어 및 지역 → 한국어의 언어 옵션에서 `광학 문자 인식`을 설치하세요.

## GUI 실행

Windows에서 `scripts/로컬_변환기_실행.bat`을 더블클릭하거나 다음 명령을 실행합니다.

```powershell
python src/converter_gui.py
```

GUI에서 파일 선택 -> 변환 형식 선택 또는 직접 입력 -> 출력 폴더 선택 -> 변환 시작 순서로 사용합니다. `mp3`, `wav`, `mp4`, `pdf` 외에도 FFmpeg가 지원하는 형식을 직접 입력할 수 있습니다.

웹 본문 PDF 탭에서는 URL을 붙여넣고 `본문 PDF 만들기`만 누르면 됩니다. 기본 저장 위치는 `output/pdf`이며, PDF에는 본문만 넣습니다. 필요하면 `PDF 첫 줄에 원본 URL 표시`를 선택하세요.

이미지 텍스트 탭에서는 `이미지 불러오기` 또는 Ctrl+V로 이미지를 넣고 `텍스트 추출`을 누릅니다. 결과는 편집창에서 직접 고칠 수 있고, `전체 복사`·`.txt 저장`·`.md 저장`·`PDF 저장`으로 내보낼 수 있습니다. PDF에는 편집창에서 고친 내용이 아니라 텍스트 추출 시점의 인식 결과가 들어갑니다.

PDF 합치기 탭에서는 `PDF 추가`로 파일을 넣고 `↑ 위로`·`↓ 아래로`로 순서를 정한 뒤, 행마다 썸네일을 클릭하거나 페이지 칸에 `1-3, 5`처럼 적어 쓸 쪽을 고릅니다(비우면 전체). PDF 분할 탭에서는 파일을 고르고 분리할 쪽을 클릭하거나 입력하면 `원본_p2-4,7.pdf`처럼 이름이 자동으로 채워집니다. 두 탭 모두 기본 저장 위치는 `output/pdf`입니다.

## CLI 실행

```powershell
python src/local_converter.py video.mp4 --to mp3
python src/local_converter.py slides.pptx --to pdf --output-dir converted
python src/local_converter.py report.docx --to pdf --overwrite
python src/local_converter.py report.pdf --to pdf --compress --quality ebook --overwrite
python src/local_converter.py report.docx --to pdf --compress --quality screen --overwrite
python src/local_converter.py manual.pdf --to jpg --output-dir images --dpi 200
python src/web_to_pdf.py "https://gall.dcinside.com/mgallery/board/view/?id=backend&no=58539"
python src/web_to_pdf.py "https://example.com/article" --output-dir saved-pdfs --include-source
python src/image_to_text.py assets/samples/ex.png
python src/image_to_text.py assets/samples/ex.png --output result.txt
python src/image_to_text.py assets/samples/ex.png --pdf result.pdf
python src/image_to_text.py --scale 4
python src/pdf_pages.py merge a.pdf "b.pdf:1-3,5" c.pdf --output merged.pdf
python src/pdf_pages.py split in.pdf --pages "2-4,7" --output-dir output/pdf
```

PDF를 이미지로 바꾸려면 Poppler의 `pdftoppm` 또는 `pdftocairo`를 설치하고 PATH에 추가해야 합니다.

`src/image_to_text.py`는 이미지 경로를 생략하면 클립보드의 이미지를 사용합니다. `--scale`의 기본값은 3으로, 인식 전에 이미지를 그만큼 확대해 정확도를 높입니다. 실측에서 2배보다 3배가 뚜렷이 나았고 그 이상은 거의 차이가 없었습니다. 긴 이미지는 인식기 한계(긴 변 10000px)에 맞춰 배율이 자동으로 낮아집니다.

모든 변환은 로컬 프로세스로 처리하며 파일을 외부 서버에 전송하지 않습니다.

## 웹페이지 PDF 참고

- 주소와 본문 이미지는 해당 웹사이트에서 직접 내려받습니다. 자바스크립트 본문은 Edge/Chrome으로 렌더링해 다시 읽습니다. 로그인·캡차·접근 제한 페이지는 저장되지 않을 수 있습니다.
- 광고·메뉴·댓글은 제외하도록 설계했지만, 사이트의 HTML 구조가 특이하면 본문 인식 결과를 확인하세요.
- 웹페이지와 이미지의 저작권·이용 조건은 사용자가 확인해야 합니다.

## 이미지 텍스트 참고

- Windows 내장 OCR(Windows.Media.Ocr)만 사용하며 이미지를 외부로 전송하지 않습니다. 한국어 인식기가 없는 PC에서는 사용할 수 없습니다.
- 인식 언어는 한국어·영어이며, 인식 전 이미지를 2배로 확대해 정확도를 높입니다.
- 숫자·한글·영문·공백·문장부호, `·` `•` `※`만 남기고 나머지 인식 노이즈는 제거합니다. 틀리게 읽은 글자를 다른 글자로 고쳐주지는 않습니다.
- PDF의 텍스트 레이어는 인식 시점의 좌표에 얹히므로, 편집창에서 고친 내용은 PDF에 반영되지 않습니다.
