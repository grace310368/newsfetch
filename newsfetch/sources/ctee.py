"""工商時報（ctee.com.tw）。

實測（2026-09）：站內搜尋頁、頻道列表、RSS、sitemap 都會被 Cloudflare WAF 以 HTTP 403 擋下，
但單篇文章頁可以正常讀取。因此依序嘗試：
1. 站內搜尋頁 https://www.ctee.com.tw/search/{關鍵字}（若執行環境的 IP 未被擋，這是最完整的來源）
2. Bing 新聞 RSS（查詢「{關鍵字} 工商時報」，取出工商時報原始網址）
取得網址後，單篇解析一律交給 extract.fetch_article。
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
