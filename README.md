# Toolchest

작업에 바로 쓸 수 있는 작은 도구 모음입니다.

## 도구

- [fileConverter](./fileConverter/): PC에서 파일을 변환하는 Python 데스크톱 도구
- [articleConverter](./articleConverter/): 웹페이지 주소를 입력해 본문과 본문 이미지를 PDF로 저장하는 GitHub Pages 웹 도구

## articleConverter 배포

`main` 브랜치에 푸시하면 GitHub Actions가 `articleConverter/`를 GitHub Pages로 배포합니다. 저장소의 **Settings > Pages**에서 Source를 **GitHub Actions**로 한 번 선택하세요.

정적 GitHub Pages는 다른 사이트의 HTML을 직접 읽을 수 없으므로, articleConverter는 별도의 Cloudflare Worker가 본문을 렌더링·추출합니다. Worker 배포 주소를 GitHub repository variable `ARTICLE_CONVERTER_API_URL`로 설정하면 방문자는 URL만 입력하면 됩니다. 로그인, 유료벽, 캡차, 자동화 차단 페이지는 변환하지 못할 수 있으며, 원문과 이미지의 이용 조건은 사용자가 확인해야 합니다.
