import json
import threading
import unittest
import urllib.request
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

        with urllib.request.urlopen(f"http://127.0.0.1:{proxy.server_port}/api/trade/tickets", timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(resp.status, 200)
        self.assertEqual(body, {"tickets": []})


if __name__ == "__main__":
    unittest.main()
