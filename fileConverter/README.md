# Local Converter

인터넷에 파일을 업로드하지 않고 PC에서 미디어와 문서를 변환하는 로컬 도구입니다. CLI와 Windows GUI를 제공합니다.

## 지원 범위

- 미디어: FFmpeg가 지원하는 모든 입력/출력 형식. 하드코딩된 확장자 목록으로 제한하지 않으므로 FFmpeg 버전에 포함된 형식을 그대로 사용할 수 있습니다.
- 문서: DOC/DOCX, PPT/PPTX, XLS/XLSX, ODT/ODP/ODS, RTF/CSV -> PDF (LibreOffice 필요)
- EXE/BAT도 파일 선택 창에서 선택할 수 있습니다. 다만 변환 자체는 FFmpeg가 해당 파일을 미디어로 해석할 수 있을 때만 가능합니다.
- PDF 압축: Ghostscript의 `screen`/`ebook`/`printer` 품질을 지원합니다.
- PDF -> JPG/PNG: 여러 페이지를 페이지별 이미지로 자동 저장합니다. 기본 해상도는 150 DPI입니다.
- Office 문서 압축: `DOCX/PPTX/XLSX -> PDF` 변환과 동시에 PDF를 압축합니다. Office 원본 내부 이미지까지 재압축하는 작업은 원본 레이아웃 손상 위험 때문에 자동 처리하지 않습니다.

## 설치

Python 3.10 이상과 다음 프로그램을 설치하세요.

1. [FFmpeg](https://ffmpeg.org/download.html): 미디어 변환용
2. [LibreOffice](https://www.libreoffice.org/download/download/): Office 문서 -> PDF용

FFmpeg와 LibreOffice를 설치한 뒤 새 터미널을 열어주세요. 프로그램이 PATH에 없어도 LibreOffice의 기본 Windows 설치 경로는 자동으로 확인합니다.

## GUI 실행

Windows에서 `로컬_변환기_실행.bat`을 더블클릭하거나 다음 명령을 실행합니다.

```powershell
python converter_gui.py
```

GUI에서 파일 선택 -> 변환 형식 선택 또는 직접 입력 -> 출력 폴더 선택 -> 변환 시작 순서로 사용합니다. `mp3`, `wav`, `mp4`, `pdf` 외에도 FFmpeg가 지원하는 형식을 직접 입력할 수 있습니다.

## CLI 실행

```powershell
python local_converter.py video.mp4 --to mp3
python local_converter.py slides.pptx --to pdf --output-dir converted
python local_converter.py report.docx --to pdf --overwrite
python local_converter.py report.pdf --to pdf --compress --quality ebook --overwrite
python local_converter.py report.docx --to pdf --compress --quality screen --overwrite
python local_converter.py manual.pdf --to jpg --output-dir images --dpi 200
```

PDF를 이미지로 바꾸려면 Poppler의 `pdftoppm` 또는 `pdftocairo`를 설치하고 PATH에 추가해야 합니다.

모든 변환은 로컬 프로세스로 처리하며 파일을 외부 서버에 전송하지 않습니다.
