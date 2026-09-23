#!/usr/bin/env python3
"""批次套用審核結果（GitHub Pages 模式下由 review-apply workflow 呼叫）。

輸入為 JSON 陣列，每個元素是一個操作（格式見 newsfetch/review.py 的 apply_op）：
    python apply_review.py --ops '[{"type":"delete","id":3,"reason":"雜訊"}]'
    python apply_review.py --file ops.json
套用後會重新輸出前端 JSON，並把結果寫到 logs/review-YYYY-MM-DD.log。
任何一筆失敗都會在結束碼反映（1），但其他成功的操作仍會保留。
"""
from __future__ import annotations

import argparse
import json
import sys

from newsfetch import config, db, export
from newsfetch.review import apply_ops


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--ops", help="JSON 字串")
    src.add_argument("--file", help="JSON 檔案路徑")
    args = ap.parse_args(argv)

    raw = args.ops if args.ops is not None else open(args.file, encoding="utf-8").read()
    ops = json.loads(raw)
    if isinstance(ops, dict):
        ops = ops.get("ops", [ops])

    conn = db.connect()
    results = apply_ops(conn, ops)
    export.export_all(conn)

    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = config.LOG_DIR / f"review-{db.today()}.log"
    with log.open("a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps({"at": db.now_iso(), **r}, ensure_ascii=False) + "\n")

    failed = [r for r in results if not r["ok"]]
    for r in results:
        mark = "成功" if r["ok"] else f"失敗：{r['error']}"
        print(f"- {r['op'].get('type')} {r['op'].get('id') or r['op'].get('url', '')} → {mark}")
    print(f"共 {len(results)} 筆，成功 {len(results) - len(failed)}，失敗 {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
