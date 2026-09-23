#!/usr/bin/env python3
"""本地審核伺服器：提供儀表板靜態檔＋審核 API，審核結果直接寫入 SQLite。

    python serve.py            # http://127.0.0.1:8000
    python serve.py --port 8080

前端偵測到 /api/health 可用時，會切換為「本地模式」，審核操作即時生效；
部署在 GitHub Pages 時則改為把審核結果批次送到 GitHub Actions（見 README）。
只綁定 127.0.0.1，不要對外開放。
"""
from __future__ import annotations

import argparse
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from newsfetch import config, db, export
from newsfetch.review import ReviewError, apply_op

DOCS = config.DOCS_DIR
_lock = threading.Lock()


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 精簡輸出
        if self.path.startswith("/api/"):
            super().log_message(fmt, *args)

    def end_headers(self):
        if self.path.startswith("/data/") or self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/health":
            return self._json(200, {"ok": True, "mode": "local"})
        return super().do_GET()

    def do_POST(self):
        routes = {"/api/review/finalize": "finalize", "/api/review/delete": "delete", "/api/manual-add": "manual_add"}
        kind = routes.get(self.path)
        if not kind:
            return self._json(404, {"ok": False, "error": "not found"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"ok": False, "error": "請求格式錯誤"})
        with _lock:
            conn = db.connect()
            try:
                result = apply_op(conn, {**payload, "type": kind})
                export.export_all(conn)
            except (ReviewError, KeyError, ValueError, TypeError) as e:
                conn.rollback()
                return self._json(400, {"ok": False, "error": str(e)})
            finally:
                conn.close()
        return self._json(200, {"ok": True, **result})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    conn = db.connect()
    export.export_all(conn)
    conn.close()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=str(DOCS)))
    print(f"新聞觀測站（本地審核模式）：http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
