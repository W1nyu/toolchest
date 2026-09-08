# Article Converter

공개 웹페이지 URL을 입력하면 광고·메뉴·댓글 같은 주변 요소를 최대한 제외하고, 본문 텍스트와 본문 안의 이미지를 PDF로 저장하는 로컬 Python 도구입니다.

자세한 설치와 사용법은 [GUIDE.html](./GUIDE.html)을 브라우저로 열어 확인하세요.

## 가장 빠른 실행

1. Python 3.10 이상을 설치합니다.
2. 이 폴더에서 다음 명령을 한 번 실행합니다.

   ~~~powershell
   python -m pip install -r requirements.txt
   ~~~

3. Windows에서는 articleConverter_실행.bat를 더블클릭하거나 다음 명령을 실행합니다.

   ~~~powershell
   python article_converter_gui.py
   ~~~

## 명령줄 실행

~~~powershell
python web_to_pdf.py "https://gall.dcinside.com/mgallery/board/view/?id=backend&no=58539"
python web_to_pdf.py "https://gw7193.tistory.com/m/117" --include-source
python web_to_pdf.py "https://www.catch.co.kr/News/RecruitNews/296945" --output-dir "C:\PDF"
~~~

기본 저장 위치는 이 폴더 아래의 output/pdf입니다.

## 지원 범위

DCinside, Tistory, Catch에는 본문 선택 규칙을 별도로 적용합니다. 그 외 공개 기사·블로그 URL도 article, main, articleBody 같은 일반적인 본문 구조를 찾아 변환합니다. 로그인, 유료벽, CAPTCHA, 접근 차단, 복잡한 앱형 페이지는 변환하지 못할 수 있습니다.

Catch처럼 자바스크립트로 본문이 채워지는 페이지는 설치된 Microsoft Edge 또는 Google Chrome을 백그라운드에서 사용합니다. 브라우저는 열리지 않으며, 페이지 변환 뒤 임시 프로필도 삭제됩니다.

원문·이미지의 저작권, 이용 조건, 접근 정책은 URL을 입력한 사용자가 확인해야 합니다.
