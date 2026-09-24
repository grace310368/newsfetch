"""每日爬蟲流程：關鍵字搜尋 → 去重 → 單篇抓取 → 日期過濾 → 規則建議 → 寫入待審核佇列。"""
from __future__ import annotations

import inspect
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import config, review, rules
from .db import now_iso, url_exists
from .extract import fetch_article
from .http import EMPTY_FIELDS, FetchError, PoliteSession
from . import sources as source_modules
from .sources import ctee, udn


@dataclass
class TermResult:
    source: str
    term: str
    found: int = 0
    error: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    run_date: str
    started_at: str
    finished_at: str = ""
    terms: list[TermResult] = field(default_factory=list)
    new_pending: list[dict] = field(default_factory=list)
    auto_added: list[dict] = field(default_factory=list)
    duplicates: int = 0
    out_of_window: int = 0
    skipped_seen: int = 0
    failures: list[dict] = field(default_factory=list)  # {category, url|term, source, message}
    needs_attention: list[str] = field(default_factory=list)

    def failures_by_category(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = defaultdict(list)
        for f in self.failures:
            out[f["category"]].append(f)
        return dict(out)


SOURCES = [(ctee.NAME, ctee.search), (udn.NAME, udn.search)]


def _seen_skip(conn: sqlite3.Connection, url: str) -> bool:
    row = conn.execute("SELECT status, attempts FROM crawl_seen WHERE url = ?", (url,)).fetchone()
    if not row:
        return False
    return row["status"] == "out_of_window" or row["attempts"] >= config.MAX_FETCH_ATTEMPTS


def _mark_seen(conn: sqlite3.Connection, url: str, status: str, error: str | None = None) -> None:
    now = now_iso()
    conn.execute(
        """INSERT INTO crawl_seen(url, status, attempts, last_error, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(url) DO UPDATE SET status = excluded.status, last_error = excluded.last_error,
               attempts = crawl_seen.attempts + excluded.attempts, last_seen = excluded.last_seen""",
        (url, status, 1 if status == "fetch_failed" else 0, error, now, now),
    )
    conn.commit()


def run_crawl(conn: sqlite3.Connection, run_date: str, session: PoliteSession | None = None,
              terms: list[str] | None = None, sources=None) -> RunResult:
    session = session or PoliteSession()
    terms = terms or rules.active_seed_terms(conn)
    topic_rules = rules.active_topics(conn)
    sources = sources or SOURCES
    result = RunResult(run_date=run_date, started_at=now_iso())
    earliest = (date.fromisoformat(run_date) - timedelta(days=config.LOOKBACK_DAYS)).isoformat()
    udn.reset_cache()
    source_modules.reset_run_state()

    # 1) 搜尋：收集候選連結（記錄每個連結是被哪個關鍵字找到的）
    candidates: dict[str, tuple[str, str]] = {}
    for source_name, search in sources:
        consecutive_blocked = 0
        for term in terms:
            tr = TermResult(source_name, term)
            try:
                if "notes" in inspect.signature(search).parameters:
                    links = search(term, session, notes=tr.notes)
                else:
                    links = search(term, session)
                tr.found = len(links)
                consecutive_blocked = 0
                for link in links:
                    candidates.setdefault(link, (source_name, term))
            except FetchError as e:
                tr.error = str(e)
                result.failures.append({"category": e.category, "source": source_name,
                                        "target": f"關鍵字「{term}」", "message": str(e)})
                consecutive_blocked += 1
            result.terms.append(tr)
            if consecutive_blocked >= 5:
                result.needs_attention.append(
                    f"{source_name}連續 5 個關鍵字搜尋失敗，已停止此來源後續搜尋（可能被擋或網站改版）")
                break
        ok = [t for t in result.terms if t.source == source_name and not t.error]
        if ok and all(t.found == 0 for t in ok):
            result.needs_attention.append(
                f"{source_name}所有關鍵字搜尋皆無任何文章連結，搜尋頁結構可能已改變")

    result.needs_attention.extend(dict.fromkeys(source_modules.RUN_NOTES))

    # 2) 單篇抓取與分類
    for url, (source_name, term) in candidates.items():
        if url_exists(conn, url):
            result.duplicates += 1
            continue
        if _seen_skip(conn, url):
            result.skipped_seen += 1
            continue
        try:
            article = fetch_article(url, session)
        except FetchError as e:
            _mark_seen(conn, url, "fetch_failed", str(e))
            result.failures.append({"category": e.category, "source": source_name,
                                    "target": url, "message": str(e)})
            continue
        if article.published_date < earliest or article.published_date > run_date:
            _mark_seen(conn, url, "out_of_window")
            result.out_of_window += 1
            continue
        if not article.summary:
            result.failures.append({"category": EMPTY_FIELDS, "source": source_name,
                                    "target": url, "message": "摘要為空，已收錄但請檢視解析邏輯"})
        status, suggestions = review.ingest_crawled(conn, article, term, topic_rules)
        conn.execute("DELETE FROM crawl_seen WHERE url = ?", (url,))
        conn.commit()
        entry = {
            "url": article.url, "title": article.title, "source": article.source,
            "date": article.published_date, "term": term,
            "suggestions": [s.as_dict() for s in suggestions],
        }
        if status == "auto":
            result.auto_added.append(entry)
        elif status == "pending":
            result.new_pending.append(entry)
        else:
            result.duplicates += 1

    parse_fail = [f for f in result.failures if f["category"] == EMPTY_FIELDS]
    fetched = len(result.new_pending) + len(result.auto_added) + result.out_of_window
    if parse_fail and len(parse_fail) >= max(3, fetched):
        result.needs_attention.append("多篇文章解析後欄位為空，單篇解析邏輯可能已失效")
    result.finished_at = now_iso()
    return result
