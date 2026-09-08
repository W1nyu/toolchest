import puppeteer from "@cloudflare/puppeteer";

function corsHeaders(origin, environment) {
  const allowedOrigin = environment.ALLOWED_ORIGIN || "https://w1nyu.github.io";
  return {
    "Access-Control-Allow-Origin": origin === allowedOrigin ? origin : allowedOrigin,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

function json(data, status, headers) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...headers },
  });
}

function isPublicWebUrl(value) {
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase();
    const privateIpv4 = /^(127|10|0)\.|^192\.168\.|^172\.(1[6-9]|2\d|3[0-1])\./;
    const privateIpv6 = host === "::1" || host.startsWith("fc") || host.startsWith("fd");
    return ["http:", "https:"].includes(url.protocol)
      && !["localhost", "localhost.localdomain"].includes(host)
      && !host.endsWith(".local")
      && !privateIpv4.test(host)
      && !privateIpv6;
  } catch {
    return false;
  }
}

function pageExtractor(sourceUrl) {
  const blockTags = new Set(["P", "DIV", "SECTION", "ARTICLE", "BLOCKQUOTE", "PRE", "LI", "H1", "H2", "H3", "H4", "H5", "H6"]);
  const noise = "script, style, noscript, template, svg, form, button, input, iframe, canvas, nav, aside, footer, header, [role='navigation'], [role='dialog'], .comment, .comments, .reply, .replies, .related, .recommend, .advertisement, .ad-banner, .adsbygoogle, [id*='advert'], [class*='advert']";
  const url = new URL(sourceUrl);
  const host = url.hostname.toLowerCase();
  document.querySelectorAll(noise).forEach((node) => node.remove());

  const selectFirst = (selectors) => selectors.map((selector) => document.querySelector(selector)).find((node) => node && (node.textContent.trim() || node.querySelector("img")));
  const siteRoot = host.endsWith("dcinside.com")
    ? selectFirst(["div.write_div", "#dgn_220", "div.view_content_wrap"])
    : host.endsWith("tistory.com")
      ? selectFirst(["div.blogview_content", "div.editor_ke", "div.tt_article_useless_p_margin", "#article-body"])
      : host.endsWith("catch.co.kr")
        ? selectFirst(["div.news_detail_cont", "#contents2 div.news_detail_cont"])
        : null;

  const score = (element) => {
    const text = element.innerText.trim();
    if (text.length < 20 && !element.querySelector("img")) return -10000;
    const className = String(element.className || "").toLowerCase();
    const penalty = /menu|nav|comment|reply|sidebar|footer/.test(className) ? 800 : 0;
    return text.length + element.querySelectorAll("img").length * 450 + element.querySelectorAll("p, li, blockquote, pre").length * 90 - element.querySelectorAll("a").length * 12 - penalty;
  };
  const genericRoot = selectFirst(["article", "[itemprop='articleBody']", ".article-body", ".article_body", ".article-content", ".entry-content", ".post-content", ".post-body", ".content-body", "main"])
    || [...document.querySelectorAll("article, main, section, div")].sort((a, b) => score(b) - score(a))[0];
  const root = siteRoot || genericRoot;
  if (!root) return { title: document.title, blocks: [] };

  const blocks = [];
  let buffer = "";
  const flushText = () => {
    buffer.split(/\n+/).map((line) => line.replace(/[\t \f\v]+/g, " ").trim()).filter(Boolean)
      .forEach((text) => blocks.push({ type: "text", text }));
    buffer = "";
  };
  const imageSource = (element) => {
    for (const attribute of ["data-original", "data-src", "data-lazy-src", "data-url", "src"]) {
      const value = element.getAttribute(attribute);
      if (value && !value.startsWith("javascript:")) return new URL(value, sourceUrl).href;
    }
    const srcset = element.getAttribute("srcset");
    return srcset ? new URL(srcset.split(",").at(-1).trim().split(/\s+/)[0], sourceUrl).href : null;
  };
  const walk = (node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      buffer += node.textContent;
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const element = node;
    if (["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "SOURCE", "VIDEO", "AUDIO"].includes(element.tagName)) return;
    if (element.tagName === "BR") {
      buffer += "\n";
      return;
    }
    if (element.tagName === "IMG") {
      flushText();
      const imageUrl = imageSource(element);
      if (imageUrl) blocks.push({ type: "image", url: imageUrl, alt: element.alt || "" });
      return;
    }
    const isBlock = blockTags.has(element.tagName);
    if (isBlock) buffer += "\n";
    element.childNodes.forEach(walk);
    if (isBlock) buffer += "\n";
  };
  walk(root);
  flushText();
  return { title: document.title || "web-article", blocks };
}

export default {
  async fetch(request, environment) {
    const origin = request.headers.get("Origin") || "";
    const headers = corsHeaders(origin, environment);
    if (request.method === "OPTIONS") return new Response(null, { headers });
    if (request.method !== "POST" || new URL(request.url).pathname !== "/article") {
      return json({ error: "Not found" }, 404, headers);
    }

    let target;
    try {
      target = (await request.json()).url;
    } catch {
      return json({ error: "A JSON body with a url is required." }, 400, headers);
    }
    if (typeof target !== "string" || !isPublicWebUrl(target)) {
      return json({ error: "A public http(s) URL is required." }, 400, headers);
    }

    let browser;
    try {
      browser = await puppeteer.launch(environment.BROWSER);
      const page = await browser.newPage();
      await page.setUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36");
      await page.goto(target, { waitUntil: "domcontentloaded", timeout: 25000 });
      await page.waitForTimeout(1800);
      const article = await page.evaluate(pageExtractor, target);
      if (!article.blocks.some((block) => block.type === "text")) {
        return json({ error: "본문을 찾지 못했습니다. 로그인 또는 접근 제한 페이지일 수 있습니다." }, 422, headers);
      }
      return json(article, 200, headers);
    } catch (error) {
      console.log("Article conversion failed", error);
      return json({ error: "페이지를 불러오지 못했습니다. 잠시 뒤 다시 시도하세요." }, 502, headers);
    } finally {
      if (browser) await browser.close();
    }
  },
};
