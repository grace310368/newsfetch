"""規則式分類引擎（純字串比對，不呼叫 LLM）。

產出「議題＋子分類＋命中依據」建議清單，一篇文章可命中多個議題；
每個議題各自判斷一次子分類：
1. 先看該議題關鍵字在標題／摘要中出現的那一句（以。！？；分句），
   比對子分類關鍵字；
2. 上下文判斷不出時，退回全文通用判斷（標題 > 前 200 字摘要）；
3. 同時命中多個子分類時取優先序最高者（政策與法規 > 商品與業務 > 同業動態），
   都沒命中則為 None，交由人工指定。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from . import config

SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;\n]")

FIELD_LABELS = {"keywords": "標籤", "title": "標題", "summary": "摘要"}


@dataclass
class Suggestion:
    topic: str
    subcategory: str | None
    reason: str
    matched_terms: list[str] = field(default_factory=list)  # 命中的議題規則關鍵字（評估誤觸率用）

    def as_dict(self) -> dict:
        return {"topic": self.topic, "subcategory": self.subcategory, "reason": self.reason}


@lru_cache(maxsize=None)
def _pattern(term: str) -> re.Pattern:
    """英數詞（OBU、ETF、MOU…）不分大小寫且需完整詞比對，避免誤中其他英文字串。"""
    escaped = re.escape(term)
    if re.fullmatch(r"[A-Za-z0-9]+", term):
        return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)
    return re.compile(escaped, re.IGNORECASE)


def find_terms(text: str, terms: list[str]) -> list[str]:
    if not text:
        return []
    return [t for t in terms if _pattern(t).search(text)]


def _pick_subcategory(text: str) -> tuple[str | None, list[str]]:
    for sub, terms in config.SUBCATEGORIES.items():
        hits = find_terms(text, terms)
        if hits:
            return sub, hits
    return None, []


def _context_snippets(text: str, terms: list[str]) -> list[str]:
    """回傳包含議題關鍵字的句子（議題關鍵字命中的上下文）。"""
    return [s for s in SENTENCE_SPLIT_RE.split(text) if s and find_terms(s, terms)]


def general_subcategory(title: str, summary: str) -> tuple[str | None, list[str]]:
    """整篇文章的通用子分類判斷：標題優先，其次前 200 字摘要。"""
    for text in (title, summary[: config.SUMMARY_CLASSIFY_LEN]):
        sub, hits = _pick_subcategory(text)
        if sub:
            return sub, hits
    return None, []


def subcategory_for_topic(topic: str, title: str, summary: str,
                          topic_terms: list[str] | None = None) -> tuple[str | None, list[str]]:
    summary = summary[: config.SUMMARY_CLASSIFY_LEN]
    terms = topic_terms if topic_terms is not None else config.TOPICS.get(topic, [])
    for text in (title, summary):
        snippets = _context_snippets(text, terms)
        if snippets:
            sub, hits = _pick_subcategory("　".join(snippets))
            if sub:
                return sub, hits
    return general_subcategory(title, summary)


def classify(title: str, summary: str = "", keywords: str | list[str] = "",
             topics: dict[str, list[str]] | None = None) -> list[Suggestion]:
    """回傳所有命中議題的建議（依 TOPICS 順序）。比對優先序：meta-keywords > 標題 > 摘要。

    topics 為實際生效的規則（rules.active_topics），未提供時使用 config.TOPICS 基礎詞庫。
    """
    topics = topics if topics is not None else config.TOPICS
    if isinstance(keywords, list):
        keywords = ",".join(keywords)
    summary = (summary or "")[: config.SUMMARY_CLASSIFY_LEN]
    fields = {"keywords": keywords or "", "title": title or "", "summary": summary}

    results = []
    for topic, terms in topics.items():
        hit_field, hits = None, []
        for field in ("keywords", "title", "summary"):
            hits = find_terms(fields[field], terms)
            if hits:
                hit_field = field
                break
        if not hit_field:
            continue
        sub, sub_hits = subcategory_for_topic(topic, fields["title"], summary, terms)
        reason = f"命中關鍵字{''.join(f'「{h}」' for h in hits)}（{FIELD_LABELS[hit_field]}）"
        if sub:
            reason += f"；子分類依據{''.join(f'「{h}」' for h in sub_hits[:3])}"
        results.append(Suggestion(topic, sub, reason, hits))
    return results


def classify_for_topics(topics: list[str], title: str, summary: str = "",
                        rules: dict[str, list[str]] | None = None) -> list[Suggestion]:
    """手動新增時：議題由使用者指定，子分類交給規則針對各議題嘗試判斷。"""
    out = []
    for topic in topics:
        terms = rules.get(topic) if rules is not None else None
        sub, sub_hits = subcategory_for_topic(topic, title, summary or "", terms)
        reason = "使用者手動指定議題"
        if sub:
            reason += f"；子分類依據{''.join(f'「{h}」' for h in sub_hits[:3])}"
        out.append(Suggestion(topic, sub, reason))
    return out
