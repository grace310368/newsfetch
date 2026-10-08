"""經濟日報（money.udn.com / udn.com）。

udn 反爬蟲較嚴，依序嘗試多種策略，任一策略取得連結即停止：
1. 經濟日報搜尋頁 HTML（只取搜尋結果區塊）
2. udn 站內搜尋 JSON API（聯合新聞網，結果含 udn.com/news/story）
3. 經濟日報 RSS（抓最新文章，再以關鍵字比對標題／描述）
4. Bing 新聞 RSS（查詢「{關鍵字} 經濟日報」）
每一種策略的失敗原因都會回報給執行報告，方便之後調整。
"""
from __future__ import annotations

import re
from urllib.parse import quote
from xml.etree import ElementTree

from .. import config
from ..http import PARSE_ERROR, FetchError, PoliteSession
from . import bing, extract_article_links, run_strategies

NAME = config.SOURCE_UDN

API_URL = "https://udn.com/api/more?page=1&id=search:{kw}&channelId=2&type=searchword"
SEARCH_URL = "https://money.udn.com/search/result/1001/{kw}"
SEARCH_CONTAINERS = (".story__content", ".story-list__news", ".search-result", "#search_content")
RSS_URLS = [
    "https://money.udn.com/rssfeed/news/1001/5588?ch=money",   # 金融要聞
    "https://money.udn.com/rssfeed/news/1001/5591?ch=money",   # 國際／財經焦點
    "https://money.udn.com/rssfeed/news/1001/12017?ch=money",  # 金融
]

_rss_cache: dict[str, list[tuple[str, str]]] = {}


def _rss_items(session: PoliteSession) -> list[tuple[str, str]]:
    """回傳 (url, 標題+描述) 清單；同一次執行只抓一次。"""
    if "items" in _rss_cache:
        return _rss_cache["items"]
    items: list[tuple[str, str]] = []
    errors: list[str] = []
    for feed in RSS_URLS:
        try:
            xml = session.get_text(feed)
            root = ElementTree.fromstring(xml.encode("utf-8"))
        except FetchError as e:
            errors.append(str(e))
            continue
        except ElementTree.ParseError as e:
            errors.append(f"[{PARSE_ERROR}] RSS 無法解析：{e}")
            continue
        for item in root.iter("item"):
            link = (item.findtext("link") or "").strip()
            text = (item.findtext("title") or "") + " " + (item.findtext("description") or "")
            items.append((link, re.sub(r"<[^>]+>", "", text)))
    if not items and errors:
        raise FetchError(PARSE_ERROR, "；".join(errors))
    _rss_cache["items"] = items
    return items


def search_api(term: str, session: PoliteSession, limit: int) -> list[str]:
    url = API_URL.format(kw=quote(term))
    return extract_article_links(session.get_text(url), url, limit)


def search_page(term: str, session: PoliteSession, limit: int) -> list[str]:
    url = SEARCH_URL.format(kw=quote(term))
    return extract_article_links(session.get_text(url), url, limit, SEARCH_CONTAINERS)


def search_rss(term: str, session: PoliteSession, limit: int) -> list[str]:
    from ..classifier import find_terms

    links = [link for link, text in _rss_items(session) if find_terms(text, [term])]
    return extract_article_links(" ".join(f'href="{u}"' for u in links), "https://money.udn.com/", limit)


def search_bing(term: str, session: PoliteSession, limit: int) -> list[str]:
    return bing.news_links(term, NAME, "udn.com", session, limit)


STRATEGIES = [("經濟日報搜尋頁", search_page), ("udn 搜尋 API", search_api), ("經濟日報 RSS", search_rss),
              ("Bing 新聞搜尋", search_bing)]


def search(term: str, session: PoliteSession, limit: int = config.MAX_RESULTS_PER_TERM,
           notes: list[str] | None = None) -> list[str]:
    return run_strategies(term, session, limit, STRATEGIES, notes, NAME)


def reset_cache() -> None:
    _rss_cache.clear()
