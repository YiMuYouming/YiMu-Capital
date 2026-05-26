"""test_correct_api.py — /api/account/correct 方法契约测试（HM-G0B）

验证：
1. GET /api/account/correct → 405 Method Not Allowed（不写数据库）
2. POST /api/account/correct 无 body → 400 Bad Request
3. POST /api/account/correct 非法参数 → 400
4. POST /api/account/correct 有效参数 → 200 + 新增冲销记录
"""
import json
import unittest
import tempfile
import threading
import io
from pathlib import Path
from unittest.mock import MagicMock

import scripts.db as db
import scripts.bridge as bridge


class CorrectAPIHTTPTest(unittest.TestCase):
    """使用 mock 测试 API 方法契约（不启动真实服务器）"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        db.DB_PATH = Path(self.tmp.name) / "test.db"
        db._local = threading.local()
        db.init_db()

        # 插入一条原始成交
        db.insert_trade({
            "trade_date": "2026-05-26",
            "trade_time": "09:32",
            "action": "买入",
            "code": "002463",
            "name": "沪电股份",
            "price": 122.5,
            "qty": 300,
        })

    def tearDown(self):
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        self.tmp.cleanup()

    def _call(self, method, path, body_bytes=None):
        """直接调用 BridgeHandler 的 do_GET / do_POST，override send_response 系列方法避免 Python 3.14 内部依赖"""
        handler = object.__new__(bridge.BridgeHandler)
        handler.request = MagicMock()
        handler.command = method
        handler.requestline = f"{method} {path} HTTP/1.1"
        handler.path = path
        handler.request.version = "HTTP/1.1"
        handler.client_address = ("127.0.0.1", 12345)
        handler.server = MagicMock()
        handler.rfile = io.BytesIO(body_bytes or b"")
        handler.headers = MagicMock()
        handler.headers.get = lambda k, d=None: (
            str(len(body_bytes)) if body_bytes is not None else str(d if d is not None else 0)
        )
        handler.log_message = MagicMock()

        # Override HTTP response methods to capture output without BytesIO Python 3.14 compat issues
        handler._resp_status = None
        handler._resp_headers = []
        handler._resp_body = b""

        def mock_send_response(code, phrase=None):
            handler._resp_status = code
        def mock_send_header(key, value):
            handler._resp_headers.append((key, value))
        def mock_end_headers():
            pass
        def mock_wfile_write(self_data, data):
            handler._resp_body += data
        handler.send_response = mock_send_response
        handler.send_header = mock_send_header
        handler.end_headers = mock_end_headers
        # 直接赋给 handler.wfile，不用 BytesIO
        handler.wfile = type("WFile", (), {"write": mock_wfile_write})()

        method_func = getattr(handler, f"do_{method}", None)
        if method_func:
            try:
                method_func()
            except Exception:
                pass

        status_code = handler._resp_status
        try:
            body_dict = json.loads(handler._resp_body.decode()) if handler._resp_body else {}
        except Exception:
            body_dict = {}

        return status_code, body_dict

    def test_get_correct_returns_405(self):
        """GET /api/account/correct → 405 Method Not Allowed"""
        status, body = self._call("GET", "/api/account/correct")
        self.assertEqual(status, 405, f"GET 应返回 405，实际 {status}: {body}")

    def test_get_correct_does_not_write_db(self):
        """GET /api/account/correct 不写数据库"""
        trades_before = db.query_trades(date_from="2026-05-26")
        count_before = len(trades_before)
        self._call("GET", "/api/account/correct")
        trades_after = db.query_trades(date_from="2026-05-26")
        self.assertEqual(len(trades_after), count_before, "GET 不应写入数据库")

    def test_post_correct_no_body_returns_400(self):
        """POST /api/account/correct 无 body → 400"""
        status, body = self._call("POST", "/api/account/correct", body_bytes=b"")
        self.assertEqual(status, 400, f"POST 无 body 应返回 400，实际 {status}: {body}")

    def test_post_correct_missing_id_returns_400(self):
        """POST /api/account/correct 缺 original_trade_id → 400"""
        payload = json.dumps({"note": "test"}).encode()
        status, body = self._call("POST", "/api/account/correct", body_bytes=payload)
        self.assertEqual(status, 400, f"POST 缺 id 应返回 400，实际 {status}: {body}")

    def test_post_correct_valid_creates_correction(self):
        """POST /api/account/correct 有效参数 → 200 + 新增冲销记录"""
        # 验证初始状态
        trades_before = db.query_trades(date_from="2026-05-26")
        self.assertEqual(len(trades_before), 1)

        payload = json.dumps({
            "original_trade_id": 1,
            "correction_action": "卖出",
            "correction_price": 120.0,
            "correction_qty": 100,
            "note": "测试纠错",
        }).encode()
        status, body = self._call("POST", "/api/account/correct", body_bytes=payload)

        self.assertEqual(status, 200, f"POST 有效应返回 200，实际 {status}: {body}")
        self.assertTrue(body.get("ok"), f"body.ok 应为 True: {body}")
        self.assertIsNotNone(body.get("correction_trade_id"))

        # 验证纠错记录已写入
        trades_after = db.query_trades(date_from="2026-05-26")
        self.assertEqual(len(trades_after), 2, f"应新增 1 条冲销记录: {trades_after}")
        reversal = next((t for t in trades_after if t["is_reversal"] == 1), None)
        self.assertIsNotNone(reversal, f"应有 is_reversal=1 的冲销记录: {trades_after}")
        self.assertEqual(reversal["reversal_of_id"], 1)


if __name__ == "__main__":
    unittest.main()
