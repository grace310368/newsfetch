"""工商時報：站內搜尋頁 → Bing 新聞 RSS。

站內搜尋、RSS、sitemap 會被 Cloudflare 擋（403），單篇文章頁可讀。
"""
from __future__ import annotations

from urllib.parse import quote

from .. import config
from ..http import PoliteSession
from . import bing, extract_article_links, run_strategies

NAME = config.SOURCE_CTEE
SEARCH_URL = "https://www.ctee.com.tw/search/{kw}"
# 搜尋結果區塊（網站改版找不到時會退回掃描整頁，執行報告中若出現大量無關文章請調整這裡）
SEARCH_CONTAINERS = (".newslist", ".news-list", ".search-result", ".search-list", "#search-result")


def search_page(term: str, session: PoliteSession, limit: int) -> list[str]:
    url = SEARCH_URL.format(kw=quote(term))
    return extract_article_links(session.get_text(url), url, limit, SEARCH_CONTAINERS)


def search_bing(term: str, session: PoliteSession, limit: int) -> list[str]:
    return bing.news_links(term, NAME, "ctee.com.tw", session, limit)


STRATEGIES = [("工商時報搜尋頁", search_page), ("Bing 新聞搜尋", search_bing)]


def search(term: str, session: PoliteSession, limit: int = config.MAX_RESULTS_PER_TERM,
           notes: list[str] | None = None) -> list[str]:
    return run_strategies(term, session, limit, STRATEGIES, notes, NAME)
