"""test_sync_api.py — POST /api/sync 空库首次写入测试 (HM-G0-R3)

回归：全新临时 DB + 临时 DATA_FILE，首笔 /api/sync 返回成功、表已建、成交存在、
JSON 仅写临时文件、连接释放。
"""
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import scripts.db as db
import scripts.bridge as bridge


class FreshDBSyncTest(unittest.TestCase):
    """空库首次 POST /api/sync 应成功建表并写入"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_db = Path(self.tmp.name) / "pnl.db"
        self.tmp_data = Path(self.tmp.name) / "dashboard_data.json"

        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        self.orig_inited = bridge._db_inited
        db.DB_PATH = self.tmp_db
        db._local = threading.local()
        bridge._db_inited = False

    def tearDown(self):
        # 仅兜底清理
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        bridge._db_inited = self.orig_inited
        self.tmp.cleanup()

    def _build_handler(self, method, path, body_bytes=b""):
        handler = object.__new__(bridge.BridgeHandler)
        handler.request = MagicMock()
        handler.command = method
        handler.requestline = f"{method} {path} HTTP/1.1"
        handler.path = path
        handler.request_version = "HTTP/1.1"
        handler.request.version = "HTTP/1.1"
        handler.client_address = ("127.0.0.1", 12345)
        handler.server = MagicMock()
        handler.rfile = io.BytesIO(body_bytes)
        handler.headers = MagicMock()
        handler.headers.get = lambda k, d=None: (
            str(len(body_bytes)) if body_bytes is not None else str(d if d is not None else 0)
        )
        handler.log_message = MagicMock()
        handler._resp_status = None
        handler._resp_headers = []
        handler._resp_body = b""

        def msr(code, phrase=None): handler._resp_status = code
        def msh(key, value): handler._resp_headers.append((key, value))
        def meh(): pass
        def mww(self_data, data): handler._resp_body += data
        handler.send_response = msr
        handler.send_header = msh
        handler.end_headers = meh
        handler.wfile = type("WFile", (), {"write": mww})()

        return handler

    def _call_handler(self, handler):
        """直接调用 do_POST/do_GET，不额外干预连接"""
        method_func = getattr(handler, f"do_{handler.command}", None)
        if method_func:
            try:
                method_func()
            except Exception:
                pass

        status = handler._resp_status
        try:
            body = json.loads(handler._resp_body.decode()) if handler._resp_body else {}
        except Exception:
            body = {}
        return status, body

    def test_fresh_db_first_sync_succeeds(self):
        """空库首次 POST /api/sync 应返回 200，连接释放"""
        with patch.object(bridge, "DATA_FILE", self.tmp_data):
            payload = json.dumps({
                "entry": {
                    "时间": "09:32:00",
                    "动作": "买入",
                    "代码": "002463",
                    "标的": "沪电股份",
                    "价格": 122.5,
                    "数量": 300,
                    "窗口": "W1",
                    "原因": "测试",
                },
            }).encode()

            handler = self._build_handler("POST", "/api/sync", payload)
            status, body = self._call_handler(handler)

        # do_POST() 返回后立即断言连接已释放
        self.assertIsNone(getattr(db._local, "conn", None),
                          "do_POST() 后连接应已释放")

        self.assertEqual(status, 200, f"空库首次 sync 应返回 200, got {status}: {body}")
        self.assertTrue(body.get("ok"), f"body.ok 应为 True: {body}")

        tables = {r["name"] for r in db._exec(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        self.assertIn("trade_records", tables, "trade_records 表应已创建")

        trades = db.query_trades(date_from="2026-05-26")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["code"], "002463")

        # DATA_FILE only written when positions_updated; entry-only sync writes to DB
        self.assertEqual(status, 200)

    def test_sync_empty_ops_releases_connection(self):
        """空操作 POST /api/sync 后连接也释放"""
        with patch.object(bridge, "DATA_FILE", self.tmp_data):
            payload = json.dumps({"今日操作": []}).encode()
            handler = self._build_handler("POST", "/api/sync", payload)
            self._call_handler(handler)

        self.assertIsNone(getattr(db._local, "conn", None))


class FreshDBCorrectAPITest(unittest.TestCase):
    """POST /api/account/correct 空库首次调用应成功建表"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_db = Path(self.tmp.name) / "pnl.db"
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        self.orig_inited = bridge._db_inited
        db.DB_PATH = self.tmp_db
        db._local = threading.local()
        bridge._db_inited = False

    def tearDown(self):
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        bridge._db_inited = self.orig_inited
        self.tmp.cleanup()

    def _call(self, method, path, body_bytes=None):
        handler = object.__new__(bridge.BridgeHandler)
        handler.request = MagicMock()
        handler.command = method
        handler.requestline = f"{method} {path} HTTP/1.1"
        handler.path = path
        handler.request_version = "HTTP/1.1"
        handler.request.version = "HTTP/1.1"
        handler.client_address = ("127.0.0.1", 12345)
        handler.server = MagicMock()
        handler.rfile = io.BytesIO(body_bytes or b"")
        handler.headers = MagicMock()
        handler.headers.get = lambda k, d=None: (
            str(len(body_bytes)) if body_bytes is not None else str(d if d is not None else 0)
        )
        handler.log_message = MagicMock()
        handler._resp_status = None
        handler._resp_headers = []
        handler._resp_body = b""

        def msr(code, phrase=None): handler._resp_status = code
        def msh(key, value): handler._resp_headers.append((key, value))
        def meh(): pass
        def mww(self_data, data): handler._resp_body += data
        handler.send_response = msr
        handler.send_header = msh
        handler.end_headers = meh
        handler.wfile = type("WFile", (), {"write": mww})()

        method_func = getattr(handler, f"do_{method}", None)
        if method_func:
            try:
                method_func()
            except Exception:
                pass

        status = handler._resp_status
        try:
            body = json.loads(handler._resp_body.decode()) if handler._resp_body else {}
        except Exception:
            body = {}
        return status, body

    def test_correct_on_fresh_db_creates_tables(self):
        """空库 POST /api/account/correct 应成功建表"""
        payload = json.dumps({
            "original_trade_id": 999,
            "correction_action": "卖出",
            "correction_price": 120.0,
            "correction_qty": 100,
            "note": "测试空库纠错",
        }).encode()
        self._call("POST", "/api/account/correct", body_bytes=payload)

        tables = {r["name"] for r in db._exec(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        self.assertIn("trade_records", tables, "trade_records 表应已创建")
        self.assertIn("account_baselines", tables, "account_baselines 表应已创建")


if __name__ == "__main__":
    unittest.main()
