"""Save only the main article text and in-article images from a web page as a PDF.

The converter deliberately downloads a normal HTML page instead of asking a
third-party service to process it.  It has a DCInside-specific extractor and a
generic main-content fallback for ordinary article and blog pages.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit

try:
    import requests
except ImportError:  # pragma: no cover - exercised by the runtime error path
    requests = None  # type: ignore[assignment]

try:
    from bs4 import BeautifulSoup, NavigableString, Tag
except ImportError:  # pragma: no cover - exercised by the runtime error path
    BeautifulSoup = None  # type: ignore[assignment,misc]
    NavigableString = Tag = Any  # type: ignore[assignment,misc]

try:
    from PIL import Image as PillowImage
    from PIL import ImageOps
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer
except ImportError:  # pragma: no cover - exercised by the runtime error path
    PillowImage = ImageOps = None  # type: ignore[assignment]
    Flowable = object  # type: ignore[assignment,misc]


DEFAULT_OUTPUT_DIR = Path("output") / "pdf"
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MINIMUM_STATIC_TEXT = 120
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
}
BLOCK_TAGS = {"p", "div", "section", "article", "blockquote", "pre", "li", "h1", "h2", "h3", "h4", "h5", "h6"}
REMOVE_TAGS = {"script", "style", "noscript", "template", "svg", "form", "button", "input", "iframe", "canvas"}
NOISE_SELECTORS = (
    "nav, aside, footer, header, [role='navigation'], [role='dialog'], "
    ".comment, .comments, .reply, .replies, .related, .recommend, "
    ".advertisement, .ad-banner, .adsbygoogle, [id*='advert'], [class*='advert']"
)
DCINSIDE_SELECTORS = (
    "div.write_div",
    "div[class~='write_div']",
    "#dgn_220",
    "div.view_content_wrap",
)
TISTORY_SELECTORS = (
    "div.blogview_content",
    "div.editor_ke",
    "div.tt_article_useless_p_margin",
    "#article-body",
)
CATCH_SELECTORS = (
    "div.news_detail_cont",
    "#contents2 div.news_detail_cont",
)
GENERIC_SELECTORS = (
    "article",
    "[itemprop='articleBody']",
    ".article-body",
    ".article_body",
    ".article-content",
    ".entry-content",
    ".post-content",
    ".post-body",
    ".content-body",
    "main",
)


class WebPdfError(RuntimeError):
    """Raised when a page cannot be safely converted to a PDF."""


@dataclass(frozen=True)
class TextBlock:
    text: str


@dataclass(frozen=True)
class ImageBlock:
    url: str


@dataclass(frozen=True)
class Article:
    title: str
    source_url: str
    blocks: tuple[TextBlock | ImageBlock, ...]


@dataclass(frozen=True)
class WebPdfResult:
    output: Path
    title: str
    text_blocks: int
    image_blocks: int
    skipped_images: tuple[str, ...]


def _require(*names: str) -> None:
    missing = []
    available = {
        "requests": requests is not None,
        "beautifulsoup4": BeautifulSoup is not None,
        "reportlab": "SimpleDocTemplate" in globals(),
        "Pillow": PillowImage is not None,
    }
    for name in names:
        if not available[name]:
            missing.append(name)
    if missing:
        joined = ", ".join(missing)
        raise WebPdfError(
            f"필수 패키지가 없습니다: {joined}. "
            "프로젝트 폴더에서 `python -m pip install -r requirements.txt`를 실행하세요."
        )


def validate_url(url: str) -> str:
    """Allow only ordinary public HTTP(S) web addresses."""
    candidate = url.strip()
    parts = urlsplit(candidate)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise WebPdfError("http:// 또는 https://로 시작하는 웹페이지 주소를 입력하세요.")
    host = (parts.hostname or "").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise WebPdfError("로컬 주소가 아닌 공개 웹페이지 주소를 입력하세요.")
    return candidate


def fetch_html(url: str, timeout: int = 30) -> tuple[str, str]:
    _require("requests")
    validate_url(url)
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
    except requests.RequestException as exc:  # type: ignore[union-attr]
        raise WebPdfError(f"웹페이지를 불러오지 못했습니다: {exc}") from exc
    content_type = response.headers.get("Content-Type", "").lower()
    if content_type and "html" not in content_type:
        raise WebPdfError("HTML 웹페이지 주소를 입력하세요.")
    return response.text, response.url


def _find_browser() -> str | None:
    """Find a Chromium browser that can render JavaScript without a UI."""
    for name in ("msedge", "msedge.exe", "chrome", "chrome.exe", "chromium", "chromium.exe"):
        found = shutil.which(name)
        if found:
            return found
    roots = [
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")),
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")),
        Path(os.environ.get("LOCALAPPDATA", "")),
    ]
    suffixes = (
        Path("Microsoft/Edge/Application/msedge.exe"),
        Path("Google/Chrome/Application/chrome.exe"),
        Path("Chromium/Application/chrome.exe"),
    )
    for root in roots:
        if not str(root):
            continue
        for suffix in suffixes:
            candidate = root / suffix
            if candidate.is_file():
                return str(candidate)
    return None


def fetch_rendered_html(url: str, timeout: int = 30) -> str:
    """Return the post-JavaScript DOM using installed Edge or Chrome headlessly."""
    browser = _find_browser()
    if not browser:
        raise WebPdfError("자바스크립트 본문을 읽으려면 Microsoft Edge 또는 Google Chrome이 필요합니다.")
    validate_url(url)
    with tempfile.TemporaryDirectory(prefix="web-pdf-browser-") as profile:
        command = [
            browser,
            "--headless",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--virtual-time-budget=6000",
            f"--user-data-dir={profile}",
            "--dump-dom",
            url,
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout + 12,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WebPdfError(f"브라우저 렌더링에 실패했습니다: {exc}") from exc
    rendered = completed.stdout.decode("utf-8", "replace")
    start = rendered.find("<html")
    end = rendered.rfind("</html>")
    if completed.returncode or start < 0 or end < start:
        details = completed.stderr.decode("utf-8", "replace").strip()
        raise WebPdfError(f"브라우저가 본문을 렌더링하지 못했습니다. {details[:250]}")
    return rendered[start:end + len("</html>")]


def _classes(element: Any) -> str:
    values = element.get("class", []) if getattr(element, "get", None) else []
    return " ".join(values).lower() if isinstance(values, list) else str(values).lower()


def _remove_noise(soup: Any) -> None:
    for node in soup.find_all(list(REMOVE_TAGS)):
        node.decompose()
    for node in soup.select(NOISE_SELECTORS):
        node.decompose()


def _title(soup: Any) -> str:
    meta = soup.find("meta", attrs={"property": "og:title"}) or soup.find("meta", attrs={"name": "twitter:title"})
    title = meta.get("content", "") if meta else ""
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", title).strip() or "web-article"


def _score_candidate(element: Any) -> int:
    text = element.get_text(" ", strip=True)
    if len(text) < 20 and not element.find("img"):
        return -10_000
    images = len(element.find_all("img"))
    paragraphs = len(element.find_all(["p", "li", "blockquote", "pre"]))
    line_breaks = len(element.find_all("br"))
    links = len(element.find_all("a"))
    classes = _classes(element)
    penalty = 800 if any(word in classes for word in ("menu", "nav", "comment", "reply", "sidebar", "footer")) else 0
    return len(text) + images * 450 + paragraphs * 90 + line_breaks * 30 - links * 12 - penalty


def _find_content_root(soup: Any, source_url: str) -> Any:
    hostname = (urlsplit(source_url).hostname or "").lower()
    if hostname.endswith("dcinside.com"):
        for selector in DCINSIDE_SELECTORS:
            found = soup.select_one(selector)
            if found and (found.get_text(strip=True) or found.find("img")):
                return found
    if hostname.endswith("tistory.com"):
        for selector in TISTORY_SELECTORS:
            found = soup.select_one(selector)
            if found and (found.get_text(strip=True) or found.find("img")):
                return found
    if hostname.endswith("catch.co.kr"):
        for selector in CATCH_SELECTORS:
            found = soup.select_one(selector)
            if found and (found.get_text(strip=True) or found.find("img")):
                return found

    for selector in GENERIC_SELECTORS:
        for found in soup.select(selector):
            if _score_candidate(found) > 0:
                return found

    candidates = soup.find_all(["article", "main", "section", "div"])
    if not candidates:
        raise WebPdfError("페이지에서 본문 후보를 찾지 못했습니다.")
    best = max(candidates, key=_score_candidate)
    if _score_candidate(best) <= 0:
        raise WebPdfError("본문이 너무 짧거나 페이지가 로그인/스크립트를 요구합니다.")
    return best


def _image_source(tag: Any, base_url: str) -> str | None:
    for attribute in ("data-original", "data-src", "data-lazy-src", "data-url", "src"):
        value = tag.get(attribute)
        if value and not value.startswith("javascript:"):
            return value if value.startswith("data:image/") else urljoin(base_url, value)
    srcset = tag.get("srcset")
    if srcset:
        selected = srcset.split(",")[-1].strip().split(" ")[0]
        return urljoin(base_url, selected)
    return None


def _clean_lines(raw: str) -> Iterable[str]:
    for line in raw.replace("\r", "").split("\n"):
        cleaned = re.sub(r"[\t \f\v]+", " ", line).strip()
        if cleaned:
            yield cleaned


def _blocks_from_root(root: Any, base_url: str) -> tuple[TextBlock | ImageBlock, ...]:
    blocks: list[TextBlock | ImageBlock] = []
    text_buffer: list[str] = []

    def flush_text() -> None:
        raw = "".join(text_buffer)
        text_buffer.clear()
        blocks.extend(TextBlock(line) for line in _clean_lines(raw))

    def walk(node: Any) -> None:
        if isinstance(node, NavigableString):
            text_buffer.append(str(node))
            return
        if not isinstance(node, Tag):
            return
        name = (node.name or "").lower()
        if name in REMOVE_TAGS or name in {"source", "video", "audio"}:
            return
        if name == "br":
            text_buffer.append("\n")
            return
        if name == "img":
            flush_text()
            image_url = _image_source(node, base_url)
            if image_url:
                blocks.append(ImageBlock(image_url))
            return
        is_block = name in BLOCK_TAGS
        if is_block:
            text_buffer.append("\n")
        for child in node.children:
            walk(child)
        if is_block:
            text_buffer.append("\n")

    walk(root)
    flush_text()
    return tuple(block for block in blocks if not isinstance(block, TextBlock) or block.text)


def extract_article(html_text: str, source_url: str) -> Article:
    """Extract an ordered sequence of body text and body images from HTML."""
    _require("beautifulsoup4")
    soup = BeautifulSoup(html_text, "html.parser")
    title = _title(soup)
    _remove_noise(soup)
    root = _find_content_root(soup, source_url)
    blocks = _blocks_from_root(root, source_url)
    if not any(isinstance(block, TextBlock) for block in blocks):
        raise WebPdfError("본문 텍스트를 찾지 못했습니다. 로그인 또는 접근 제한 페이지일 수 있습니다.")
    return Article(title=title, source_url=source_url, blocks=blocks)


def safe_filename(title: str, fallback: str = "web-article") -> str:
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", " ", title)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name[:100].strip() or fallback).rstrip(" .")


def _next_output_path(output_dir: Path, title: str, overwrite: bool) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    preferred = output_dir / f"{safe_filename(title)}.pdf"
    if overwrite or not preferred.exists():
        return preferred
    index = 2
    while True:
        candidate = output_dir / f"{safe_filename(title)} ({index}).pdf"
        if not candidate.exists():
            return candidate
        index += 1


def _text_length(article: Article) -> int:
    return sum(len(block.text) for block in article.blocks if isinstance(block, TextBlock))


def _font_name() -> str:
    candidates = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "malgun.ttf",
        Path("C:/Windows/Fonts/malgun.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJKkr-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            name = "WebArticleFont"
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(candidate)))
            return name
    return "Helvetica"


def _image_bytes(image_url: str, referer: str, timeout: int) -> bytes:
    if image_url.startswith("data:image/"):
        try:
            header, encoded = image_url.split(",", 1)
            if ";base64" not in header:
                raise ValueError("not base64")
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, UnicodeError) as exc:
            raise WebPdfError("본문의 인라인 이미지를 읽지 못했습니다.") from exc
        if len(payload) > MAX_IMAGE_BYTES:
            raise WebPdfError("본문 이미지가 25 MB보다 큽니다.")
        return payload

    _require("requests")
    try:
        response = requests.get(
            image_url,
            headers={**REQUEST_HEADERS, "Referer": referer},
            timeout=timeout,
            stream=True,
        )
        response.raise_for_status()
        declared_size = int(response.headers.get("Content-Length", "0") or 0)
        if declared_size > MAX_IMAGE_BYTES:
            raise WebPdfError("본문 이미지가 25 MB보다 큽니다.")
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(64 * 1024):
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                raise WebPdfError("본문 이미지가 25 MB보다 큽니다.")
            chunks.append(chunk)
        return b"".join(chunks)
    except requests.RequestException as exc:  # type: ignore[union-attr]
        raise WebPdfError(str(exc)) from exc


def _open_image(data: bytes) -> Any:
    _require("Pillow")
    try:
        with PillowImage.open(io.BytesIO(data)) as original:
            image = ImageOps.exif_transpose(original)
            if image.mode in {"RGBA", "LA"}:
                background = PillowImage.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                return background
            return image.convert("RGB")
    except Exception as exc:  # Pillow uses several format-specific error types
        raise WebPdfError("지원하지 않는 이미지 형식입니다.") from exc


class _SplittableImage(Flowable):
    """An image flowable that crops very tall images across PDF pages."""

    def __init__(self, image: Any, width: float) -> None:
        super().__init__()
        self.image = image
        self.width = width
        self.height = width * image.height / image.width

    def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
        return self.width, self.height

    def split(self, available_width: float, available_height: float) -> list[Flowable]:
        if self.height <= available_height or available_height < 24:
            return []
        pixels_per_point = self.image.width / self.width
        crop_height = max(1, int(available_height * pixels_per_point))
        top = self.image.crop((0, 0, self.image.width, crop_height))
        bottom = self.image.crop((0, crop_height, self.image.width, self.image.height))
        return [_SplittableImage(top, self.width), _SplittableImage(bottom, self.width)]

    def draw(self) -> None:
        from reportlab.lib.utils import ImageReader

        self.canv.drawImage(ImageReader(self.image), 0, 0, width=self.width, height=self.height, mask="auto")


def build_pdf(article: Article, destination: Path, *, include_source: bool, timeout: int) -> tuple[str, ...]:
    """Render article blocks. Failed images do not prevent the text PDF from being saved."""
    _require("reportlab", "Pillow")
    font = _font_name()
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "ArticleBody",
        parent=styles["BodyText"],
        fontName=font,
        fontSize=10.5,
        leading=17,
        alignment=TA_LEFT,
        spaceAfter=7,
        wordWrap="CJK",
    )
    source_style = ParagraphStyle(
        "Source",
        parent=body_style,
        fontSize=7.5,
        leading=10,
        textColor="#666666",
        spaceAfter=12,
    )
    story: list[Flowable] = []
    if include_source:
        story.append(Paragraph(html.escape(article.source_url), source_style))

    skipped: list[str] = []
    document_width = A4[0] - 36 * mm
    for block in article.blocks:
        if isinstance(block, TextBlock):
            story.append(Paragraph(html.escape(block.text).replace("\n", "<br/>"), body_style))
            continue
        try:
            image = _open_image(_image_bytes(block.url, article.source_url, timeout))
        except WebPdfError:
            skipped.append(block.url)
            continue
        story.append(_SplittableImage(image, document_width))
        story.append(Spacer(1, 8))

    temporary = destination.with_name(f".{destination.stem}.partial.pdf")
    document = SimpleDocTemplate(
        str(temporary),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=article.title,
        author="Web Article PDF",
    )
    try:
        document.build(story)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return tuple(skipped)


def webpage_to_pdf(
    url: str,
    output_dir: Path | None = None,
    *,
    overwrite: bool = False,
    include_source: bool = False,
    timeout: int = 30,
) -> WebPdfResult:
    """Download a page, isolate its main content, and save it as a PDF."""
    if timeout < 5:
        raise WebPdfError("시간 제한은 5초 이상이어야 합니다.")
    html_text, final_url = fetch_html(url, timeout)
    article = extract_article(html_text, final_url)
    # Some sites send only a shell in the first HTML response.  If that shell
    # contains almost no article text, ask the local browser for the rendered
    # DOM instead.  This keeps normal sites fast and handles JavaScript sites
    # such as Catch without sending content to a third-party conversion API.
    if _text_length(article) < MINIMUM_STATIC_TEXT:
        rendered_article = extract_article(fetch_rendered_html(final_url, timeout), final_url)
        if _text_length(rendered_article) <= _text_length(article):
            raise WebPdfError("렌더링 후에도 본문을 찾지 못했습니다. 로그인 또는 접근 제한 페이지일 수 있습니다.")
        article = rendered_article
    destination = _next_output_path(output_dir or DEFAULT_OUTPUT_DIR, article.title, overwrite)
    skipped = build_pdf(article, destination, include_source=include_source, timeout=timeout)
    return WebPdfResult(
        output=destination,
        title=article.title,
        text_blocks=sum(isinstance(block, TextBlock) for block in article.blocks),
        image_blocks=sum(isinstance(block, ImageBlock) for block in article.blocks),
        skipped_images=skipped,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="웹페이지의 본문과 본문 이미지만 PDF로 저장합니다.")
    parser.add_argument("url", help="저장할 http(s) 웹페이지 주소")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="PDF 저장 폴더 (기본: output/pdf)")
    parser.add_argument("--overwrite", action="store_true", help="같은 제목의 PDF가 있으면 덮어씁니다")
    parser.add_argument("--include-source", action="store_true", help="PDF 첫 줄에 원본 URL을 표시합니다")
    parser.add_argument("--timeout", type=int, default=30, help="웹페이지/이미지 요청 시간 제한(초)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = webpage_to_pdf(
            args.url,
            args.output_dir,
            overwrite=args.overwrite,
            include_source=args.include_source,
            timeout=args.timeout,
        )
    except WebPdfError as exc:
        print(f"PDF 생성 실패: {exc}", file=sys.stderr)
        return 1
    print(f"PDF 생성 완료: {result.output}")
    print(f"본문 {result.text_blocks}개, 이미지 {result.image_blocks}개")
    if result.skipped_images:
        print(f"가져오지 못한 이미지 {len(result.skipped_images)}개", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
