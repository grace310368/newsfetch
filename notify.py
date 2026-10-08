#!/usr/bin/env python3
"""每日爬蟲完成後寄送 Email 通知（GitHub Actions 在爬蟲之後呼叫）。

    python notify.py                       # 依今天的執行報告寄出摘要
    python notify.py --date 2026-10-08
    python notify.py --status failure      # 爬蟲失敗時寄出失敗通知
SMTP 設定見 newsfetch/notify.py；未設定時直接略過，不會讓 workflow 失敗。
寄信本身失敗（帳密錯誤等）時結束碼為 1，會在 Actions 上顯示紅色，方便發現設定問題。
"""
from __future__ import annotations

import argparse
import smtplib
import sys

from newsfetch import db
from newsfetch.notify import notify_run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="執行日期 YYYY-MM-DD（預設台灣時間今天）")
    ap.add_argument("--status", default="success", choices=["success", "failure"])
    args = ap.parse_args(argv)
    try:
        notify_run(args.date or db.today(), args.status)
    except (smtplib.SMTPException, OSError) as e:
        print(f"Email 寄送失敗：{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
