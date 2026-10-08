"""Bing 新聞 RSS 備援：查詢「{關鍵字} {報社名稱}」（mkt=zh-TW），只保留該報社的文章網址。

`site:` 搭配中文關鍵字會回傳 0 筆，因此改用報社名稱；原始網址在連結的 url 參數中。
"""
from __future__ import annotations

from urllib.parse import parse_qs, quote, urlsplit
from xml.etree import ElementTree

from ..http import PARSE_ERROR, FetchError, PoliteSession
from . import extract_article_links

RSS_URL = "https://www.bing.com/news/search?q={q}&format=rss&mkt=zh-TW"


def _real_url(link: str) -> str:
    return parse_qs(urlsplit(link).query).get("url", [link])[0]


def news_links(term: str, publisher: str, host_suffix: str, session: PoliteSession, limit: int) -> list[str]:
    url = RSS_URL.format(q=quote(f"{term} {publisher}"))
    xml = session.get_text(url)
    try:
        root = ElementTree.fromstring(xml.encode("utf-8"))
    except ElementTree.ParseError as e:
        raise FetchError(PARSE_ERROR, f"Bing RSS 無法解析：{e}", url) from e
    links = [_real_url(item.findtext("link") or "") for item in root.iter("item")]
    links = [u for u in links if urlsplit(u).netloc.lower().endswith(host_suffix)]
    return extract_article_links(" ".join(f'href="{u}"' for u in links), f"https://{host_suffix}/", limit)
