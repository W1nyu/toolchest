# Toolchest

다운로드 후 내 PC에서 바로 실행하는 두 가지 변환 도구 모음입니다. 변환 대상 파일이나 웹페이지 본문을 외부 변환 서버에 업로드하지 않습니다.

| 도구 | 하는 일 | 시작하기 |
| --- | --- | --- |
| [fileConverter](./fileConverter/) | 미디어·문서 파일을 원하는 형식으로 변환 | Windows에서 [로컬_변환기_실행.bat](./fileConverter/%EB%A1%9C%EC%BB%AC_%EB%B3%80%ED%99%98%EA%B8%B0_%EC%8B%A4%ED%96%89.bat)를 더블클릭 |
| [articleConverter](./articleConverter/) | 공개 웹페이지에서 본문과 본문 이미지만 추려 PDF 저장 | Windows에서 [articleConverter_실행.bat](./articleConverter/articleConverter_%EC%8B%A4%ED%96%89.bat)를 더블클릭 |

각 도구의 설치, 사용 예시, 지원 범위와 문제 해결 방법은 아래 HTML 가이드에서 확인할 수 있습니다.

- [fileConverter 상세 가이드](./fileConverter/GUIDE.html)
- [articleConverter 상세 가이드](./articleConverter/GUIDE.html)

## 공통 준비

1. 이 저장소를 ZIP으로 내려받아 압축을 풉니다. 또는 Git으로 복제합니다.
2. Windows에서는 Python 3.10 이상을 설치할 때 Add Python to PATH를 선택합니다.
3. 각 도구 폴더의 README와 GUIDE.html에 적힌 준비 과정을 한 번만 진행합니다.

이 저장소는 GitHub Pages, Cloudflare Worker 등 웹 배포 구성을 사용하지 않습니다. 모든 실행은 내려받은 PC에서 이뤄집니다.
