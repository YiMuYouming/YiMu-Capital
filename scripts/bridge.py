#!/usr/bin/env python3
"""bridge.py — 看板 ↔ JSON 桥接服务
在看板目录运行: python3 scripts/bridge.py
然后浏览器打开 http://localhost:8080
W15 记流水时自动 POST 到 /api/sync，实时写入 JSON
"""

import json, os, sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data/dashboard_data.json"

class BridgeHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_POST(self):
        if self.path == '/api/sync':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
                # 合并写入：读现有 JSON → 覆盖 positions + 今日操作 → 写回
                if DATA_FILE.exists():
                    with open(DATA_FILE) as f:
                        data = json.load(f)
                else:
                    data = {}

                if 'positions' in payload:
                    data['positions'] = payload['positions']
                if '今日操作' in payload:
                    if 'decision' not in data:
                        data['decision'] = {}
                    data['decision']['今日操作'] = payload['今日操作']

                with open(DATA_FILE, 'w') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True}).encode())
                print(f"  [bridge] Synced {len(body)} bytes → {DATA_FILE}")
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
                print(f"  [bridge] Error: {e}")
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        if args and hasattr(args[0], 'startswith'):
            if args[0].startswith('GET /api/') or args[0].startswith('POST /api/'):
                print(f"  [{self.log_date_time_string()}] {args[0]}")

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = HTTPServer(('', port), BridgeHandler)
    print(f'[bridge] 看板桥接服务启动 → http://localhost:{port}')
    print(f'[bridge] W15 记流水自动同步到 {DATA_FILE}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n[bridge] 已停止')
