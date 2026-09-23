"""月度重點報告與趨勢報告（Claude API，批次排程觸發，不在使用者瀏覽時呼叫）。

成本控制：
- 月度報告：只送「標題＋150 字摘要」，依子分類分三組，一次呼叫產出三段
- 趨勢報告：只送已濃縮的月度報告文字，不重新讀原始新聞
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date

from pydantic import BaseModel, Field

from . import config
from .db import now_iso

MODEL = os.environ.get("NEWSFETCH_CLAUDE_MODEL", "claude-opus-5")
NO_NEWS = "本月無相關新聞"

SYSTEM = (
    "你是台灣金融政策研究助理，協助彙整金管會「金融卓越發展計畫」相關新聞。"
    "請使用道地的繁體中文，語氣中性、聚焦政策推進脈絡，不要加入新聞以外的臆測。"
)


class MonthlyReport(BaseModel):
    policy_report: str = Field(description="政策與法規段落，60-80 字")
    product_report: str = Field(description="商品與業務段落，60-80 字")
    peer_report: str = Field(description="同業動態段落，60-80 字")


class TrendStage(BaseModel):
    period_label: str = Field(description="時間標籤，如「2025 Q1」「2025 Q4－2026 Q1」")
    primary_subcategory: str = Field(description="政策與法規／商品與業務／同業動態 三選一")
    stage_description: str = Field(description="該階段的整合敘事描述，約 60-100 字")


class TrendReport(BaseModel):
    stages: list[TrendStage] = Field(description="依時間由舊到新排列的階段")


def _client():
    import anthropic

    return anthropic.Anthropic()


def _parse(output_format, prompt: str):
    """呼叫 Claude 並以 Pydantic schema 驗證輸出。啟用 server-side fallback 處理拒答。"""
    response = _client().messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        messages=[{"role": "user", "content": prompt}],
        output_format=output_format,
        extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
        extra_body={"fallbacks": "default"},
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude 拒絕產生報告：{response.stop_details}")
    if response.parsed_output is None:
        raise RuntimeError(f"Claude 回應無法解析（stop_reason={response.stop_reason}）")
    return response.parsed_output


# ---------------------------------------------------------------------------
# 月度報告
# ---------------------------------------------------------------------------

def month_articles(conn: sqlite3.Connection, topic: str, year_month: str) -> dict[str, list[sqlite3.Row]]:
    """某議題某月份的文章，依「該議題底下」的子分類分組。"""
    rows = conn.execute(
        """SELECT a.title, a.summary, a.published_date, c.subcategory
           FROM article_classifications c JOIN articles a ON a.url = c.article_url
           WHERE c.topic = ? AND substr(a.published_date, 1, 7) = ?
           ORDER BY a.published_date""",
        (topic, year_month),
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = {s: [] for s in config.SUBCATEGORY_NAMES}
    for r in rows:
        groups.setdefault(r["subcategory"] or "政策與法規", []).append(r)
    return groups


def build_monthly_prompt(topic: str, year_month: str, groups: dict[str, list]) -> str:
    parts = [f"議題：{topic}", f"月份：{year_month}", ""]
    for sub in config.SUBCATEGORY_NAMES:
        parts.append(f"【{sub}】")
        items = groups.get(sub) or []
        if not items:
            parts.append("（本月無新聞）")
        for r in items:
            parts.append(f"- {r['published_date']} {r['title']}：{r['summary'] or ''}")
        parts.append("")
    parts.append(
        "請根據以上依三個類別分組的新聞標題與摘要，分別為政策與法規、商品與業務、同業動態三個類別"
        "各寫一段 60-80 字的重點摘要，說明該類別本月討論了什麼、有無明顯轉折；"
        f"若某類別當月沒有新聞，該段落請填『{NO_NEWS}』。"
    )
    return "\n".join(parts)


def generate_monthly(conn: sqlite3.Connection, topic: str, year_month: str, dry_run: bool = False) -> dict | None:
    groups = month_articles(conn, topic, year_month)
    count = sum(len(v) for v in groups.values())
    if count == 0:
        return None  # 當月完全無文章：不生成報告
    prompt = build_monthly_prompt(topic, year_month, groups)
    if dry_run:
        return {"topic": topic, "year_month": year_month, "prompt": prompt, "article_count": count}
    report: MonthlyReport = _parse(MonthlyReport, prompt)
    fields = {
        "policy_report": report.policy_report,
        "product_report": report.product_report,
        "peer_report": report.peer_report,
    }
    # 沒有文章的子分類固定顯示「本月無相關新聞」，不採用模型輸出
    for sub, field in config.SUBCATEGORY_REPORT_FIELDS.items():
        if not groups.get(sub):
            fields[field] = NO_NEWS
    conn.execute(
        """INSERT OR REPLACE INTO monthly_reports(topic, year_month, policy_report, product_report,
               peer_report, article_count, generated_at) VALUES (?,?,?,?,?,?,?)""",
        (topic, year_month, fields["policy_report"], fields["product_report"], fields["peer_report"],
         count, now_iso()),
    )
    conn.commit()
    return {"topic": topic, "year_month": year_month, "article_count": count, **fields}


def previous_month(today: date | None = None) -> str:
    today = today or date.today()
    y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    return f"{y:04d}-{m:02d}"


# ---------------------------------------------------------------------------
# 趨勢報告
# ---------------------------------------------------------------------------

def build_trend_prompt(topic: str, reports: list[sqlite3.Row]) -> str:
    parts = [f"議題：{topic}", "以下為按時間排序的月度重點摘要：", ""]
    for r in reports:
        parts.append(f"■ {r['year_month']}（{r['article_count']} 則新聞）")
        parts.append(f"  [政策與法規] {r['policy_report']}")
        parts.append(f"  [商品與業務] {r['product_report']}")
        parts.append(f"  [同業動態] {r['peer_report']}")
    parts += ["",
              "請根據以上按時間排序的月度摘要，整理出幾個階段性的敘事演變描述，說明這個議題的討論方向"
              "如何隨時間推進，語氣中性、聚焦政策推進脈絡，非條列式新聞回顧；每個階段請額外標注一個主要"
              "子分類（政策與法規／商品與業務／同業動態三選一），代表這個階段的變化主要落在哪個面向。"
              "階段數量以 2–5 個為宜，依時間由舊到新排列，period_label 使用「YYYY Qn」或「YYYY Qn－YYYY Qn」格式。"]
    return "\n".join(parts)


def generate_trend(conn: sqlite3.Connection, topic: str, dry_run: bool = False) -> list[dict] | dict | None:
    reports = conn.execute(
        "SELECT * FROM monthly_reports WHERE topic = ? ORDER BY year_month", (topic,)
    ).fetchall()
    if len(reports) < 2:
        return None  # 需要先累積數個月的月度報告
    prompt = build_trend_prompt(topic, reports)
    if dry_run:
        return {"topic": topic, "prompt": prompt, "months": len(reports)}
    trend: TrendReport = _parse(TrendReport, prompt)
    now = now_iso()
    conn.execute("DELETE FROM trend_reports WHERE topic = ?", (topic,))
    stages = []
    for i, st in enumerate(trend.stages):
        sub = st.primary_subcategory if st.primary_subcategory in config.SUBCATEGORIES else None
        conn.execute(
            """INSERT INTO trend_reports(topic, period_label, primary_subcategory, stage_description,
                   generated_at, sort_order) VALUES (?,?,?,?,?,?)""",
            (topic, st.period_label, sub, st.stage_description, now, i),
        )
        stages.append({"period": st.period_label, "subcategory": sub, "description": st.stage_description})
    conn.commit()
    return stages
