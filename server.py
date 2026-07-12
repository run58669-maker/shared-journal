# -*- coding: utf-8 -*-
"""共享手账 HTTP 服务器（单文件，零依赖）。

    python server.py [端口, 默认 8789]

  GET  /            → 手账页面
  GET  /journal/data → 当前手账 JSON
  POST /journal/data → 保存（乐观并发：_rev 不符返回 409，旧客户端覆盖不了新数据）

数据落在 data/journal_data.json，每次改动追加 data/journal_history.jsonl。
手机访问：局域网 IP / Tailscale IP + 端口。
"""
import hashlib
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import journal_history
import journal_toc

ROOT = Path(__file__).resolve().parent
HTML = ROOT / "journal.html"
DATA = Path(os.environ.get("JOURNAL_DATA") or (ROOT / "data" / "journal_data.json"))


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/journal"):
            raw = HTML.read_bytes()
            # 带内容指纹重定向，确保前端更新后客户端不吃旧缓存
            build = hashlib.md5(raw).hexdigest()[:8]
            qs = parse_qs(urlparse(self.path).query)
            if qs.get("_b", [""])[0] != build:
                self.send_response(302)
                self.send_header("Location", f"{path}?_b={build}")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if path == "/journal/data":
            body = DATA.read_bytes() if DATA.exists() else b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self):
        if urlparse(self.path).path != "/journal/data":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        # 乐观并发：手机可能拿旧的整本状态回写，_rev 不符一律 409 拒绝，
        # 防止旧缓存吃掉 MCP/桥 刚写的新页
        try:
            incoming = json.loads(raw.decode("utf-8"))
            current = {}
            if DATA.exists():
                current = json.loads(DATA.read_text(encoding="utf-8"))
            current_rev = int(current.get("_rev", 0))
            if int(incoming.get("_rev", 0)) != current_rev:
                self._json({"ok": False, "error": "stale_journal", "rev": current_rev}, 409)
                return
            incoming["_rev"] = current_rev + 1
            incoming["_ts"] = int(time.time() * 1000)
            journal_toc.rebuild(incoming)
            new_raw = json.dumps(incoming, ensure_ascii=False)
        except Exception as e:
            self._json({"ok": False, "error": "invalid_journal", "detail": str(e)}, 400)
            return
        old_raw = DATA.read_text(encoding="utf-8") if DATA.exists() else ""
        journal_history.record(old_raw, new_raw, "frontend")
        DATA.parent.mkdir(parents=True, exist_ok=True)
        DATA.write_text(new_raw, encoding="utf-8")
        self._json({"ok": True, "rev": incoming["_rev"], "ts": incoming["_ts"]})

    def log_message(self, fmt, *args):
        pass  # 安静


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8789
    print(f"shared-journal serving on http://0.0.0.0:{port}  (data: {DATA})")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
