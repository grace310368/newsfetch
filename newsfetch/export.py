"""把資料庫輸出成前端讀取的靜態 JSON（docs/data/*.json）。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import config, keyword_learning, stats
from .db import now_iso, today, topic_modes


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def articles(conn: sqlite3.Connection) -> list[dict]:
    classes: dict[str, list[dict]] = {}
    order = {t: i for i, t in enumerate(config.TOPIC_NAMES)}
    for r in conn.execute("SELECT article_url, topic, subcategory FROM article_classifications"):
        classes.setdefault(r["article_url"], []).append({"topic": r["topic"], "subcategory": r["subcategory"]})
    out = []
    for r in conn.execute(
        "SELECT * FROM articles ORDER BY published_date DESC, COALESCE(published_time, '') DESC, title"
    ):
        cls = sorted(classes.get(r["url"], []), key=lambda c: order.get(c["topic"], 99))
        out.append({
            "url": r["url"],
            "title": r["title"],
            "source": r["source"],
            "date": r["published_date"],
            "time": r["published_time"],
            "summary": r["summary"],
            "keywords": r["raw_keywords"],
            "origin": r["origin"],
            "classifications": cls,
        })
    return out


def pending(conn: sqlite3.Connection) -> list[dict]:
    sugg: dict[int, list[dict]] = {}
    for r in conn.execute("SELECT * FROM pending_review_suggestions ORDER BY id"):
        sugg.setdefault(r["pending_review_id"], []).append({
            "topic": r["suggested_topic"],
            "subcategory": r["suggested_subcategory"],
            "reason": r["suggested_reason"],
        })
    out = []
    for r in conn.execute(
        "SELECT * FROM pending_review WHERE status = 'pending' ORDER BY created_at DESC, id DESC"
    ):
        out.append({
            "id": r["id"],
            "url": r["url"],
            "title": r["title"],
            "source": r["source"],
            "date": r["published_date"],
            "time": r["published_time"],
            "summary": r["summary"],
            "keywords": r["raw_keywords"],
            "origin": r["origin"],
            "created_at": r["created_at"],
            "suggestions": sugg.get(r["id"], []),
        })
    return out


def reports(conn: sqlite3.Connection) -> dict:
    monthly: dict[str, dict] = {}
    for r in conn.execute("SELECT * FROM monthly_reports ORDER BY year_month"):
        monthly.setdefault(r["topic"], {})[r["year_month"]] = {
            "政策與法規": r["policy_report"],
            "商品與業務": r["product_report"],
            "同業動態": r["peer_report"],
            "article_count": r["article_count"],
            "generated_at": r["generated_at"],
        }
    trend: dict[str, list] = {}
    for r in conn.execute("SELECT * FROM trend_reports ORDER BY topic, sort_order DESC"):
        trend.setdefault(r["topic"], []).append({
            "period": r["period_label"],
            "subcategory": r["primary_subcategory"],
            "description": r["stage_description"],
            "generated_at": r["generated_at"],
        })
    return {"monthly": monthly, "trend": trend}


def export_all(conn: sqlite3.Connection, out_dir: Path | None = None) -> Path:
    out_dir = Path(out_dir or config.EXPORT_DIR)
    _write(out_dir / "articles.json", articles(conn))
    _write(out_dir / "pending.json", pending(conn))
    _write(out_dir / "reports.json", reports(conn))
    _write(out_dir / "stats.json", {
        "accuracy": stats.accuracy(conn),
        "coverage": stats.coverage(conn),
    })
    _write(out_dir / "keywords.json", keyword_learning.analyze(conn))
    _write(out_dir / "meta.json", {
        "generated_at": now_iso(),
        "today": today(),
        "topics": config.TOPIC_NAMES,
        "subcategories": config.SUBCATEGORY_NAMES,
        "topic_modes": topic_modes(conn),
    })
    return out_dir
