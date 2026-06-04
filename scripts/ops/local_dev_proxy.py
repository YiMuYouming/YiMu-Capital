#!/usr/bin/env python3
"""Local read-only dev preview.

Serves frontend files from the local checkout and proxies GET /api/* to the
cloud tunnel on localhost:8088. Mutating HTTP methods are blocked so this page
can be used for UI/code preview without accidentally writing real trades.
"""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import json
import os
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
CLOUD_DATA_PATHS = {
    "/data/auction_snapshot.json",
    "/data/pnl_history.json",
    "/data/sentiment_auto.json",
    "/data/ymwm_report.json",
    "/data/zt_history.json",
}


class LocalDevProxyHandler(SimpleHTTPRequestHandler):
    cloud_base = "http://127.0.0.1:8088"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        if self.path.split("?", 1)[0] in ("/", "/index.html"):
            self.send_header("Clear-Site-Data", '"cache"')
        super().end_headers()

    def do_GET(self):
        request_path = self.path.split("?", 1)[0]
        if self.path.startswith("/api/") or request_path in CLOUD_DATA_PATHS:
            self._proxy_get()
            return
        super().do_GET()

    def do_POST(self):
        self._blocked_write()

    def do_PUT(self):
        self._blocked_write()

    def do_DELETE(self):
        self._blocked_write()

    def _proxy_get(self):
        target = self.cloud_base + self.path
        try:
            with urllib.request.urlopen(target, timeout=10) as response:
                body = response.read()
                self.send_response(response.status)
                self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
        except urllib.error.HTTPError as exc:
            if self.path.split("?", 1)[0] == "/api/trade/tickets" and exc.code == 404:
                self._write_json({"tickets": []}, status=200)
                return
            body = exc.read()
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            self.send_response(502)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({
                "error": "cloud_proxy_unavailable",
                "detail": str(exc),
            }, ensure_ascii=False).encode("utf-8"))

    def _write_json(self, payload, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _blocked_write(self):
        self.send_response(403)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps({
            "error": "readonly_dev_preview",
            "message": "本地开发预览页禁止写入；实盘录入请使用 http://localhost:8088",
        }, ensure_ascii=False).encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Serve local UI with read-only cloud API proxy")
    parser.add_argument("--port", type=int, default=int(os.getenv("YIMU_DEV_PROXY_PORT", "18088")))
    parser.add_argument("--cloud", default=os.getenv("YIMU_DEV_PROXY_CLOUD", "http://127.0.0.1:8088"))
    args = parser.parse_args()

    LocalDevProxyHandler.cloud_base = args.cloud.rstrip("/")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), LocalDevProxyHandler)
    print(f"[local-dev-proxy] local UI: http://127.0.0.1:{args.port}")
    print(f"[local-dev-proxy] GET /api/* and selected /data/*.json -> {LocalDevProxyHandler.cloud_base}")
    print("[local-dev-proxy] POST/PUT/DELETE blocked")
    server.serve_forever()


if __name__ == "__main__":
    main()
