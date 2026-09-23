"""SQLite 連線與 schema。

schema 依需求文件設計；額外增加的欄位／表：
- pending_review.published_time / articles.published_time：HH:MM，前端清單顯示時間用（可為 null）
- pending_review.delete_reason：整篇刪除時的原因，供之後檢討規則庫
- crawl_seen：已看過但未收錄的 URL（例如發布日期超出回溯範圍、抓取失敗次數），
  避免每天重複抓取同一批舊文章
- topic_review_mode：各議題為人工審核或自動分類模式（本階段預設全部人工審核）
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_review (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    published_date TEXT,
    published_time TEXT,
    summary TEXT,
    raw_keywords TEXT,
    origin TEXT NOT NULL,             -- 'crawler' 或 'manual'
    status TEXT DEFAULT 'pending',    -- pending / approved / edited / deleted
    delete_reason TEXT,
    reviewed_at TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS pending_review_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pending_review_id INTEGER NOT NULL REFERENCES pending_review(id),
    suggested_topic TEXT NOT NULL,
    suggested_subcategory TEXT,
    suggested_reason TEXT
);

CREATE TABLE IF NOT EXISTS pending_review_final (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pending_review_id INTEGER NOT NULL REFERENCES pending_review(id),
    final_topic TEXT NOT NULL,
    final_subcategory TEXT,
    was_suggested INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS articles (
    url TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    published_date TEXT NOT NULL,
    published_time TEXT,
    summary TEXT,
    raw_keywords TEXT,
    origin TEXT NOT NULL,
    crawled_at TEXT
);

CREATE TABLE IF NOT EXISTS article_classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_url TEXT NOT NULL REFERENCES articles(url),
    topic TEXT NOT NULL,
    subcategory TEXT,
    UNIQUE(article_url, topic)
);

CREATE TABLE IF NOT EXISTS topic_review_mode (
    topic TEXT PRIMARY KEY,
    mode TEXT DEFAULT 'manual_review'   -- 'manual_review' 或 'auto'
);

CREATE TABLE IF NOT EXISTS crawl_seen (
    url TEXT PRIMARY KEY,
    status TEXT NOT NULL,             -- 'out_of_window' / 'fetch_failed'
    attempts INTEGER DEFAULT 0,
    last_error TEXT,
    first_seen TEXT,
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS monthly_reports (
    topic TEXT NOT NULL,
    year_month TEXT NOT NULL,
    policy_report TEXT,
    product_report TEXT,
    peer_report TEXT,
    article_count INTEGER,
    generated_at TEXT,
    PRIMARY KEY (topic, year_month)
);

CREATE TABLE IF NOT EXISTS trend_reports (
    topic TEXT NOT NULL,
    period_label TEXT NOT NULL,
    primary_subcategory TEXT,
    stage_description TEXT NOT NULL,
    generated_at TEXT,
    sort_order INTEGER
);

CREATE INDEX IF NOT EXISTS idx_suggestions_pr ON pending_review_suggestions(pending_review_id);
CREATE INDEX IF NOT EXISTS idx_final_pr ON pending_review_final(pending_review_id);
CREATE INDEX IF NOT EXISTS idx_class_topic ON article_classifications(topic);
CREATE INDEX IF NOT EXISTS idx_articles_date ON articles(published_date);
"""


def now_iso() -> str:
    return datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%dT%H:%M:%S%z")


def today() -> str:
    return datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT OR IGNORE INTO topic_review_mode(topic, mode) VALUES (?, 'manual_review')",
        [(t,) for t in config.TOPIC_NAMES],
    )
    conn.commit()


def url_exists(conn: sqlite3.Connection, url: str) -> bool:
    """URL 是否已存在於正式表或待審核表（含已刪除，避免重複收錄雜訊）。"""
    row = conn.execute(
        "SELECT 1 FROM articles WHERE url = ? UNION SELECT 1 FROM pending_review WHERE url = ?",
        (url, url),
    ).fetchone()
    return row is not None


def topic_modes(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["topic"]: r["mode"] for r in conn.execute("SELECT topic, mode FROM topic_review_mode")}
