# File Converter

파일을 인터넷에 올리지 않고 PC에서 미디어·문서를 변환하는 Python 데스크톱 도구입니다.

자세한 설치와 사용법은 [GUIDE.html](./GUIDE.html)을 브라우저로 열어 확인하세요.

## 가장 빠른 실행

Windows에서 로컬_변환기_실행.bat를 더블클릭하거나 다음 명령을 실행합니다.

~~~powershell
python converter_gui.py
~~~

필요한 프로그램은 변환 종류에 따라 다릅니다.

- 미디어 변환: [FFmpeg](https://ffmpeg.org/download.html)
- Office 문서에서 PDF: [LibreOffice](https://www.libreoffice.org/download/download/)
- PDF 압축: [Ghostscript](https://ghostscript.com/releases/)
- PDF에서 JPG/PNG: [Poppler](https://github.com/oschwartz10612/poppler-windows/releases/)

## 명령줄 예시

~~~powershell
python local_converter.py video.mp4 --to mp3
python local_converter.py slides.pptx --to pdf --output-dir converted
python local_converter.py report.pdf --to pdf --compress --quality ebook --overwrite
python local_converter.py manual.pdf --to jpg --output-dir images --dpi 200
~~~

모든 변환은 로컬 프로세스에서 처리합니다.
