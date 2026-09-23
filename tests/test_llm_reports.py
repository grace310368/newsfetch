from newsfetch import llm_reports, review
from newsfetch.classifier import Suggestion
from newsfetch.extract import Article
from newsfetch.review import FinalItem


def add(conn, n, date, topic, sub):
    a = Article(url=f"https://www.ctee.com.tw/news/{n}-1", title=f"新聞{n}", source="工商時報",
                published_date=date, summary=f"摘要{n}", classify_text="")
    review.ingest(conn, a, [Suggestion(topic, sub, "")], "crawler")
    pid = conn.execute("SELECT id FROM pending_review WHERE url = ?", (a.url,)).fetchone()["id"]
    review.finalize(conn, pid, [FinalItem(topic, sub, True)])


def test_monthly_prompt_groups_by_topic_subcategory(conn, monkeypatch):
    add(conn, 1, "2026-08-03", "信任金融", "政策與法規")
    add(conn, 2, "2026-08-20", "信任金融", "同業動態")
    add(conn, 3, "2026-09-01", "信任金融", "同業動態")
    dry = llm_reports.generate_monthly(conn, "信任金融", "2026-08", dry_run=True)
    assert dry["article_count"] == 2
    assert "【商品與業務】\n（本月無新聞）" in dry["prompt"]
    assert "新聞3" not in dry["prompt"]
    assert llm_reports.generate_monthly(conn, "三軌金融", "2026-08") is None

    monkeypatch.setattr(llm_reports, "_parse", lambda fmt, prompt: llm_reports.MonthlyReport(
        policy_report="政策段", product_report="模型亂寫的", peer_report="同業段"))
    out = llm_reports.generate_monthly(conn, "信任金融", "2026-08")
    assert out["product_report"] == llm_reports.NO_NEWS
    row = conn.execute("SELECT * FROM monthly_reports").fetchone()
    assert (row["policy_report"], row["article_count"]) == ("政策段", 2)


def test_trend_requires_reports_and_saves_order(conn, monkeypatch):
    assert llm_reports.generate_trend(conn, "信任金融") is None
    for ym in ("2026-07", "2026-08"):
        conn.execute("INSERT INTO monthly_reports VALUES ('信任金融', ?, 'a', 'b', 'c', 3, 'x')", (ym,))
    monkeypatch.setattr(llm_reports, "_parse", lambda fmt, prompt: llm_reports.TrendReport(stages=[
        llm_reports.TrendStage(period_label="2026 Q3 前期", primary_subcategory="政策與法規", stage_description="舊"),
        llm_reports.TrendStage(period_label="2026 Q3", primary_subcategory="亂填", stage_description="新"),
    ]))
    stages = llm_reports.generate_trend(conn, "信任金融")
    assert stages[1]["subcategory"] is None
    rows = conn.execute("SELECT * FROM trend_reports ORDER BY sort_order DESC").fetchall()
    assert rows[0]["stage_description"] == "新"


def test_previous_month():
    from datetime import date
    assert llm_reports.previous_month(date(2026, 1, 5)) == "2025-12"
    assert llm_reports.previous_month(date(2026, 9, 1)) == "2026-08"
