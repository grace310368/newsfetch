import json

import pytest

from newsfetch import export, review, stats
from newsfetch.classifier import Suggestion
from newsfetch.extract import Article
from newsfetch.review import FinalItem, ReviewError


def make_article(n=1, date="2026-09-15"):
    return Article(url=f"https://www.ctee.com.tw/news/{n}-1", title=f"標題{n}", source="工商時報",
                   published_date=date, published_time="09:00", summary="摘要", classify_text="摘要",
                   keywords=["TISA"])


def ingest(conn, n, suggestions, origin="crawler"):
    assert review.ingest(conn, make_article(n), suggestions, origin) == "pending"
    return conn.execute("SELECT id FROM pending_review WHERE url = ?", (make_article(n).url,)).fetchone()["id"]


S_ASIA = Suggestion("亞洲資產管理中心", "政策與法規", "命中「TISA」")
S_CAP = Suggestion("國際級資本市場", None, "命中「ETF」")
S_TRUST = Suggestion("信任金融", "同業動態", "命中「公司治理」")


def test_ingest_goes_to_pending_not_articles(conn):
    ingest(conn, 1, [S_ASIA])
    assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM pending_review_suggestions").fetchone()[0] == 1
    assert review.ingest(conn, make_article(1), [S_ASIA], "crawler") == "duplicate"


def test_finalize_accuracy_is_per_topic_pair(conn):
    pid = ingest(conn, 1, [S_ASIA, S_CAP, S_TRUST])
    # 亞資：原樣核准（正確）；資本市場：補上子分類（錯誤）；信任金融：移除；補充全齡金融（錯誤）
    status = review.finalize(conn, pid, [
        FinalItem("亞洲資產管理中心", "政策與法規", True),
        FinalItem("國際級資本市場", "同業動態", True),   # 前端說 True 也不採信
        FinalItem("全齡金融", "商品與業務", False),
    ])
    assert status == "edited"
    finals = {r["final_topic"]: r["was_suggested"] for r in conn.execute("SELECT * FROM pending_review_final")}
    assert finals == {"亞洲資產管理中心": 1, "國際級資本市場": 0, "全齡金融": 0}
    cls = {r["topic"]: r["subcategory"] for r in conn.execute("SELECT * FROM article_classifications")}
    assert cls == {"亞洲資產管理中心": "政策與法規", "國際級資本市場": "同業動態", "全齡金融": "商品與業務"}

    acc = {t["topic"]: t for t in stats.accuracy(conn)["topics"]}
    assert acc["亞洲資產管理中心"]["rate"] == 1.0
    assert acc["國際級資本市場"]["rate"] == 0.0
    assert acc["信任金融"]["rate"] is None
    assert stats.accuracy(conn)["removed_suggestions"] == 1


def test_finalize_all_suggested_is_approved(conn):
    pid = ingest(conn, 1, [S_ASIA])
    assert review.finalize(conn, pid, [FinalItem("亞洲資產管理中心", "政策與法規", True)]) == "approved"
    with pytest.raises(ReviewError):
        review.finalize(conn, pid, [FinalItem("亞洲資產管理中心", "政策與法規", True)])


def test_finalize_validation(conn):
    pid = ingest(conn, 1, [S_CAP])
    with pytest.raises(ReviewError, match="子分類"):
        review.finalize(conn, pid, [FinalItem("國際級資本市場", None, True)])
    with pytest.raises(ReviewError, match="至少"):
        review.finalize(conn, pid, [])
    with pytest.raises(ReviewError, match="未知"):
        review.finalize(conn, pid, [FinalItem("不存在", "政策與法規", False)])


def test_delete_soft_and_not_in_accuracy(conn):
    pid = ingest(conn, 1, [S_ASIA])
    review.delete(conn, pid, "關鍵字誤觸")
    row = conn.execute("SELECT * FROM pending_review WHERE id = ?", (pid,)).fetchone()
    assert row["status"] == "deleted" and row["delete_reason"] == "關鍵字誤觸"
    assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0
    acc = stats.accuracy(conn)
    assert acc["deleted_articles"] == 1
    assert all(t["total"] == 0 for t in acc["topics"])


def test_coverage_counts_articles(conn):
    ingest(conn, 1, [S_ASIA])
    ingest(conn, 2, [S_ASIA, S_CAP])
    pid3 = ingest(conn, 3, [S_ASIA], origin="manual")
    review.finalize(conn, pid3, [FinalItem("亞洲資產管理中心", "政策與法規", True)])
    pid4 = ingest(conn, 4, [])
    review.delete(conn, pid4)
    cov = stats.coverage(conn)
    assert (cov["crawler"], cov["manual"]) == (2, 1)
    assert cov["rate"] == round(2 / 3, 4)


def test_auto_mode_skips_review(conn):
    conn.execute("UPDATE topic_review_mode SET mode = 'auto' WHERE topic = '亞洲資產管理中心'")
    assert review.ingest(conn, make_article(1), [S_ASIA], "crawler") == "auto"
    assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1
    # 同時有人工審核模式的議題 → 仍需審核
    assert review.ingest(conn, make_article(2), [S_ASIA, S_TRUST], "crawler") == "pending"
    # 規則未命中 → 仍需審核
    assert review.ingest(conn, make_article(3), [], "crawler") == "pending"


def test_manual_add_uses_fetcher_and_detects_duplicates(conn, monkeypatch):
    monkeypatch.setattr(review, "fetch_article", lambda url, session=None: make_article(9))
    res = review.manual_add(conn, "https://www.ctee.com.tw/news/9-1?utm=x", ["全齡金融", "信任金融"])
    row = conn.execute("SELECT * FROM pending_review WHERE id = ?", (res["id"],)).fetchone()
    assert row["origin"] == "manual"
    topics = [r["suggested_topic"] for r in conn.execute(
        "SELECT * FROM pending_review_suggestions WHERE pending_review_id = ?", (res["id"],))]
    assert topics == ["全齡金融", "信任金融"]
    with pytest.raises(ReviewError, match="已經收錄"):
        review.manual_add(conn, "https://www.ctee.com.tw/news/9-1", ["全齡金融"])
    with pytest.raises(ReviewError, match="議題"):
        review.manual_add(conn, "https://www.ctee.com.tw/news/10-1", [])


def test_manual_add_fetch_failure_not_written(conn, monkeypatch):
    from newsfetch.http import HTTP_ERROR, FetchError

    def boom(url, session=None):
        raise FetchError(HTTP_ERROR, "HTTP 404", url)

    monkeypatch.setattr(review, "fetch_article", boom)
    with pytest.raises(ReviewError, match="無法抓取"):
        review.manual_add(conn, "https://www.ctee.com.tw/news/404-1", ["三軌金融"])
    assert conn.execute("SELECT COUNT(*) FROM pending_review").fetchone()[0] == 0


def test_apply_ops_and_export(conn, tmp_path):
    p1 = ingest(conn, 1, [S_ASIA, S_CAP])
    p2 = ingest(conn, 2, [S_TRUST])
    results = review.apply_ops(conn, [
        {"type": "finalize", "id": p1, "items": [{"topic": "亞洲資產管理中心", "subcategory": "政策與法規"},
                                                 {"topic": "國際級資本市場", "subcategory": "同業動態"}]},
        {"type": "delete", "id": p2, "reason": "雜訊"},
        {"type": "delete", "id": 999},
    ])
    assert [r["ok"] for r in results] == [True, True, False]

    out = export.export_all(conn, tmp_path)
    arts = json.loads((out / "articles.json").read_text(encoding="utf-8"))
    assert len(arts) == 1
    assert [c["topic"] for c in arts[0]["classifications"]] == ["亞洲資產管理中心", "國際級資本市場"]
    assert json.loads((out / "pending.json").read_text(encoding="utf-8")) == []
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["topics"][0] == "亞洲資產管理中心"
