"""每日通知：在「每日爬蟲通知」Issue 留言摘要並 @ repo 擁有者，由 GitHub 寄 Email。

- 環境變數：GITHUB_TOKEN、GITHUB_REPOSITORY（Actions 自動提供）；NOTIFY_MENTION（選填）
- 只維持一則開啟中的 Issue（以 ISSUE_LABEL 辨識），每天新增一則留言
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import quote
from dataclasses import dataclass
from pathlib import Path

from . import config

ISSUE_TITLE = "每日爬蟲通知"
ISSUE_LABEL = "每日爬蟲通知"
MAX_LISTED = 20
API = os.environ.get("GITHUB_API_URL", "https://api.github.com")


@dataclass
class Links:
    dashboard: str = ""
    report: str = ""
    run: str = ""

    @classmethod
    def from_env(cls, run_date: str) -> "Links":
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        if not repo:
            return cls()
        owner, name = repo.split("/", 1)
        run_id = os.environ.get("GITHUB_RUN_ID")
        branch = os.environ.get("GITHUB_REF_NAME", "main")
        return cls(
            dashboard=f"https://{owner.lower()}.github.io/{name}/#review",
            report=f"{server}/{repo}/blob/{branch}/logs/{run_date}-report.md",
            run=f"{server}/{repo}/actions/runs/{run_id}" if run_id else "",
        )


def _mmdd(date: str) -> str:
    return f"{int(date[5:7])}/{int(date[8:10])}"


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _md(text: str) -> str:
    """避免標題中的 Markdown 符號破壞版面。"""
    return text.replace("[", "［").replace("]", "］").replace("|", "｜")


def _footer(links: Links) -> list[str]:
    parts = [f"[{label}]({url})" for label, url in
             (("前往審核", links.dashboard), ("完整執行報告", links.report), ("執行紀錄", links.run)) if url]
    return ["", "　｜　".join(parts)] if parts else []


def build_success(report: dict, pending_total: int, suggestions: int, links: Links) -> str:
    new = report.get("new_pending", [])
    failures = report.get("failures", [])
    attention = report.get("needs_attention", [])
    date = report["run_date"]

    lines = [f"### {_mmdd(date)} 新增 {len(new)} 則待審核" + ("（有項目需要檢視）" if attention else ""), ""]
    lines.append(f"- 目前共 **{pending_total}** 則待處理；自動收錄 {len(report.get('auto_added', []))} 則；失敗 {len(failures)} 筆")
    sources: dict[str, list[dict]] = {}
    for t in report.get("terms", []):
        sources.setdefault(t["source"], []).append(t)
    for name, terms in sources.items():
        ok = sum(1 for t in terms if not t.get("error"))
        found = sum(t.get("found", 0) for t in terms)
        lines.append(f"- {name}：關鍵字 {ok}/{len(terms)} 個成功，找到 {found} 個連結")
    if suggestions:
        lines.append(f"- 關鍵字學習：{suggestions} 項建議待處理")

    if attention:
        lines += ["", "**需要人工檢視**"] + [f"- {a}" for a in attention]

    if new:
        lines += ["", "**新增待審核文章**"]
        for a in new[:MAX_LISTED]:
            topics = "、".join(s["topic"] for s in a.get("suggestions", [])) or "規則未命中"
            lines.append(f"- [{_md(a['title'])}]({a['url']})　{a['source']}・{topics}")
        if len(new) > MAX_LISTED:
            lines.append(f"- …另有 {len(new) - MAX_LISTED} 則")
    return "\n".join(lines + _footer(links))


def build_failure(run_date: str, links: Links) -> str:
    lines = [f"### {_mmdd(run_date)} 每日爬蟲執行失敗", "",
             "今天的新聞可能沒有更新。請開啟執行紀錄查看錯誤訊息，可以把錯誤內容貼給 Claude 一起排查。"]
    return "\n".join(lines + _footer(links))


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------

class GitHub:
    def __init__(self, repo: str, token: str):
        self.repo, self.token = repo, token

    def request(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(
            f"{API}/repos/{self.repo}{path}",
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        return json.loads(data) if data else None


def _ensure_issue(gh, mention: str) -> int:
    issues = gh.request("GET", f"/issues?state=open&labels={quote(ISSUE_LABEL)}&per_page=10") or []
    issues = [i for i in issues if "pull_request" not in i]
    if issues:
        return issues[0]["number"]
    try:
        gh.request("POST", "/labels", {"name": ISSUE_LABEL, "color": "A9683F",
                                       "description": "新聞觀測站每日爬蟲的執行摘要"})
    except urllib.error.HTTPError as e:
        if e.code != 422:  # 422＝標籤已存在
            raise
    issue = gh.request("POST", "/issues", {
        "title": ISSUE_TITLE,
        "labels": [ISSUE_LABEL],
        "body": (f"{mention} 每日爬蟲跑完後，會在這則 Issue 留言當天的摘要，GitHub 會把留言寄到你的 Email。\n\n"
                 "請保持這則 Issue 開啟；若關閉，下一次執行會自動再開一則。"),
    })
    return issue["number"]


def post(body: str, env: dict | None = None, gh=None) -> bool:
    """在通知 Issue 留言。缺少 GITHUB_TOKEN／GITHUB_REPOSITORY（例如本機執行）時略過並回傳 False。"""
    env = env if env is not None else os.environ
    repo, token = env.get("GITHUB_REPOSITORY", ""), env.get("GITHUB_TOKEN", "")
    if gh is None:
        if not repo or not token:
            print("未提供 GITHUB_TOKEN／GITHUB_REPOSITORY，略過通知（本機執行時屬正常）")
            return False
        gh = GitHub(repo, token)
    owner = env.get("NOTIFY_MENTION") or (repo.split("/")[0] if repo else "")
    mention = f"@{owner.lstrip('@')}" if owner else ""
    number = _ensure_issue(gh, mention)
    gh.request("POST", f"/issues/{number}/comments", {"body": f"{body}\n\n{mention}".rstrip()})
    print(f"已在 Issue #{number} 留言通知")
    return True


def notify_run(run_date: str, status: str = "success", log_dir: Path | None = None,
               export_dir: Path | None = None, env: dict | None = None, gh=None) -> bool:
    links = Links.from_env(run_date)
    if status != "success":
        return post(build_failure(run_date, links), env, gh)
    log_dir = Path(log_dir or config.LOG_DIR)
    export_dir = Path(export_dir or config.EXPORT_DIR)
    report = _load_json(log_dir / f"{run_date}-report.json", None)
    if report is None:  # 爬蟲步驟沒有產生報告，視同失敗
        return post(build_failure(run_date, links), env, gh)
    pending_total = len(_load_json(export_dir / "pending.json", []))
    suggestions = len(_load_json(export_dir / "keywords.json", {}).get("suggestions", []))
    return post(build_success(report, pending_total, suggestions, links), env, gh)
