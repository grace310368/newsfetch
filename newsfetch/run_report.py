"""產生每日執行報告：logs/YYYY-MM-DD-report.md（給人看／貼給 Claude 討論）與同名 .json（結構化）。"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from . import config
from .crawler import RunResult


def _md_escape(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


KIND_LABEL = {"seed": "搜尋關鍵字", "topic": "議題規則"}


def render_learning(learning: dict) -> list[str]:
    m = learning["missed"]
    lines = ["## 關鍵字學習", "",
             f"手動新增（爬蟲漏抓）共 {m['manual_total']} 篇：關鍵字缺口 {m['keyword_gap']} 篇、"
             f"已含搜尋關鍵字但仍漏抓（來源抓取問題）{m['source_gap']} 篇。", ""]
    if m["source_gap_examples"]:
        lines.append("來源抓取問題範例：" + "；".join(m["source_gap_examples"]))
        lines.append("")
    sugs = learning["suggestions"][:10]
    if not sugs:
        return lines + ["- 目前沒有新的關鍵字建議", ""]
    lines += ["| 建議 | 關鍵字 | 對象 | 佐證 |", "|---|---|---|---|"]
    for sg in sugs:
        action = "新增" if sg["action"] == "adopt" else "停用"
        target = KIND_LABEL[sg["kind"]] + (f"「{sg['topic']}」" if sg["topic"] else "")
        lines.append(f"| {action} | {_md_escape(sg['term'])} | {target} | {_md_escape(sg['summary'])} |")
    return lines + ["", "（於儀表板「待審核」畫面的「關鍵字建議」區塊採用或忽略）", ""]


def render_markdown(r: RunResult, learning: dict | None = None) -> str:
    lines = [f"# 每日爬蟲執行報告 {r.run_date}", ""]
    lines += [f"- 開始：{r.started_at}", f"- 結束：{r.finished_at}",
              f"- 新增待審核：**{len(r.new_pending)}** 則", f"- 自動收錄（自動模式議題）：{len(r.auto_added)} 則",
              f"- 已收錄過（重複）：{r.duplicates}", f"- 發布日期超出回溯範圍（{config.LOOKBACK_DAYS} 天）：{r.out_of_window}",
              f"- 先前已判定略過：{r.skipped_seen}", f"- 失敗：**{len(r.failures)}** 筆", ""]

    lines += ["## 需要人工檢視", ""]
    lines += [f"- 【注意】{n}" for n in r.needs_attention] or ["- 無"]
    lines.append("")

    lines += ["## 各來源／關鍵字結果", ""]
    for source in dict.fromkeys(t.source for t in r.terms):
        rows = [t for t in r.terms if t.source == source]
        ok = sum(1 for t in rows if not t.error)
        lines += [f"### {source}（成功 {ok}／失敗 {len(rows) - ok}，共找到 {sum(t.found for t in rows)} 個連結）", "",
                  "| 關鍵字 | 找到連結 | 狀態 | 備註 |", "|---|---:|---|---|"]
        for t in rows:
            status = "失敗" if t.error else ("無結果" if t.found == 0 else "成功")
            note = t.error or "；".join(t.notes)
            lines.append(f"| {_md_escape(t.term)} | {t.found} | {status} | {_md_escape(note)} |")
        lines.append("")

    lines += ["## 失敗原因分類", ""]
    by_cat = r.failures_by_category()
    if not by_cat:
        lines += ["- 無", ""]
    for cat, items in by_cat.items():
        lines += [f"### {cat}（{len(items)}）", ""]
        for f in items[:50]:
            lines.append(f"- [{f['source']}] {f['target']} — {_md_escape(f['message'])}")
        if len(items) > 50:
            lines.append(f"- …另有 {len(items) - 50} 筆，詳見 JSON 報告")
        lines.append("")

    lines += ["## 新增待審核文章", ""]
    if not r.new_pending:
        lines += ["- 無", ""]
    for a in r.new_pending:
        sug = "、".join(f"{s['topic']}／{s['subcategory'] or '子分類未命中'}" for s in a["suggestions"])
        lines.append(f"- [{_md_escape(a['title'])}]({a['url']}) {a['source']} {a['date']}"
                     f"（關鍵字「{a['term']}」）→ {sug or '**規則未命中任何議題**'}")
    lines.append("")

    unclassified = [a for a in r.new_pending if not a["suggestions"]]
    lines += [f"## 規則未命中文章（{len(unclassified)}）", "",
              "以下文章被關鍵字搜尋找到，但議題規則全部沒命中，可作為擴充 TOPICS 關鍵字的依據：", ""]
    lines += [f"- [{_md_escape(a['title'])}]({a['url']})（搜尋詞「{a['term']}」）" for a in unclassified] or ["- 無"]
    lines.append("")
    if learning:
        lines += render_learning(learning)
    lines += ["---", "討論格式建議：問題現象／可能原因／改進建議。"]
    return "\n".join(lines) + "\n"


def write_report(r: RunResult, log_dir: Path | None = None, learning: dict | None = None) -> Path:
    log_dir = Path(log_dir or config.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    md = log_dir / f"{r.run_date}-report.md"
    md.write_text(render_markdown(r, learning), encoding="utf-8")
    (log_dir / f"{r.run_date}-report.json").write_text(
        json.dumps(asdict(r), ensure_ascii=False, indent=2), encoding="utf-8")
    return md
