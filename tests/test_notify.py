import json

import pytest

from newsfetch import notify

REPORT = {
    "run_date": "2026-10-08",
    "new_pending": [
        {"url": "https://www.ctee.com.tw/news/1-1", "title": "亞資中心新進度", "source": "工商時報",
         "date": "2026-10-08", "term": "亞資中心",
         "suggestions": [{"topic": "亞洲資產管理中心", "subcategory": "政策與法規", "reason": ""}]},
        {"url": "https://money.udn.com/money/story/1/2", "title": "台股<收盤>", "source": "經濟日報",
         "date": "2026-10-08", "term": "TISA", "suggestions": []},
    ],
    "auto_added": [],
    "failures": [{"category": "反爬蟲擋下", "source": "工商時報", "target": "x", "message": "403"}],
    "needs_attention": ["工商時報「工商時報搜尋頁」被反爬蟲擋下"],
    "terms": [{"source": "工商時報", "term": "TISA", "found": 2, "error": None},
              {"source": "經濟日報", "term": "TISA", "found": 0, "error": "[逾時] x"}],
}
ENV = {"SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587", "SMTP_USER": "bot@example.com",
       "SMTP_PASSWORD": "pw", "MAIL_TO": "a@example.com, b@example.com"}
GH = {"GITHUB_REPOSITORY": "Grace310368/newsfetch", "GITHUB_RUN_ID": "42", "GITHUB_REF_NAME": "main"}


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, pw):
        self.calls.append(("login", user))

    def send_message(self, msg):
        FakeSMTP.sent.append((self, msg))


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent = []
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", FakeSMTP)
    for k, v in GH.items():
        monkeypatch.setenv(k, v)
    return FakeSMTP


@pytest.fixture
def dirs(tmp_path):
    logs, data = tmp_path / "logs", tmp_path / "data"
    logs.mkdir(), data.mkdir()
    (logs / "2026-10-08-report.json").write_text(json.dumps(REPORT, ensure_ascii=False), encoding="utf-8")
    (data / "pending.json").write_text(json.dumps([{}] * 7), encoding="utf-8")
    (data / "keywords.json").write_text(json.dumps({"suggestions": [{}, {}]}), encoding="utf-8")
    return logs, data


def test_success_email(smtp, dirs):
    assert notify.notify_run("2026-10-08", "success", *dirs, env=ENV)
    server, msg = smtp.sent[0]
    assert (server.host, server.port) == ("smtp.example.com", 587)
    assert server.calls == ["starttls", ("login", "bot@example.com")]
    assert msg["Subject"] == "【新聞觀測站】10/8 新增 2 則待審核（有項目需要檢視）"
    assert msg["To"] == "a@example.com, b@example.com"
    text = msg.get_body(("plain",)).get_content()
    assert "目前共 7 則待處理" in text and "關鍵字學習：2 項建議" in text
    assert "工商時報：關鍵字 1/1 個成功" in text and "經濟日報：關鍵字 0/1 個成功" in text
    assert "https://grace310368.github.io/newsfetch/#review" in text
    assert "https://github.com/Grace310368/newsfetch/actions/runs/42" in text
    body = msg.get_body(("html",)).get_content()
    assert "台股&lt;收盤&gt;" in body and "規則未命中" in body


def test_failure_email_and_missing_report(smtp, tmp_path):
    assert notify.notify_run("2026-10-08", "failure", env=ENV)
    assert smtp.sent[-1][1]["Subject"] == "【新聞觀測站】10/8 每日爬蟲執行失敗"
    # 報告不存在也當作失敗通知
    assert notify.notify_run("2026-10-08", "success", tmp_path, tmp_path, env=ENV)
    assert "執行失敗" in smtp.sent[-1][1]["Subject"]


def test_ssl_port(smtp, dirs):
    notify.notify_run("2026-10-08", "success", *dirs, env={**ENV, "SMTP_PORT": "465"})
    assert smtp.sent[0][0].calls == [("login", "bot@example.com")]  # 465 不需 starttls


def test_skip_when_not_configured(smtp, dirs):
    assert notify.notify_run("2026-10-08", "success", *dirs, env={}) is False
    assert smtp.sent == []
