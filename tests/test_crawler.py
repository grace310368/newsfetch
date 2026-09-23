from newsfetch import crawler
from newsfetch.extract import Article
from newsfetch.http import BLOCKED, HTTP_ERROR, FetchError
from newsfetch.run_report import render_markdown


def art(url, date, title="金管會核准TISA新制"):
    return Article(url=url, title=title, source="工商時報", published_date=date, published_time="08:00",
                   summary="摘要內容", classify_text="摘要內容", keywords=[])


def test_run_crawl_flow(conn, monkeypatch):
    pages = {
        "https://www.ctee.com.tw/news/1-1": art("https://www.ctee.com.tw/news/1-1", "2026-09-15"),
        "https://www.ctee.com.tw/news/2-1": art("https://www.ctee.com.tw/news/2-1", "2026-01-01"),
        "https://www.ctee.com.tw/news/3-1": art("https://www.ctee.com.tw/news/3-1", "2026-09-14", "台股收盤"),
    }

    def fake_fetch(url, session=None):
        if url.endswith("/4-1"):
            raise FetchError(HTTP_ERROR, "HTTP 500", url)
        return pages[url]

    monkeypatch.setattr(crawler, "fetch_article", fake_fetch)

    def ctee_search(term, session):
        return list(pages) + ["https://www.ctee.com.tw/news/4-1"]

    def udn_search(term, session, notes=None):
        notes.append("udn 搜尋 API失敗")
        raise FetchError(BLOCKED, "HTTP 403")

    result = crawler.run_crawl(conn, "2026-09-15", session=object(), terms=["TISA"],
                               sources=[("工商時報", ctee_search), ("經濟日報", udn_search)])
    assert [a["url"] for a in result.new_pending] == [
        "https://www.ctee.com.tw/news/1-1", "https://www.ctee.com.tw/news/3-1"]
    assert result.new_pending[1]["suggestions"] == []  # 規則未命中也進待審核
    assert result.out_of_window == 1
    cats = {f["category"] for f in result.failures}
    assert cats == {HTTP_ERROR, BLOCKED}
    assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0

    md = render_markdown(result)
    assert "反爬蟲擋下" in md and "規則未命中文章（1）" in md

    # 第二次執行：已收錄的算重複、超出範圍的不再抓
    result2 = crawler.run_crawl(conn, "2026-09-15", session=object(), terms=["TISA"],
                                sources=[("工商時報", ctee_search)])
    assert result2.duplicates == 2
    assert result2.skipped_seen == 1
    assert result2.new_pending == []


def test_consecutive_failures_stop_source(conn):
    calls = []

    def blocked(term, session):
        calls.append(term)
        raise FetchError(BLOCKED, "HTTP 403")

    result = crawler.run_crawl(conn, "2026-09-15", session=object(), terms=[f"t{i}" for i in range(10)],
                               sources=[("工商時報", blocked)])
    assert len(calls) == 5
    assert any("連續 5 個" in n for n in result.needs_attention)
