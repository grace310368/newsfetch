"""工商時報：使用站內搜尋頁 https://www.ctee.com.tw/search/{關鍵字}。"""
from __future__ import annotations

from urllib.parse import quote

from .. import config
from ..http import PoliteSession
from . import extract_article_links

NAME = config.SOURCE_CTEE
SEARCH_URL = "https://www.ctee.com.tw/search/{kw}"
# 搜尋結果區塊（網站改版找不到時會退回掃描整頁，執行報告中若出現大量無關文章請調整這裡）
SEARCH_CONTAINERS = (".newslist", ".news-list", ".search-result", ".search-list", "#search-result")


def search(term: str, session: PoliteSession, limit: int = config.MAX_RESULTS_PER_TERM) -> list[str]:
    url = SEARCH_URL.format(kw=quote(term))
    html = session.get_text(url)
    return extract_article_links(html, url, limit, SEARCH_CONTAINERS)
