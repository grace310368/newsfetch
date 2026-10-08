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


# 本次執行中需要寫進執行報告「需要人工檢視」的訊息（例如站內搜尋被擋、已改用備援）
RUN_NOTES: list[str] = []
# 本次執行中已判定被擋的策略，後續關鍵字直接略過，避免浪費請求
_blocked_strategies: set[str] = set()


def reset_run_state() -> None:
    RUN_NOTES.clear()
    _blocked_strategies.clear()


def run_strategies(term: str, session, limit: int, strategies, notes: list[str] | None = None,
                   source_name: str = "") -> list[str]:
    """依序嘗試各策略，第一個取得連結的策略即回傳。

    - 策略被反爬蟲擋下（BLOCKED）後，本次執行不再嘗試該策略，並記錄一次到 RUN_NOTES
    - 每個策略都出錯時才丟出最後一個錯誤；有策略正常執行但沒結果則回傳空清單
    """
    from ..http import BLOCKED, FetchError

    last_error: FetchError | None = None
    any_ok = False
    for label, fn in strategies:
        key = f"{source_name}:{label}"
        if key in _blocked_strategies:
            continue
        try:
            links = fn(term, session, limit)
        except FetchError as e:
            last_error = e
            if notes is not None:
                notes.append(f"{label}失敗：{e}")
            if e.category == BLOCKED:
                _blocked_strategies.add(key)
                RUN_NOTES.append(f"{source_name}「{label}」被反爬蟲擋下（{e}），本次執行改用其他備援策略")
            continue
        any_ok = True
        if links:
            if notes is not None and label != strategies[0][0]:
                notes.append(f"由「{label}」取得連結")
            return links
        if notes is not None:
            notes.append(f"{label}無結果")
    if last_error and not any_ok:
        raise last_error
    return []
