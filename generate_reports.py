#!/usr/bin/env python3
"""月度重點報告／趨勢報告生成（需要環境變數 ANTHROPIC_API_KEY）。

    python generate_reports.py monthly                    # 上個月、全部議題
    python generate_reports.py monthly --month 2026-08 --topic 信任金融   # 重新生成單一月份／議題
    python generate_reports.py trend                      # 全部議題
    python generate_reports.py trend --topic 亞洲資產管理中心
    加上 --dry-run 只印出送給 Claude 的內容，不呼叫 API。
"""
from __future__ import annotations

import argparse
import re
import sys

from newsfetch import config, db, export
from newsfetch.llm_reports import generate_monthly, generate_trend, previous_month


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["monthly", "trend"])
    ap.add_argument("--month", help="YYYY-MM 或 YYYYMM（monthly 用，預設上個月）")
    ap.add_argument("--topic", choices=config.TOPIC_NAMES, help="只處理單一議題")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    topics = [args.topic] if args.topic else config.TOPIC_NAMES
    conn = db.connect()
    errors = 0
    for topic in topics:
        try:
            if args.kind == "monthly":
                month = args.month or previous_month()
                m = re.fullmatch(r"(\d{4})-?(\d{2})", month)
                if not m:
                    ap.error("--month 格式應為 YYYY-MM 或 YYYYMM")
                month = f"{m.group(1)}-{m.group(2)}"
                result = generate_monthly(conn, topic, month, dry_run=args.dry_run)
                label = f"{topic} {month}"
            else:
                result = generate_trend(conn, topic, dry_run=args.dry_run)
                label = topic
        except Exception as e:  # noqa: BLE001 - 單一議題失敗不影響其他議題
            errors += 1
            print(f"[失敗] {topic}：{e}", file=sys.stderr)
            continue
        if result is None:
            print(f"[略過] {label}：資料不足（月度：當月無文章；趨勢：月度報告少於 2 份）")
        elif args.dry_run:
            print(f"===== {label} =====\n{result['prompt']}\n")
        else:
            print(f"[完成] {label}")
    if not args.dry_run:
        export.export_all(conn)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
