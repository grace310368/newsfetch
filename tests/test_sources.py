import pytest

from newsfetch import sources
from newsfetch.http import BLOCKED, HTTP_ERROR, FetchError
from newsfetch.sources import bing, ctee

BING_RSS = """<?xml version="1.0" encoding="utf-8"?><rss><channel>
<item><title>亞資中心新進度</title>
<link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;aid=&amp;url=https%3a%2f%2fwww.ctee.com.tw%2fnews%2f20260918700118-439901&amp;c=1</link></item>
<item><title>別家</title>
<link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;url=https%3a%2f%2fmoney.udn.com%2fmoney%2fstory%2f5613%2f9761877</link></item>
<item><title>頻道頁</title>
<link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fwww.ctee.com.tw%2flivenews%2ffinance</link></item>
</channel></rss>"""


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get_text(self, url):
        self.calls.append(url)
        for key, resp in self.responses.items():
            if key in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(url)


@pytest.fixture(autouse=True)
def reset():
    sources.reset_run_state()
    yield
    sources.reset_run_state()


def test_bing_extracts_publisher_article_urls():
    s = FakeSession({"bing.com": BING_RSS})
    assert bing.news_links("亞資中心", "工商時報", "ctee.com.tw", s, 10) == [
        "https://www.ctee.com.tw/news/20260918700118-439901"]
    assert "%E4%BA%9E%E8%B3%87%E4%B8%AD%E5%BF%83%20%E5%B7%A5%E5%95%86%E6%99%82%E5%A0%B1" in s.calls[0]
    assert "mkt=zh-TW" in s.calls[0]


def test_ctee_falls_back_to_bing_and_skips_blocked_search():
    s = FakeSession({"ctee.com.tw/search": FetchError(BLOCKED, "HTTP 403"), "bing.com": BING_RSS})
    notes = []
    assert ctee.search("亞資中心", s, notes=notes) == ["https://www.ctee.com.tw/news/20260918700118-439901"]
    assert any("由「Bing 新聞搜尋」取得連結" in n for n in notes)
    assert len(sources.RUN_NOTES) == 1
    # 第二個關鍵字：站內搜尋已判定被擋，不再請求
    ctee.search("TISA", s)
    assert sum("ctee.com.tw/search" in c for c in s.calls) == 1


def test_all_strategies_fail_raises():
    s = FakeSession({"ctee.com.tw/search": FetchError(BLOCKED, "HTTP 403"),
                     "bing.com": FetchError(HTTP_ERROR, "HTTP 500")})
    with pytest.raises(FetchError):
        ctee.search("亞資中心", s)
