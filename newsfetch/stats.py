"""統計：分類準確率（單位＝議題＋子分類組合）與爬蟲涵蓋率（單位＝文章），兩者分開計算。"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config


def _since(days: int = config.STATS_WINDOW_DAYS) -> str:
    return (datetime.now(ZoneInfo(config.TIMEZONE)) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")


def accuracy(conn: sqlite3.Connection, days: int = config.STATS_WINDOW_DAYS) -> dict:
    since = _since(days)
    rows = conn.execute(
        """SELECT f.final_topic AS topic, COUNT(*) AS total, SUM(f.was_suggested) AS correct
           FROM pending_review_final f JOIN pending_review p ON p.id = f.pending_review_id
           WHERE p.reviewed_at >= ?
           GROUP BY f.final_topic""",
        (since,),
    ).fetchall()
    by_topic = {r["topic"]: r for r in rows}
    topics = []
    for t in config.TOPIC_NAMES:
        r = by_topic.get(t)
        total = r["total"] if r else 0
        correct = (r["correct"] or 0) if r else 0
        topics.append({
            "topic": t,
            "total": total,
            "correct": correct,
            "rate": round(correct / total, 4) if total else None,
        })

    # 規則誤觸參考：被移除的建議組合數、整篇刪除數（刪除不計入準確率）
    removed = conn.execute(
        """SELECT COUNT(*) FROM pending_review_suggestions s JOIN pending_review p ON p.id = s.pending_review_id
           WHERE p.status IN ('approved', 'edited') AND p.reviewed_at >= ?
             AND NOT EXISTS (SELECT 1 FROM pending_review_final f
                             WHERE f.pending_review_id = s.pending_review_id AND f.final_topic = s.suggested_topic)""",
        (since,),
    ).fetchone()[0]
    deleted = conn.execute(
        "SELECT COUNT(*) FROM pending_review WHERE status = 'deleted' AND reviewed_at >= ?", (since,)
    ).fetchone()[0]
    return {"window_days": days, "topics": topics, "removed_suggestions": removed, "deleted_articles": deleted}


def coverage(conn: sqlite3.Connection, days: int = config.STATS_WINDOW_DAYS) -> dict:
    """近 N 天：自動爬取篇數 ÷（自動爬取＋手動新增）。整篇刪除的雜訊不計入。"""
    since = _since(days)
    rows = conn.execute(
        """SELECT origin, COUNT(*) AS n FROM (
               SELECT url, origin FROM pending_review
                WHERE created_at >= ? AND status != 'deleted'
               UNION
               SELECT url, origin FROM articles WHERE crawled_at >= ?
           ) GROUP BY origin""",
        (since, since),
    ).fetchall()
    counts = {r["origin"]: r["n"] for r in rows}
    crawler, manual = counts.get("crawler", 0), counts.get("manual", 0)
    total = crawler + manual
    return {
        "window_days": days,
        "crawler": crawler,
        "manual": manual,
        "rate": round(crawler / total, 4) if total else None,
    }
