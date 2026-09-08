const form = document.querySelector("#converter-form");
const urlInput = document.querySelector("#article-url");
const extractButton = document.querySelector("#extract-button");
const status = document.querySelector("#status");
const previewSection = document.querySelector("#preview-section");
const articleOutput = document.querySelector("#article-output");
const printButton = document.querySelector("#print-button");

const apiBaseUrl = String(window.ARTICLE_CONVERTER_API_URL || "").replace(/\/$/, "");

function setStatus(message, state = "idle") {
  status.textContent = message;
  status.dataset.state = state;
}

function safeHttpUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function createTextBlock(text) {
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  return paragraph;
}

function createImageBlock(block) {
  const figure = document.createElement("figure");
  const image = document.createElement("img");
  image.src = block.url;
  image.alt = block.alt || "본문 이미지";
  image.loading = "lazy";
  image.referrerPolicy = "no-referrer";
  figure.append(image);
  if (block.alt) {
    const caption = document.createElement("figcaption");
    caption.textContent = block.alt;
    figure.append(caption);
  }
  return figure;
}

function renderArticle(article) {
  articleOutput.replaceChildren();
  for (const block of article.blocks) {
    if (block.type === "text" && block.text) articleOutput.append(createTextBlock(block.text));
    if (block.type === "image" && safeHttpUrl(block.url || "")) articleOutput.append(createImageBlock(block));
  }
}

function apiEndpoint() {
  if (!safeHttpUrl(apiBaseUrl)) return null;
  return `${apiBaseUrl}/article`;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const sourceUrl = safeHttpUrl(urlInput.value.trim());
  if (!sourceUrl) {
    setStatus("http:// 또는 https://로 시작하는 올바른 주소를 입력하세요.", "error");
    urlInput.focus();
    return;
  }
  const endpoint = apiEndpoint();
  if (!endpoint) {
    setStatus("변환 서버가 아직 연결되지 않았습니다. 사이트 관리자에게 Worker 주소 설정을 요청하세요.", "error");
    return;
  }

  extractButton.disabled = true;
  previewSection.hidden = true;
  setStatus("본문과 본문 이미지를 준비하고 있습니다…");
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: sourceUrl }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `server returned ${response.status}`);
    if (!Array.isArray(payload.blocks) || !payload.blocks.some((block) => block.type === "text")) {
      throw new Error("article content was not found");
    }

    renderArticle(payload);
    document.title = `${payload.title || new URL(sourceUrl).hostname} | Article Converter`;
    previewSection.hidden = false;
    setStatus("본문을 준비했습니다. 미리보기를 확인한 뒤 PDF로 저장하세요.", "success");
    previewSection.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    console.error(error);
    setStatus("본문을 불러오지 못했습니다. 공개 페이지인지와 주소를 확인한 뒤 다시 시도하세요.", "error");
  } finally {
    extractButton.disabled = false;
  }
});

printButton.addEventListener("click", () => window.print());
