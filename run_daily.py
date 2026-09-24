#!/usr/bin/env python3
"""每日排程入口（GitHub Actions 呼叫）：爬蟲 → 寫入待審核佇列 → 輸出前端 JSON → 執行報告。

用法：
    python run_daily.py                 # 正常執行
    python run_daily.py --date 2026-09-15
    python run_daily.py --terms TISA 亞資中心   # 只跑指定關鍵字（除錯用）
    python run_daily.py --export-only   # 只重新輸出 JSON
"""
from __future__ import annotations

import argparse
import sys

from newsfetch import db, export, keyword_learning
from newsfetch.crawler import run_crawl
from newsfetch.run_report import write_report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="執行日期 YYYY-MM-DD（預設台灣時間今天）")
    ap.add_argument("--terms", nargs="*", help="只搜尋指定關鍵字")
    ap.add_argument("--export-only", action="store_true", help="不爬蟲，只重新輸出前端 JSON")
    args = ap.parse_args(argv)

    conn = db.connect()
    if not args.export_only:
        run_date = args.date or db.today()
        result = run_crawl(conn, run_date, terms=args.terms)
        report = write_report(result, learning=keyword_learning.analyze(conn))
        print(f"新增待審核 {len(result.new_pending)} 則，失敗 {len(result.failures)} 筆；報告：{report}")
        for note in result.needs_attention:
            print(f"[需要人工檢視] {note}")
    out = export.export_all(conn)
    print(f"已輸出前端資料：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
