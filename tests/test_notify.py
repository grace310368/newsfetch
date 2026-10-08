import json
import urllib.error

import pytest

from newsfetch import notify

REPORT = {
    "run_date": "2026-10-08",
    "new_pending": [
        {"url": "https://www.ctee.com.tw/news/1-1", "title": "亞資中心新進度", "source": "工商時報",
         "date": "2026-10-08", "term": "亞資中心",
         "suggestions": [{"topic": "亞洲資產管理中心", "subcategory": "政策與法規", "reason": ""}]},
        {"url": "https://money.udn.com/money/story/1/2", "title": "台股[收盤]|大漲", "source": "經濟日報",
         "date": "2026-10-08", "term": "TISA", "suggestions": []},
    ],
    "auto_added": [],
    "failures": [{"category": "反爬蟲擋下", "source": "工商時報", "target": "x", "message": "403"}],
    "needs_attention": ["工商時報「工商時報搜尋頁」被反爬蟲擋下"],
    "terms": [{"source": "工商時報", "term": "TISA", "found": 2, "error": None},
              {"source": "經濟日報", "term": "TISA", "found": 0, "error": "[逾時] x"}],
}
ENV = {"GITHUB_REPOSITORY": "Grace310368/newsfetch", "GITHUB_TOKEN": "t"}


class FakeGitHub:
    def __init__(self, open_issues=(), label_exists=False):
        self.issues = list(open_issues)
        self.label_exists = label_exists
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET":
            return self.issues
        if path == "/labels":
            if self.label_exists:
                raise urllib.error.HTTPError(path, 422, "exists", None, None)
            return {}
        if path == "/issues":
            self.issues.append({"number": 7})
            return {"number": 7}
        return {}

    def comments(self):
        return [(p, b["body"]) for m, p, b in self.calls if p.endswith("/comments")]


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "Grace310368/newsfetch")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    logs, data = tmp_path / "logs", tmp_path / "data"
    logs.mkdir(), data.mkdir()
    (logs / "2026-10-08-report.json").write_text(json.dumps(REPORT, ensure_ascii=False), encoding="utf-8")
    (data / "pending.json").write_text(json.dumps([{}] * 7), encoding="utf-8")
    (data / "keywords.json").write_text(json.dumps({"suggestions": [{}, {}]}), encoding="utf-8")
    return logs, data


def test_first_run_creates_issue_and_comments(dirs):
    gh = FakeGitHub(label_exists=True)
    assert notify.notify_run("2026-10-08", "success", *dirs, env=ENV, gh=gh)
    created = [b for m, p, b in gh.calls if p == "/issues"][0]
    assert created["title"] == "每日爬蟲通知" and "@Grace310368" in created["body"]
    path, body = gh.comments()[0]
    assert path == "/issues/7/comments"
    assert body.startswith("### 10/8 新增 2 則待審核（有項目需要檢視）")
    assert "目前共 **7** 則待處理" in body and "關鍵字學習：2 項建議" in body
    assert "經濟日報：關鍵字 0/1 個成功" in body
    assert "[台股［收盤］｜大漲](https://money.udn.com/money/story/1/2)" in body   # 標題符號不破壞連結
    assert "規則未命中" in body
    assert "(https://grace310368.github.io/newsfetch/#review)" in body
    assert "actions/runs/42" in body
    assert body.rstrip().endswith("@Grace310368")


def test_reuses_open_issue(dirs):
    gh = FakeGitHub(open_issues=[{"number": 3}])
    notify.notify_run("2026-10-08", "success", *dirs, env=ENV, gh=gh)
    assert not [c for c in gh.calls if c[1] == "/issues"]
    assert gh.comments()[0][0] == "/issues/3/comments"


def test_failure_and_missing_report(dirs, tmp_path):
    gh = FakeGitHub(open_issues=[{"number": 3}])
    notify.notify_run("2026-10-08", "failure", env=ENV, gh=gh)
    notify.notify_run("2026-10-08", "success", tmp_path, tmp_path, env=ENV, gh=gh)
    assert all("每日爬蟲執行失敗" in b for _, b in gh.comments())


def test_custom_mention_and_skip_without_token(dirs):
    gh = FakeGitHub(open_issues=[{"number": 3}])
    notify.notify_run("2026-10-08", "success", *dirs, env={**ENV, "NOTIFY_MENTION": "someone"}, gh=gh)
    assert gh.comments()[0][1].endswith("@someone")
    assert notify.notify_run("2026-10-08", "success", *dirs, env={}) is False
