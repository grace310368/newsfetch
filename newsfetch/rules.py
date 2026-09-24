"""實際生效的關鍵字規則＝ config.py 基礎詞庫 ＋ keyword_rules 已採用 − keyword_rules 已停用。

基礎詞庫仍在 config.py 維護；從審核資料學到的關鍵字存在資料庫，不需要改程式碼。
"""
from __future__ import annotations

import sqlite3

from . import config
from .db import now_iso


def _rules(conn: sqlite3.Connection, kind: str, status: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT term, topic FROM keyword_rules WHERE kind = ? AND status = ? ORDER BY id", (kind, status)
    ).fetchall()


def active_topics(conn: sqlite3.Connection) -> dict[str, list[str]]:
    disabled = {(r["topic"], r["term"]) for r in _rules(conn, "topic", "disabled")}
    merged = {t: [w for w in terms if (t, w) not in disabled] for t, terms in config.TOPICS.items()}
    for r in _rules(conn, "topic", "active"):
        if r["topic"] in merged and r["term"] not in merged[r["topic"]]:
            merged[r["topic"]].append(r["term"])
    return merged


def active_seed_terms(conn: sqlite3.Connection) -> list[str]:
    disabled = {r["term"] for r in _rules(conn, "seed", "disabled")}
    terms = [t for t in config.all_seed_terms() if t not in disabled]
    for r in _rules(conn, "seed", "active"):
        if r["term"] not in terms:
            terms.append(r["term"])
    return terms


def learned_terms(conn: sqlite3.Connection) -> set[tuple[str, str, str]]:
    """所有已處理過（採用／忽略／停用）的 (term, kind, topic)，不再重複建議。"""
    return {(r["term"], r["kind"], r["topic"]) for r in conn.execute("SELECT term, kind, topic FROM keyword_rules")}


def set_rule(conn: sqlite3.Connection, term: str, kind: str, topic: str, status: str, evidence: str = "") -> None:
    from .review import ReviewError

    term = (term or "").strip()
    topic = topic or ""
    if not term:
        raise ReviewError("關鍵字不可為空")
    if kind not in ("seed", "topic"):
        raise ReviewError(f"未知的關鍵字類型：{kind}")
    if kind == "topic" and topic not in config.TOPICS:
        raise ReviewError(f"未知的議題：{topic}")
    if status not in ("active", "ignored", "disabled"):
        raise ReviewError(f"未知的狀態：{status}")
    now = now_iso()
    conn.execute(
        """INSERT INTO keyword_rules(term, kind, topic, status, evidence, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(term, kind, topic) DO UPDATE SET status = excluded.status,
               evidence = COALESCE(excluded.evidence, keyword_rules.evidence), updated_at = excluded.updated_at""",
        (term, kind, topic if kind == "topic" else "", status, evidence or None, now, now),
    )
    conn.commit()
