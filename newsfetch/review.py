"""待審核流程：寫入待審核佇列、審核完成寫入正式表、整篇刪除、手動新增。

本地審核伺服器（serve.py）與 GitHub Actions 批次套用（apply_review.py）都呼叫這裡的函式，
兩邊行為完全一致。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import config
from .classifier import Suggestion, classify, classify_for_topics
from .db import now_iso, topic_modes, url_exists
from .extract import Article, fetch_article, normalize_url
from .http import FetchError, PoliteSession


class ReviewError(Exception):
    """審核操作不合法（參數錯誤、狀態不符等），訊息會直接顯示給使用者。"""


@dataclass
class FinalItem:
    topic: str
    subcategory: str | None
    was_suggested: bool


# ---------------------------------------------------------------------------
# 寫入
# ---------------------------------------------------------------------------

def _insert_article(conn: sqlite3.Connection, art: dict, origin: str, items: list[tuple[str, str | None]]) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO articles(url, title, source, published_date, published_time,
               summary, raw_keywords, origin, crawled_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (art["url"], art["title"], art["source"], art["published_date"], art.get("published_time"),
         art.get("summary"), art.get("raw_keywords"), origin, art.get("created_at") or now_iso()),
    )
    conn.executemany(
        "INSERT OR REPLACE INTO article_classifications(article_url, topic, subcategory) VALUES (?,?,?)",
        [(art["url"], t, s) for t, s in items],
    )


def ingest(conn: sqlite3.Connection, article: Article, suggestions: list[Suggestion], origin: str) -> str:
    """把新文章寫入待審核佇列。

    若所有建議議題都已切換為自動模式（且每組都有子分類），直接寫入正式表，回傳 'auto'；
    否則寫入 pending_review，回傳 'pending'。重複 URL 回傳 'duplicate'。
    """
    if url_exists(conn, article.url):
        return "duplicate"
    modes = topic_modes(conn)
    auto = (
        origin == "crawler"
        and suggestions
        and all(modes.get(s.topic) == "auto" and s.subcategory for s in suggestions)
    )
    created = now_iso()
    if auto:
        _insert_article(conn, {
            "url": article.url, "title": article.title, "source": article.source,
            "published_date": article.published_date, "published_time": article.published_time,
            "summary": article.summary, "raw_keywords": article.raw_keywords, "created_at": created,
        }, origin, [(s.topic, s.subcategory) for s in suggestions])
        conn.commit()
        return "auto"

    cur = conn.execute(
        """INSERT INTO pending_review(url, title, source, published_date, published_time, summary,
               raw_keywords, origin, status, created_at)
           VALUES (?,?,?,?,?,?,?,?, 'pending', ?)""",
        (article.url, article.title, article.source, article.published_date, article.published_time,
         article.summary, article.raw_keywords, origin, created),
    )
    pid = cur.lastrowid
    conn.executemany(
        """INSERT INTO pending_review_suggestions(pending_review_id, suggested_topic,
               suggested_subcategory, suggested_reason) VALUES (?,?,?,?)""",
        [(pid, s.topic, s.subcategory, s.reason) for s in suggestions],
    )
    conn.commit()
    return "pending"


def ingest_crawled(conn: sqlite3.Connection, article: Article) -> tuple[str, list[Suggestion]]:
    suggestions = classify(article.title, article.classify_text, article.keywords)
    return ingest(conn, article, suggestions, "crawler"), suggestions


# ---------------------------------------------------------------------------
# 審核
# ---------------------------------------------------------------------------

def _get_pending(conn: sqlite3.Connection, pending_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM pending_review WHERE id = ?", (pending_id,)).fetchone()
    if not row:
        raise ReviewError(f"找不到待審核文章 #{pending_id}")
    if row["status"] != "pending":
        raise ReviewError(f"文章 #{pending_id} 已審核過（{row['status']}）")
    return row


def _validate_items(items: list[FinalItem]) -> None:
    if not items:
        raise ReviewError("至少需要核准一個議題；若整篇不相關請改用刪除")
    seen = set()
    for it in items:
        if it.topic not in config.TOPICS:
            raise ReviewError(f"未知的議題：{it.topic}")
        if it.subcategory not in config.SUBCATEGORIES:
            raise ReviewError(f"「{it.topic}」尚未指定子分類")
        if it.topic in seen:
            raise ReviewError(f"議題重複：{it.topic}")
        seen.add(it.topic)


def finalize(conn: sqlite3.Connection, pending_id: int, items: list[FinalItem]) -> str:
    """完成一篇文章的審核：寫入 pending_review_final，並正式收錄到 articles / article_classifications。

    was_suggested 以伺服器端比對規則建議為準（核准且子分類未修改才算 1），
    不信任前端傳來的值，確保準確率統計一致。
    被移除的建議不寫入任何資料（由 suggestions 與 final 的差異推導）。
    """
    row = _get_pending(conn, pending_id)
    _validate_items(items)
    suggested = {
        r["suggested_topic"]: r["suggested_subcategory"]
        for r in conn.execute(
            "SELECT suggested_topic, suggested_subcategory FROM pending_review_suggestions WHERE pending_review_id = ?",
            (pending_id,),
        )
    }
    # 手動新增文章的議題是使用者自己指定的，不代表規則判斷，只有子分類部分由規則建議
    finals = []
    for it in items:
        was = int(it.topic in suggested and suggested[it.topic] == it.subcategory)
        finals.append((pending_id, it.topic, it.subcategory, was))
    if not row["published_date"]:
        raise ReviewError("此文章缺少發布日期，無法收錄")

    conn.executemany(
        """INSERT INTO pending_review_final(pending_review_id, final_topic, final_subcategory, was_suggested)
           VALUES (?,?,?,?)""",
        finals,
    )
    status = "approved" if all(f[3] for f in finals) and len(finals) == len(suggested) else "edited"
    reviewed = now_iso()
    conn.execute("UPDATE pending_review SET status = ?, reviewed_at = ? WHERE id = ?", (status, reviewed, pending_id))
    _insert_article(conn, dict(row), row["origin"], [(f[1], f[2]) for f in finals])
    conn.commit()
    return status


def delete(conn: sqlite3.Connection, pending_id: int, reason: str = "") -> None:
    """整篇刪除（軟刪除）：不寫入正式表，保留紀錄與原因供檢討規則。"""
    _get_pending(conn, pending_id)
    conn.execute(
        "UPDATE pending_review SET status = 'deleted', delete_reason = ?, reviewed_at = ? WHERE id = ?",
        (reason or None, now_iso(), pending_id),
    )
    conn.commit()


def manual_add(conn: sqlite3.Connection, url: str, topics: list[str],
               session: PoliteSession | None = None) -> dict:
    """手動新增新聞：抓取（複用爬蟲解析函式）→ 寫入待審核佇列（origin='manual'）。"""
    url = (url or "").strip()
    if not url:
        raise ReviewError("請貼上新聞連結")
    topics = [t for t in dict.fromkeys(topics or [])]
    if not topics:
        raise ReviewError("請至少選擇一個議題")
    bad = [t for t in topics if t not in config.TOPICS]
    if bad:
        raise ReviewError(f"未知的議題：{'、'.join(bad)}")
    norm = normalize_url(url)
    if url_exists(conn, norm):
        raise ReviewError("這則新聞已經收錄")
    try:
        article = fetch_article(norm, session)
    except FetchError as e:
        raise ReviewError(f"無法抓取這則新聞：{e}。請確認連結是否正確。") from e
    if url_exists(conn, article.url):
        raise ReviewError("這則新聞已經收錄")
    suggestions = classify_for_topics(topics, article.title, article.classify_text)
    ingest(conn, article, suggestions, "manual")
    pid = conn.execute("SELECT id FROM pending_review WHERE url = ?", (article.url,)).fetchone()["id"]
    return {"id": pid, "title": article.title, "source": article.source, "published_date": article.published_date}


# ---------------------------------------------------------------------------
# 批次操作（前端送出的審核結果）
# ---------------------------------------------------------------------------

def apply_op(conn: sqlite3.Connection, op: dict, session: PoliteSession | None = None) -> dict:
    """套用單一操作。op 格式：
    {"type": "finalize", "id": 12, "items": [{"topic": "...", "subcategory": "..."}]}
    {"type": "delete", "id": 12, "reason": "..."}
    {"type": "manual_add", "url": "https://...", "topics": ["..."]}
    """
    kind = op.get("type")
    if kind == "finalize":
        items = [FinalItem(i.get("topic"), i.get("subcategory"), bool(i.get("was_suggested"))) for i in op.get("items", [])]
        return {"status": finalize(conn, int(op["id"]), items)}
    if kind == "delete":
        delete(conn, int(op["id"]), op.get("reason", ""))
        return {"status": "deleted"}
    if kind == "manual_add":
        return {"status": "added", **manual_add(conn, op.get("url", ""), op.get("topics", []), session)}
    raise ReviewError(f"未知的操作類型：{kind}")


def apply_ops(conn: sqlite3.Connection, ops: list[dict]) -> list[dict]:
    session = PoliteSession()
    results = []
    for op in ops:
        try:
            results.append({"op": op, "ok": True, **apply_op(conn, op, session)})
        except (ReviewError, KeyError, ValueError, TypeError) as e:
            conn.rollback()
            results.append({"op": op, "ok": False, "error": str(e)})
    return results
