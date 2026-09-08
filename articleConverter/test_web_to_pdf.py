import unittest

import web_to_pdf


HAS_PARSER = web_to_pdf.BeautifulSoup is not None


class WebToPdfTests(unittest.TestCase):
    def test_safe_filename_removes_windows_unsafe_characters(self):
        self.assertEqual(web_to_pdf.safe_filename('a/b:c*?"<>|'), "a b c")

    def test_short_static_article_is_marked_for_browser_rendering(self):
        article = web_to_pdf.Article("title", "https://example.com", (web_to_pdf.TextBlock("짧은 본문"),))
        self.assertLess(web_to_pdf._text_length(article), web_to_pdf.MINIMUM_STATIC_TEXT)

    def test_naver_desktop_url_is_normalized_to_public_mobile_article(self):
        self.assertEqual(
            web_to_pdf._fetch_url("https://blog.naver.com/pangyo_nevergiveup_/224310471995"),
            "https://m.blog.naver.com/pangyo_nevergiveup_/224310471995",
        )
        self.assertEqual(
            web_to_pdf.validate_url(" https://blog.naver.com/pangyo_nevergiveup_/224310471995, "),
            "https://blog.naver.com/pangyo_nevergiveup_/224310471995",
        )

    @unittest.skipUnless(HAS_PARSER, "beautifulsoup4 is not installed")
    def test_dcinside_body_selector_keeps_only_article_text_and_images(self):
        page = """
        <html><head><title>게시글 제목 - 사이트</title></head><body>
          <nav>메뉴 광고</nav>
          <div class="write_div">
            정말 부끄러운 수준의 포트폴리오지만 한번 공유해봐요!<br>
            이와 같은 방식의 포트폴리오도 하나의 참고 사례로 봐주시면 감사하겠습니다.<br>
            <img src="//dcimg1.dcinside.com/viewimage.jpg">
            <img data-original="https://dcimg1.dcinside.com/viewimage2.jpg">
          </div>
          <div class="comment">댓글과 추천</div>
        </body></html>
        """
        article = web_to_pdf.extract_article(page, "https://gall.dcinside.com/mgallery/board/view/?id=backend&no=1")
        self.assertEqual(
            [block.text for block in article.blocks if isinstance(block, web_to_pdf.TextBlock)],
            [
                "정말 부끄러운 수준의 포트폴리오지만 한번 공유해봐요!",
                "이와 같은 방식의 포트폴리오도 하나의 참고 사례로 봐주시면 감사하겠습니다.",
            ],
        )
        self.assertEqual(
            [block.url for block in article.blocks if isinstance(block, web_to_pdf.ImageBlock)],
            ["https://dcimg1.dcinside.com/viewimage.jpg", "https://dcimg1.dcinside.com/viewimage2.jpg"],
        )

    @unittest.skipUnless(HAS_PARSER, "beautifulsoup4 is not installed")
    def test_generic_article_excludes_navigation_and_comments(self):
        page = """
        <html><body><main><nav>필요없는 메뉴</nav><article>
          <h1>본문 제목</h1><p>첫 번째 본문입니다.</p><p>두 번째 본문입니다.</p>
          <img src="images/one.png"><div class="comments">댓글 200개</div>
        </article></main></body></html>
        """
        article = web_to_pdf.extract_article(page, "https://example.com/posts/1")
        text = [block.text for block in article.blocks if isinstance(block, web_to_pdf.TextBlock)]
        self.assertEqual(text, ["본문 제목", "첫 번째 본문입니다.", "두 번째 본문입니다."])
        images = [block.url for block in article.blocks if isinstance(block, web_to_pdf.ImageBlock)]
        self.assertEqual(images, ["https://example.com/posts/images/one.png"])

    @unittest.skipUnless(HAS_PARSER, "beautifulsoup4 is not installed")
    def test_tistory_body_selector_excludes_post_header(self):
        page = """
        <html><body><article class="mobile-article">
          <header>카테고리 없음 LEFT JOIN 인덱스 설계 문제 gw1 2026. 3. 15.</header>
          <div class="blogview_content editor_ke"><p>실제 본문입니다.</p><img src="body.png"></div>
        </article></body></html>
        """
        article = web_to_pdf.extract_article(page, "https://gw7193.tistory.com/m/117")
        self.assertEqual(
            [block.text for block in article.blocks if isinstance(block, web_to_pdf.TextBlock)],
            ["실제 본문입니다."],
        )
        self.assertEqual(
            [block.url for block in article.blocks if isinstance(block, web_to_pdf.ImageBlock)],
            ["https://gw7193.tistory.com/m/body.png"],
        )

    @unittest.skipUnless(HAS_PARSER, "beautifulsoup4 is not installed")
    def test_catch_body_selector_excludes_site_navigation(self):
        page = """
        <html><body><nav>CATCH 채용공고 전체 메뉴</nav>
          <div id="contents2"><div class="news_detail_cont">
            <p>캣치 기사 본문입니다.</p><img src="images/news.png">
          </div></div><footer>회사 정보</footer>
        </body></html>
        """
        article = web_to_pdf.extract_article(page, "https://www.catch.co.kr/News/RecruitNews/296945")
        self.assertEqual(
            [block.text for block in article.blocks if isinstance(block, web_to_pdf.TextBlock)],
            ["캣치 기사 본문입니다."],
        )
        self.assertEqual(
            [block.url for block in article.blocks if isinstance(block, web_to_pdf.ImageBlock)],
            ["https://www.catch.co.kr/News/RecruitNews/images/news.png"],
        )

    @unittest.skipUnless(HAS_PARSER, "beautifulsoup4 is not installed")
    def test_linkareer_body_selector_excludes_actions_and_comments(self):
        page = """
        <html><body>
          <div id="post-detail-container">
            <div class="post-header">게시글 제목과 작성자</div>
            <div id="post-detail-content-container">
              <p>실제 게시글 첫 문단입니다.</p><img src="images/article.png">
              <p>실제 게시글 마지막 문단입니다.</p>
            </div>
            <div class="action-wrapper">추천과 공유</div>
          </div>
          <div class="comments">댓글 내용</div>
        </body></html>
        """
        article = web_to_pdf.extract_article(page, "https://community.linkareer.com/employment_data/1")
        self.assertEqual(
            [block.text for block in article.blocks if isinstance(block, web_to_pdf.TextBlock)],
            ["실제 게시글 첫 문단입니다.", "실제 게시글 마지막 문단입니다."],
        )
        self.assertEqual(
            [block.url for block in article.blocks if isinstance(block, web_to_pdf.ImageBlock)],
            ["https://community.linkareer.com/employment_data/images/article.png"],
        )

    @unittest.skipUnless(HAS_PARSER, "beautifulsoup4 is not installed")
    def test_naver_mobile_body_selector_excludes_post_header(self):
        page = """
        <html><body>
          <div class="post_ct">
            <div class="post_header">블로그 제목과 작성일</div>
            <div class="se-main-container"><p>실제 블로그 본문입니다.</p><img data-src="images/post.png"></div>
          </div>
          <div class="comment">댓글</div>
        </body></html>
        """
        article = web_to_pdf.extract_article(page, "https://m.blog.naver.com/example/123")
        self.assertEqual(
            [block.text for block in article.blocks if isinstance(block, web_to_pdf.TextBlock)],
            ["실제 블로그 본문입니다."],
        )
        self.assertEqual(
            [block.url for block in article.blocks if isinstance(block, web_to_pdf.ImageBlock)],
            ["https://m.blog.naver.com/example/images/post.png"],
        )

if __name__ == "__main__":
    unittest.main()
