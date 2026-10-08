#!/usr/bin/env python3
"""每日爬蟲完成後通知（GitHub Actions 在爬蟲之後呼叫）。

在 repo 的「每日爬蟲通知」Issue 留言當日摘要並 @ repo 擁有者，GitHub 會寄 Email 通知。
    python notify.py                       # 依今天的執行報告留言摘要
    python notify.py --date 2026-10-08
    python notify.py --status failure      # 爬蟲失敗時留言失敗通知
本機執行（沒有 GITHUB_TOKEN）時直接略過。
"""
from __future__ import annotations

import argparse
import sys
import urllib.error

from newsfetch import db
from newsfetch.notify import notify_run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="執行日期 YYYY-MM-DD（預設台灣時間今天）")
    ap.add_argument("--status", default="success", choices=["success", "failure"])
    args = ap.parse_args(argv)
    try:
        notify_run(args.date or db.today(), args.status)
    except (urllib.error.URLError, OSError) as e:
        print(f"通知失敗：{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
