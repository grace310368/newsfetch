"""各新聞來源的搜尋模組：給定關鍵字，回傳候選文章 URL 清單（單篇解析一律交給 extract.fetch_article）。"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..extract import is_article_url, normalize_url

HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
ABS_URL_RE = re.compile(r"https?:\\?/\\?/[^\s\"'<>]+")


def extract_article_links(html: str, base: str, limit: int | None = None,
                          containers: tuple[str, ...] = ()) -> list[str]:
    """從 HTML／JSON 文字中找出符合文章 URL 格式的連結。

    containers 為搜尋結果區塊的 CSS selector：有任何一個命中時，只取這些區塊內的連結，
    避免抓到頁首跑馬燈、側欄熱門新聞；都沒命中（網站改版）則退回掃描整頁。
    """
    if containers:
        soup = BeautifulSoup(html, "html.parser")
        blocks = [el for sel in containers for el in soup.select(sel)]
        if blocks:
            html = "".join(str(b) for b in blocks)
    found: dict[str, None] = {}
    candidates = [urljoin(base, h) for h in HREF_RE.findall(html)]
    candidates += [u.replace("\\/", "/") for u in ABS_URL_RE.findall(html)]
    for raw in candidates:
        try:
            if not is_article_url(raw):
                continue
        except ValueError:
            continue
        found.setdefault(normalize_url(raw), None)
        if limit and len(found) >= limit:
            break
    return list(found)
