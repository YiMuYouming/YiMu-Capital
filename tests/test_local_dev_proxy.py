import json
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from scripts.ops.local_dev_proxy import LocalDevProxyHandler


class _Cloud404Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"not_found"}')

    def log_message(self, *_args):
        pass


class _CloudDashboardDataHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/data/dashboard_data.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"meta":{"source":"cloud"}}')
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_args):
        pass


def _start_server(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class LocalDevProxyTicketFallbackTest(unittest.TestCase):
    def tearDown(self):
        for srv in getattr(self, "_servers", []):
            srv.shutdown()
            srv.server_close()

    def test_ticket_endpoint_404_falls_back_to_empty_readonly_board(self):
        cloud = _start_server(_Cloud404Handler)
        LocalDevProxyHandler.cloud_base = f"http://127.0.0.1:{cloud.server_port}"
        proxy = _start_server(LocalDevProxyHandler)
        self._servers = [proxy, cloud]

        with urllib.request.urlopen(f"http://127.0.0.1:{proxy.server_port}/api/trade/tickets?date=2026-06-28", timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(resp.status, 200)
        self.assertEqual(body, {"tickets": [], "data_date": "2026-06-28", "date_source": "query_param"})

    def test_ticket_endpoint_404_bare_request_defaults_to_today_metadata(self):
        cloud = _start_server(_Cloud404Handler)
        LocalDevProxyHandler.cloud_base = f"http://127.0.0.1:{cloud.server_port}"
        proxy = _start_server(LocalDevProxyHandler)
        self._servers = [proxy, cloud]

        with urllib.request.urlopen(f"http://127.0.0.1:{proxy.server_port}/api/trade/tickets", timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(resp.status, 200)
        self.assertEqual(body, {
            "tickets": [],
            "data_date": datetime.now().strftime("%Y-%m-%d"),
            "date_source": "default_today",
        })

    def test_dashboard_data_json_is_proxied_to_cloud_when_local_file_missing(self):
        cloud = _start_server(_CloudDashboardDataHandler)
        LocalDevProxyHandler.cloud_base = f"http://127.0.0.1:{cloud.server_port}"
        proxy = _start_server(LocalDevProxyHandler)
        self._servers = [proxy, cloud]

        with tempfile.TemporaryDirectory() as tmp:
            local_file = Path(tmp) / "data" / "dashboard_data.json"
            self.assertFalse(local_file.exists())

            with urllib.request.urlopen(
                f"http://127.0.0.1:{proxy.server_port}/data/dashboard_data.json",
                timeout=5,
            ) as resp:
                body = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(resp.status, 200)
        self.assertEqual(body, {"meta": {"source": "cloud"}})


if __name__ == "__main__":
    unittest.main()
