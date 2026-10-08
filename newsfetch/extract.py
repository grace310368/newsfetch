"""單篇文章解析（每日爬蟲與手動新增共用同一套函式）。

解析策略以結構化資料為主（JSON-LD、og/article meta、meta keywords），
內文段落只做為摘要的退路，降低網站改版時整個解析失效的機率。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from . import config
from .http import EMPTY_FIELDS, NOT_SUPPORTED, PARSE_ERROR, FetchError, PoliteSession

CTEE_ARTICLE_RE = re.compile(r"^/news/\d+-\d+/?$")
UDN_ARTICLE_RES = {
    "money.udn.com": re.compile(r"^/money/story/\d+/\d+/?$"),
    "udn.com": re.compile(r"^/news/story/\d+/\d+/?$"),
}

TITLE_SUFFIX_RE = re.compile(r"\s*[|｜\-－—]\s*(工商時報|經濟日報|聯合新聞網|udn.*|中時新聞網|ctee.*)\s*$", re.I)


@dataclass
class Article:
    url: str
    title: str
    source: str
    published_date: str | None          # YYYY-MM-DD
    published_time: str | None = None   # HH:MM
    summary: str = ""                   # 儲存用（150 字）
    classify_text: str = ""             # 分類用（前 200 字）
    keywords: list[str] = field(default_factory=list)

    @property
    def raw_keywords(self) -> str:
        return ",".join(self.keywords)


def normalize_url(url: str) -> str:
    """去除 query/fragment 與結尾斜線，統一 https，確保去重一致。"""
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if host.startswith("m."):
        host = host[2:]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, "", ""))


def source_for_url(url: str) -> str | None:
    host = urlsplit(url).netloc.lower()
    if host.endswith("ctee.com.tw"):
        return config.SOURCE_CTEE
    if host.endswith("udn.com"):
        return config.SOURCE_UDN
    return None


def is_article_url(url: str) -> bool:
    parts = urlsplit(normalize_url(url))
    host = parts.netloc
    if host.endswith("ctee.com.tw"):
        return bool(CTEE_ARTICLE_RE.match(parts.path))
    for h, pat in UDN_ARTICLE_RES.items():
        if host == h or host == "www." + h:
            return bool(pat.match(parts.path))
    return False


def _meta(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name}) \
            or soup.find("meta", attrs={"itemprop": name})
        if tag and tag.get("content", "").strip():
            return tag["content"].strip()
    return ""


def _json_ld(soup: BeautifulSoup) -> list[dict]:
    items: list[dict] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                if "@graph" in d and isinstance(d["@graph"], list):
                    stack.extend(d["@graph"])
                items.append(d)
            elif isinstance(d, list):
                stack.extend(d)
    return [d for d in items if str(d.get("@type", "")).lower().endswith(("newsarticle", "article", "reportagenewsarticle"))] or items


def parse_datetime(value: str) -> tuple[str, str | None] | None:
    """解析各種日期字串，回傳台灣時間的 (YYYY-MM-DD, HH:MM|None)。"""
    if not value:
        return None
    value = value.strip()
    tz = ZoneInfo(config.TIMEZONE)
    iso = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo:
            dt = dt.astimezone(tz)
        has_time = "T" in value or " " in value or ":" in value
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M") if has_time else None
    except ValueError:
        pass
    m = re.search(r"(20\d{2})[./\-年](\d{1,2})[./\-月](\d{1,2})日?(?:\s*(\d{1,2}):(\d{2}))?", value)
    if m:
        y, mo, d, hh, mm = m.groups()
        date = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        return date, f"{int(hh):02d}:{mm}" if hh else None
    return None


def _clean(text: str) -> str:
    # 保留全形空白（中文標題常用來分隔），只收斂一般空白
    return re.sub(r"[^\S\u3000]+", " ", text or "").strip(" \u3000")


def _body_text(soup: BeautifulSoup) -> str:
    container = None
    for selector in ("article", "[itemprop=articleBody]", ".article-content__editor",
                     "#article_body", ".article-body", ".entry-content", "main"):
        container = soup.select_one(selector)
        if container:
            break
    paras = [_clean(p.get_text(" ")) for p in (container or soup).find_all("p")]
    paras = [p for p in paras if len(p) >= 20 and "版權" not in p and "請繼續往下閱讀" not in p]
    return "".join(paras)


def parse_article_html(html: str, url: str) -> Article:
    url = normalize_url(url)
    source = source_for_url(url)
    if not source:
        raise FetchError(NOT_SUPPORTED, "僅支援工商時報與經濟日報的文章連結", url)
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:  # noqa: BLE001 - bs4 很少丟例外，但仍歸類為解析失敗
        raise FetchError(PARSE_ERROR, f"HTML 無法解析：{e}", url) from e

    ld = _json_ld(soup)
    ld0 = ld[0] if ld else {}

    title = _meta(soup, "og:title", "twitter:title") or _clean(str(ld0.get("headline", "")))
    if not title:
        h1 = soup.find("h1")
        title = _clean(h1.get_text(" ")) if h1 else _clean(soup.title.get_text() if soup.title else "")
    title = _clean(title)
    if " | " in title:  # udn：「標題 | 頻道 | 分類 | 經濟日報」
        title = title.split(" | ")[0]
    title = TITLE_SUFFIX_RE.sub("", title).strip()

    date_candidates = [
        _meta(soup, "article:published_time", "pubdate", "publishdate", "date.available",
              "datePublished", "og:article:published_time", "date"),
        str(ld0.get("datePublished", "")),
    ]
    time_tag = soup.find("time")
    if time_tag:
        date_candidates += [time_tag.get("datetime", ""), time_tag.get_text(" ")]
    published = next((p for p in map(parse_datetime, date_candidates) if p), None)
    if not published:
        # 最後退路：頁面文字中第一個「YYYY-MM-DD HH:MM」樣式
        published = parse_datetime(_clean(soup.get_text(" "))[:5000])

    kw_raw = _meta(soup, "keywords", "news_keywords", "meta-keywords")
    ld_kw = ld0.get("keywords")
    if not kw_raw and ld_kw:
        kw_raw = ",".join(ld_kw) if isinstance(ld_kw, list) else str(ld_kw)
    tags = [t.get("content", "") for t in soup.find_all("meta", attrs={"property": "article:tag"})]
    keywords = []
    for k in re.split(r"[,，、]", kw_raw) + tags:
        k = k.strip()
        if k and k not in keywords:
            keywords.append(k)

    desc = _meta(soup, "og:description", "description", "twitter:description") \
        or _clean(str(ld0.get("description", "")))
    body = _body_text(soup)
    lead = desc
    if len(desc) < config.SUMMARY_CLASSIFY_LEN and body:
        lead = body if not desc or body.startswith(desc[:20]) else f"{desc} {body}"
    lead = _clean(lead)

    article = Article(
        url=url,
        title=title,
        source=source,
        published_date=published[0] if published else None,
        published_time=published[1] if published else None,
        summary=lead[: config.SUMMARY_STORE_LEN],
        classify_text=lead[: config.SUMMARY_CLASSIFY_LEN],
        keywords=keywords,
    )
    missing = [name for name, v in (("標題", article.title), ("發布日期", article.published_date)) if not v]
    if missing:
        raise FetchError(EMPTY_FIELDS, f"解析後缺少欄位：{'、'.join(missing)}", url)
    return article


def fetch_article(url: str, session: PoliteSession | None = None) -> Article:
    """抓取並解析單篇文章。每日爬蟲與手動新增都呼叫這個函式。"""
    norm = normalize_url(url)
    if not source_for_url(norm):
        raise FetchError(NOT_SUPPORTED, "僅支援工商時報（ctee.com.tw）與經濟日報（udn.com）的文章連結", url)
    session = session or PoliteSession(delay_range=(0, 0))
    html = session.get_text(norm)
    return parse_article_html(html, norm)
