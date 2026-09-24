"""Bing 新聞 RSS：當報社站內搜尋被擋時，改由搜尋引擎取得文章連結。

查詢「{關鍵字} {報社名稱}」並指定台灣市場（mkt=zh-TW），再只保留符合該報社文章網址格式的連結。
（實測 `site:` 語法搭配中文關鍵字時 Bing 會回傳 0 筆，所以改用報社名稱當關鍵字。）
Bing RSS 的 <link> 是轉址連結，原始網址放在 url 參數中。
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
