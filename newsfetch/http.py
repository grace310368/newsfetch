"""禮貌爬取用的 HTTP 客戶端：固定 User-Agent、每次請求間隔 1–2 秒、錯誤原因分類。"""
from __future__ import annotations

import random
import time

import requests

from . import config

# 失敗原因分類（寫入執行報告）
HTTP_ERROR = "HTTP 錯誤"
BLOCKED = "反爬蟲擋下"
TIMEOUT = "逾時"
NETWORK = "連線失敗"
PARSE_ERROR = "頁面結構改變／解析失敗"
EMPTY_FIELDS = "欄位為空（需要人工檢視）"
NOT_SUPPORTED = "非支援網站連結"

BLOCK_MARKERS = ("captcha", "cf-challenge", "Access Denied", "驗證您是真人", "Just a moment")


class FetchError(Exception):
    def __init__(self, category: str, message: str, url: str = ""):
        super().__init__(message)
        self.category = category
        self.url = url

    def __str__(self) -> str:
        return f"[{self.category}] {super().__str__()}"


class PoliteSession:
    def __init__(self, delay_range: tuple[float, float] = config.REQUEST_DELAY_RANGE):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.6",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        })
        self.delay_range = delay_range
        self._last = 0.0

    def _wait(self) -> None:
        lo, hi = self.delay_range
        if hi <= 0:
            return
        gap = random.uniform(lo, hi)
        elapsed = time.monotonic() - self._last
        if elapsed < gap:
            time.sleep(gap - elapsed)

    def get(self, url: str, **kwargs) -> requests.Response:
        self._wait()
        try:
            resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT, **kwargs)
        except requests.Timeout as e:
            raise FetchError(TIMEOUT, str(e), url) from e
        except requests.RequestException as e:
            raise FetchError(NETWORK, str(e), url) from e
        finally:
            self._last = time.monotonic()

        if resp.status_code in (403, 429, 503) or (
            resp.ok and any(m in resp.text[:5000] for m in BLOCK_MARKERS)
        ):
            raise FetchError(BLOCKED, f"HTTP {resp.status_code}", url)
        if not resp.ok:
            raise FetchError(HTTP_ERROR, f"HTTP {resp.status_code}", url)
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding or "utf-8"
        return resp

    def get_text(self, url: str, **kwargs) -> str:
        return self.get(url, **kwargs).text
