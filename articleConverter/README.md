# Article Converter

GitHub Pages와 Cloudflare Worker로 동작하는 웹 본문 PDF 도구입니다.

1. 배포된 페이지에서 공개 웹페이지 주소를 입력합니다.
2. 본문 미리보기를 확인합니다.
3. **PDF로 저장**을 눌러 브라우저 인쇄 창에서 PDF로 저장합니다.

## 배포 순서

1. Cloudflare 계정에서 API 토큰과 Account ID를 준비해 GitHub repository secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`로 등록합니다.
2. GitHub Actions의 **Deploy articleConverter Worker**를 실행합니다.
3. 배포 로그에 표시된 Worker의 `https://...workers.dev` 주소를 repository variable `ARTICLE_CONVERTER_API_URL`로 등록합니다.
4. 저장소의 **Settings > Pages**에서 Source를 **GitHub Actions**로 선택한 뒤, **Deploy articleConverter to GitHub Pages**를 실행합니다.

Cloudflare Workers Free에는 브라우저 사용 시간이 하루 10분 포함됩니다. 로그인, 유료벽, 캡차, 자동화 차단 사이트는 서비스 정책에 따라 변환하지 못할 수 있습니다.
