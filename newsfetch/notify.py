"""每日爬蟲完成後寄送 Email 通知（SMTP）。

設定（GitHub Actions 的 Secrets，或本機環境變數）：
    SMTP_HOST       例如 smtp.gmail.com
    SMTP_PORT       587（STARTTLS，預設）或 465（SSL）
    SMTP_USER       寄件帳號
    SMTP_PASSWORD   密碼或應用程式密碼
    MAIL_TO         收件人，多位以逗號分隔
    MAIL_FROM       寄件人顯示（選填，預設同 SMTP_USER）
未設定 SMTP_HOST 或 MAIL_TO 時不寄信。
"""
from __future__ import annotations

import html
import json
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from . import config

MAX_LISTED = 20


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


def build_success(report: dict, pending_total: int, suggestions: int, links: Links) -> tuple[str, str, str]:
    """回傳 (主旨, 純文字內容, HTML 內容)。"""
    new = report.get("new_pending", [])
    failures = report.get("failures", [])
    attention = report.get("needs_attention", [])
    date = report["run_date"]

    subject = f"【新聞觀測站】{_mmdd(date)} 新增 {len(new)} 則待審核"
    if attention:
        subject += "（有項目需要檢視）"

    sources: dict[str, list[dict]] = {}
    for t in report.get("terms", []):
        sources.setdefault(t["source"], []).append(t)
    source_lines = []
    for name, terms in sources.items():
        ok = sum(1 for t in terms if not t.get("error"))
        found = sum(t.get("found", 0) for t in terms)
        source_lines.append(f"{name}：關鍵字 {ok}/{len(terms)} 個成功，找到 {found} 個連結")

    summary = [
        f"新增待審核：{len(new)} 則（目前共 {pending_total} 則待處理）",
        f"自動收錄：{len(report.get('auto_added', []))} 則",
        f"失敗：{len(failures)} 筆",
        *source_lines,
    ]
    if suggestions:
        summary.append(f"關鍵字學習：{suggestions} 項建議待處理")

    # ---- 純文字
    text = [f"每日爬蟲執行完成（{date}）", ""] + [f"・{s}" for s in summary] + [""]
    if attention:
        text += ["需要人工檢視："] + [f"・{a}" for a in attention] + [""]
    if new:
        text.append("新增待審核文章：")
        for a in new[:MAX_LISTED]:
            topics = "、".join(s["topic"] for s in a.get("suggestions", [])) or "規則未命中"
            text.append(f"・[{a['source']}] {a['title']}（{topics}）\n  {a['url']}")
        if len(new) > MAX_LISTED:
            text.append(f"・…另有 {len(new) - MAX_LISTED} 則")
        text.append("")
    for label, url in (("前往審核", links.dashboard), ("完整執行報告", links.report), ("執行紀錄", links.run)):
        if url:
            text.append(f"{label}：{url}")

    # ---- HTML（沿用儀表板配色）
    e = html.escape
    rows = "".join(
        f'<tr><td style="padding:10px 0;border-bottom:1px solid #D8CDB8;">'
        f'<div style="font-size:11px;color:#A69C8C;margin-bottom:3px;">{e(a["source"])}・'
        f'{e("、".join(s["topic"] for s in a.get("suggestions", [])) or "規則未命中")}</div>'
        f'<a href="{e(a["url"])}" style="color:#3A2E22;font-weight:bold;text-decoration:none;font-size:14px;">{e(a["title"])}</a>'
        f"</td></tr>"
        for a in new[:MAX_LISTED]
    )
    more = f'<p style="font-size:12px;color:#7D7263;">…另有 {len(new) - MAX_LISTED} 則</p>' if len(new) > MAX_LISTED else ""
    attention_html = (
        '<div style="background:#E3D9C4;border-radius:10px;padding:12px 14px;margin:16px 0;">'
        '<div style="font-size:12px;font-weight:bold;color:#7C4B2A;margin-bottom:6px;">需要人工檢視</div>'
        + "".join(f'<div style="font-size:12px;color:#3A2E22;line-height:1.7;">・{e(a)}</div>' for a in attention)
        + "</div>"
    ) if attention else ""
    button = (
        f'<a href="{e(links.dashboard)}" style="display:inline-block;background:#A9683F;color:#fff;'
        f'padding:9px 18px;border-radius:8px;text-decoration:none;font-size:13px;font-weight:bold;">前往審核</a>'
    ) if links.dashboard else ""
    footer_links = "　".join(
        f'<a href="{e(u)}" style="color:#7C4B2A;">{label}</a>'
        for label, u in (("完整執行報告", links.report), ("執行紀錄", links.run)) if u
    )
    body_html = f"""<div style="background:#F3EEE4;padding:24px 16px;font-family:'Microsoft JhengHei','PingFang TC',sans-serif;color:#3A2E22;">
  <div style="max-width:560px;margin:0 auto;">
    <div style="font-size:20px;font-weight:bold;letter-spacing:2px;">新聞觀測站</div>
    <div style="font-size:11px;color:#7C4B2A;letter-spacing:2px;margin-bottom:18px;">每日爬蟲執行完成・{e(date)}</div>
    <div style="background:#EAE2D2;border-radius:12px;padding:14px 16px;">
      {"".join(f'<div style="font-size:13px;line-height:1.9;">{e(s)}</div>' for s in summary)}
    </div>
    {attention_html}
    {f'<div style="font-size:12px;color:#7D7263;margin:18px 0 4px;">新增待審核文章</div><table style="width:100%;border-collapse:collapse;">{rows}</table>{more}' if new else ''}
    <div style="margin:20px 0 10px;">{button}</div>
    <div style="font-size:12px;">{footer_links}</div>
  </div>
</div>"""
    return subject, "\n".join(text), body_html


def build_failure(run_date: str, links: Links) -> tuple[str, str, str]:
    subject = f"【新聞觀測站】{_mmdd(run_date)} 每日爬蟲執行失敗"
    lines = [f"每日爬蟲在 {run_date} 執行失敗，今天的新聞可能沒有更新。",
             "請開啟執行紀錄查看錯誤訊息，可以把錯誤內容貼給 Claude 一起排查。"]
    if links.run:
        lines += ["", f"執行紀錄：{links.run}"]
    e = html.escape
    body_html = (
        "<div style=\"background:#F3EEE4;padding:24px 16px;font-family:'Microsoft JhengHei',sans-serif;color:#3A2E22;\">"
        '<div style="max-width:560px;margin:0 auto;"><div style="font-size:20px;font-weight:bold;">新聞觀測站</div>'
        f'<p style="font-size:14px;line-height:1.8;">{e(lines[0])}<br>{e(lines[1])}</p>'
        + (f'<a href="{e(links.run)}" style="color:#7C4B2A;">查看執行紀錄</a>' if links.run else "")
        + "</div></div>"
    )
    return subject, "\n".join(lines), body_html


def send(subject: str, text: str, body_html: str, env: dict | None = None) -> bool:
    """寄出 Email。未設定 SMTP 時回傳 False（不視為錯誤）。"""
    env = env if env is not None else os.environ
    host, to = env.get("SMTP_HOST", "").strip(), env.get("MAIL_TO", "").strip()
    if not host or not to:
        print("未設定 SMTP_HOST／MAIL_TO，略過 Email 通知")
        return False
    port = int(env.get("SMTP_PORT") or 587)
    user, password = env.get("SMTP_USER", ""), env.get("SMTP_PASSWORD", "")
    sender = env.get("MAIL_FROM") or user

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("新聞觀測站", sender)) if "<" not in sender else sender
    msg["To"] = ", ".join(a.strip() for a in to.split(",") if a.strip())
    msg.set_content(text)
    msg.add_alternative(body_html, subtype="html")

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as s:
            if user:
                s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=context)
            if user:
                s.login(user, password)
            s.send_message(msg)
    print(f"已寄出 Email 通知：{subject} → {msg['To']}")
    return True


def notify_run(run_date: str, status: str = "success", log_dir: Path | None = None,
               export_dir: Path | None = None, env: dict | None = None) -> bool:
    links = Links.from_env(run_date)
    if status != "success":
        return send(*build_failure(run_date, links), env=env)
    log_dir = Path(log_dir or config.LOG_DIR)
    export_dir = Path(export_dir or config.EXPORT_DIR)
    report = _load_json(log_dir / f"{run_date}-report.json", None)
    if report is None:  # 爬蟲步驟沒有產生報告，視同失敗
        return send(*build_failure(run_date, links), env=env)
    pending_total = len(_load_json(export_dir / "pending.json", []))
    suggestions = len(_load_json(export_dir / "keywords.json", {}).get("suggestions", []))
    return send(*build_success(report, pending_total, suggestions, links), env=env)
