"""關鍵字學習：從人工審核結果找出關鍵字庫的缺口與誤觸，產生「建議」，由使用者決定是否採用。

純統計、不呼叫 LLM。訊號來源：
1. 手動新增的文章（爬蟲漏抓）
   - 文章裡已含既有搜尋關鍵字 → 屬於「來源抓取」問題（例如搜尋被擋、搜尋引擎沒收錄）
   - 文章裡不含任何搜尋關鍵字 → 屬於「關鍵字缺口」→ 建議新增搜尋關鍵字
2. 已收錄文章中，現行議題規則判斷不出、但人工歸入某議題的「議題缺口」→ 建議新增議題規則關鍵字
3. 規則關鍵字／搜尋關鍵字實際命中後被移除或刪除的比例 → 誤觸率高者建議停用

候選詞彙取自報社編輯下的 meta-keywords（以及標題中的英文縮寫），比自行斷詞乾淨；
再以「出現在標題、標籤、摘要中」統計各文章是否包含該詞。
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config, rules
from .classifier import classify, find_terms

WINDOW_DAYS = 365           # 只用近一年的審核資料
MIN_TOPIC_SUPPORT = 2       # 議題規則建議：至少出現在 2 篇該議題文章
MIN_TOPIC_PRECISION = 0.7   # 議題規則建議：含此詞的文章至少 70% 屬於該議題
MIN_SEED_PRECISION = 0.6    # 搜尋關鍵字建議：含此詞的文章至少 60% 是相關文章（非刪除的雜訊）
MIN_MISFIRE_SAMPLES = 3     # 停用建議：至少命中過 3 次才判斷
MISFIRE_RATE = 0.7          # 停用建議：誤觸率 70% 以上
MAX_SUGGESTIONS = 30

# 太籠統、會帶進大量無關新聞的標籤（另外也排除子分類關鍵字）
STOPWORDS = {
    "台股", "美股", "陸股", "港股", "日股", "股市", "盤後量價", "焦點", "財經", "理財", "產業", "證券",
    "保險", "投資", "經濟", "新聞", "要聞", "市場", "金融", "金融業", "金融股", "公司", "企業", "台灣",
    "中國", "美國", "大陸", "專題", "獨家", "快訊", "即時", "熱門", "外資", "投信", "法人", "營收",
}
# 金融機構名稱：樣本少時「剛好參與該活動的公司」會跟議題高度相關，但不是好的規則詞
INSTITUTIONS = {
    "富邦", "國泰", "凱基", "元大", "永豐", "玉山", "中信", "台新", "兆豐", "第一", "華南", "合庫", "彰銀",
    "土銀", "新光", "開發", "群益", "統一", "國票", "南山", "中壽", "遠東", "渣打", "匯豐", "花旗", "星展",
    "上海商銀", "京城", "王道", "將來", "連線", "樂天", "三商美邦", "安聯", "安泰", "日盛", "康和", "元富",
    "華南永昌", "基富通", "集保", "集保結算所", "櫃買中心", "證交所", "期交所", "券商公會", "投信投顧公會",
}
INSTITUTION_RE = re.compile(r"(金控|金|銀行|銀|證券|證|人壽|壽|產險|投信|投顧|期貨|保經|保代)$")
ASCII_TERM_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9]{1,6}(?![A-Za-z0-9])")


@dataclass
class Doc:
    key: str
    title: str
    text: str                      # 標題＋標籤＋摘要，用來判斷是否含某詞
    keywords: list[str]
    summary: str = ""
    topics: set[str] = field(default_factory=set)
    origin: str = "crawler"
    deleted: bool = False


def _since() -> str:
    return (datetime.now(ZoneInfo(config.TIMEZONE)) - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")


def _split_keywords(raw: str | None) -> list[str]:
    return [k.strip() for k in re.split(r"[,，、]", raw or "") if k.strip()]


def load_docs(conn: sqlite3.Connection) -> list[Doc]:
    since = _since()
    docs: dict[str, Doc] = {}
    for r in conn.execute("SELECT * FROM articles WHERE published_date >= ?", (since,)):
        kws = _split_keywords(r["raw_keywords"])
        docs[r["url"]] = Doc(r["url"], r["title"], " ".join([r["title"], ",".join(kws), r["summary"] or ""]),
                             kws, r["summary"] or "", origin=r["origin"])
    for r in conn.execute("SELECT article_url, topic FROM article_classifications"):
        if r["article_url"] in docs:
            docs[r["article_url"]].topics.add(r["topic"])
    for r in conn.execute(
        "SELECT * FROM pending_review WHERE status = 'deleted' AND COALESCE(published_date, created_at) >= ?", (since,)
    ):
        kws = _split_keywords(r["raw_keywords"])
        docs[r["url"]] = Doc(r["url"], r["title"], " ".join([r["title"], ",".join(kws), r["summary"] or ""]),
                             kws, r["summary"] or "", origin=r["origin"], deleted=True)
    return list(docs.values())


def is_institution(term: str) -> bool:
    return term in INSTITUTIONS or any(term.startswith(n) for n in INSTITUTIONS) \
        or (len(term) <= 5 and bool(INSTITUTION_RE.search(term)))


def _eligible(term: str) -> bool:
    if len(term) < 2 or len(term) > 12 or term.isdigit() or term in STOPWORDS or is_institution(term):
        return False
    return not any(term in words for words in config.SUBCATEGORIES.values())


def vocabulary(docs: list[Doc]) -> set[str]:
    vocab = set()
    for d in docs:
        vocab.update(k for k in d.keywords if _eligible(k))
        vocab.update(m for m in ASCII_TERM_RE.findall(d.title) if _eligible(m))
    return vocab


def _contains(doc: Doc, term: str) -> bool:
    return bool(find_terms(doc.text, [term]))


def _examples(docs: list[Doc], n: int = 2) -> list[str]:
    return [d.title for d in docs[:n]]


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


# ---------------------------------------------------------------------------
# 建議
# ---------------------------------------------------------------------------

def topic_suggestions(docs: list[Doc], vocab: set[str], topic_rules: dict[str, list[str]],
                      processed: set[tuple[str, str, str]]) -> list[dict]:
    confirmed = [d for d in docs if not d.deleted]
    # 現行規則判斷不出、但人工歸入的議題
    gaps = {d.key: d.topics - {s.topic for s in classify(d.title, d.summary, d.keywords, topic_rules)} for d in confirmed}
    owner = {w: t for t, words in topic_rules.items() for w in words}
    out = []
    for term in vocab:
        if term in owner:  # 已是某議題的規則詞，不跨議題建議
            continue
        having = [d for d in docs if _contains(d, term)]
        if len(having) < MIN_TOPIC_SUPPORT:
            continue
        for topic in config.TOPIC_NAMES:
            if (term, "topic", topic) in processed:
                continue
            pos = [d for d in having if topic in d.topics]
            gap = [d for d in pos if topic in gaps.get(d.key, set())]
            if len(pos) < MIN_TOPIC_SUPPORT or not gap:
                continue
            precision = len(pos) / len(having)
            if precision < MIN_TOPIC_PRECISION:
                continue
            out.append({
                "action": "adopt", "kind": "topic", "topic": topic, "term": term,
                "score": round((len(gap) * 2 + len(pos)) * precision, 2),
                "stats": {"support": len(pos), "gaps": len(gap), "precision": round(precision, 3)},
                "summary": f"{len(pos)} 篇「{topic}」文章含此詞，其中 {len(gap)} 篇現行規則沒判斷到；"
                           f"含此詞的文章 {_pct(precision)} 屬於此議題",
                "examples": _examples(gap),
            })
    return out


def missed_analysis(docs: list[Doc], seed_terms: list[str]) -> tuple[list[Doc], list[Doc]]:
    """手動新增（爬蟲漏抓）的文章，分成「關鍵字缺口」與「已含搜尋關鍵字（來源抓取問題）」。

    只看標題與標籤中的「具體」搜尋詞：搜尋引擎主要依這兩處排序；而「金管會」這類範圍很廣的詞
    （config.BROAD_SEED_GROUPS）每天只取前幾十筆結果，實際上不保證搜得到。
    """
    broad = {t for g in config.BROAD_SEED_GROUPS for t in config.SEED_TERMS.get(g, [])}
    specific = [t for t in seed_terms if t not in broad]
    manual = [d for d in docs if d.origin == "manual" and not d.deleted]
    covered = [d for d in manual if find_terms(d.title + " " + ",".join(d.keywords), specific)]
    uncovered = [d for d in manual if d not in covered]
    return uncovered, covered


def seed_suggestions(docs: list[Doc], vocab: set[str], seed_terms: list[str],
                     processed: set[tuple[str, str, str]]) -> list[dict]:
    uncovered, _ = missed_analysis(docs, seed_terms)
    if not uncovered:
        return []
    out = []
    for term in vocab:
        if term in seed_terms or (term, "seed", "") in processed:
            continue
        missed = [d for d in uncovered if _contains(d, term)]
        if not missed:
            continue
        having = [d for d in docs if _contains(d, term)]
        relevant = [d for d in having if not d.deleted]
        precision = len(relevant) / len(having)
        in_title = any(term in d.title for d in missed)
        # 至少兩篇佐證，或出現在漏抓文章的標題中（強訊號）
        if precision < MIN_SEED_PRECISION or not (len(relevant) >= 2 or in_title):
            continue
        out.append({
            "action": "adopt", "kind": "seed", "topic": "", "term": term,
            "score": round((len(missed) * 3 + len(relevant) + (1 if in_title else 0)) * precision, 2),
            "stats": {"missed": len(missed), "relevant": len(relevant), "noise": len(having) - len(relevant),
                      "precision": round(precision, 3)},
            "summary": f"出現在 {len(missed)} 篇爬蟲漏抓（手動新增）的文章；共 {len(relevant)} 篇相關文章含此詞"
                       + (f"、{len(having) - len(relevant)} 篇被刪除的雜訊" if len(having) > len(relevant) else ""),
            "examples": _examples(missed),
        })
    return out


def topic_term_stats(conn: sqlite3.Connection, topic_rules: dict[str, list[str]]) -> list[dict]:
    """各議題規則關鍵字的實際表現：命中後被核准（正確）或被移除／整篇刪除（誤觸）。"""
    counts: dict[tuple[str, str], list[int]] = {}
    rows = conn.execute(
        """SELECT s.suggested_topic AS topic, s.matched_terms, p.status,
                  EXISTS(SELECT 1 FROM pending_review_final f
                         WHERE f.pending_review_id = s.pending_review_id AND f.final_topic = s.suggested_topic) AS kept
           FROM pending_review_suggestions s JOIN pending_review p ON p.id = s.pending_review_id
           WHERE p.status != 'pending' AND p.origin = 'crawler' AND s.matched_terms IS NOT NULL
             AND p.reviewed_at >= ?""",
        (_since(),),
    )
    for r in rows:
        for term in r["matched_terms"].split(","):
            c = counts.setdefault((r["topic"], term), [0, 0])
            c[0] += 1
            c[1] += 0 if r["kept"] else 1
    out = []
    for (topic, term), (n, wrong) in counts.items():
        out.append({"kind": "topic", "topic": topic, "term": term, "hits": n, "misfires": wrong,
                    "misfire_rate": round(wrong / n, 3), "active": term in topic_rules.get(topic, [])})
    return sorted(out, key=lambda x: (-x["misfire_rate"], -x["hits"]))


def seed_term_stats(conn: sqlite3.Connection, seed_terms: list[str]) -> list[dict]:
    """各搜尋關鍵字找到的文章數與審核結果（找到的文章以「第一個找到它的關鍵字」計）。"""
    rows = conn.execute(
        """SELECT search_term AS term, COUNT(*) AS found,
                  SUM(status IN ('approved', 'edited')) AS approved,
                  SUM(status = 'deleted') AS deleted,
                  SUM(status = 'pending') AS pending
           FROM pending_review WHERE origin = 'crawler' AND search_term IS NOT NULL AND created_at >= ?
           GROUP BY search_term""",
        (_since(),),
    ).fetchall()
    by_term = {r["term"]: r for r in rows}
    out = []
    for term in dict.fromkeys(seed_terms + list(by_term)):
        r = by_term.get(term)
        found, approved, deleted = (r["found"], r["approved"] or 0, r["deleted"] or 0) if r else (0, 0, 0)
        reviewed = approved + deleted
        out.append({"kind": "seed", "term": term, "found": found, "approved": approved, "deleted": deleted,
                    "pending": (r["pending"] or 0) if r else 0,
                    "relevant_rate": round(approved / reviewed, 3) if reviewed else None,
                    "active": term in seed_terms})
    return sorted(out, key=lambda x: (-x["found"], x["term"]))


def disable_suggestions(topic_stats: list[dict], seed_stats: list[dict],
                        processed: set[tuple[str, str, str]]) -> list[dict]:
    out = []
    for s in topic_stats:
        if not s["active"] or (s["term"], "topic", s["topic"]) in processed:
            continue
        if s["hits"] >= MIN_MISFIRE_SAMPLES and s["misfire_rate"] >= MISFIRE_RATE:
            out.append({
                "action": "disable", "kind": "topic", "topic": s["topic"], "term": s["term"],
                "score": round(s["misfires"] * s["misfire_rate"], 2),
                "stats": {k: s[k] for k in ("hits", "misfires", "misfire_rate")},
                "summary": f"命中「{s['topic']}」{s['hits']} 次，其中 {s['misfires']} 次被移除或整篇刪除"
                           f"（誤觸率 {_pct(s['misfire_rate'])}）",
                "examples": [],
            })
    for s in seed_stats:
        reviewed = s["approved"] + s["deleted"]
        if not s["active"] or (s["term"], "seed", "") in processed or reviewed < MIN_MISFIRE_SAMPLES + 2:
            continue
        if s["deleted"] / reviewed >= MISFIRE_RATE:
            out.append({
                "action": "disable", "kind": "seed", "topic": "", "term": s["term"],
                "score": round(s["deleted"] * s["deleted"] / reviewed, 2),
                "stats": {"found": s["found"], "approved": s["approved"], "deleted": s["deleted"]},
                "summary": f"此搜尋關鍵字找到的 {reviewed} 篇已審核文章中，{s['deleted']} 篇被整篇刪除",
                "examples": [],
            })
    return out


def analyze(conn: sqlite3.Connection) -> dict:
    topic_rules = rules.active_topics(conn)
    seed_terms = rules.active_seed_terms(conn)
    processed = rules.learned_terms(conn)
    docs = load_docs(conn)
    vocab = vocabulary(docs)

    topic_stats = topic_term_stats(conn, topic_rules)
    seed_stats = seed_term_stats(conn, seed_terms)
    suggestions = (topic_suggestions(docs, vocab, topic_rules, processed)
                   + seed_suggestions(docs, vocab, seed_terms, processed)
                   + disable_suggestions(topic_stats, seed_stats, processed))
    suggestions.sort(key=lambda s: (-s["score"], s["term"]))

    uncovered, covered = missed_analysis(docs, seed_terms)
    learned = [dict(r) for r in conn.execute(
        "SELECT term, kind, topic, status, evidence, updated_at FROM keyword_rules ORDER BY updated_at DESC")]
    return {
        "suggestions": suggestions[:MAX_SUGGESTIONS],
        "missed": {
            "manual_total": len(uncovered) + len(covered),
            "keyword_gap": len(uncovered),
            "source_gap": len(covered),
            "keyword_gap_examples": _examples(uncovered, 3),
            "source_gap_examples": _examples(covered, 3),
        },
        "seed_term_stats": seed_stats,
        "topic_term_stats": topic_stats,
        "learned": learned,
        "counts": {"seed_terms": len(seed_terms), "topic_terms": sum(len(v) for v in topic_rules.values())},
    }
