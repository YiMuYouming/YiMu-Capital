"""test_db_lifecycle.py — SQLite 连接生命周期测试 (HM-G0-R3)

验证：
1. close_conn() 关闭连接并清空 thread-local
2. HTTP handler 不会线性积累连接
3. log_pnl_snapshot 成功/incomplete 路径释放连接
4. run_closing_anchor 成功/异常路径释放连接（注入 temp pnl_history_path）
5. run_morning_health_check 锚点存在/缺失路径释放连接（ROOT 隔离到 temp）
6. trigger_llm_auto early-return / insert_llm 抛错路径释放连接（LLM_INSIGHTS_FILE 隔离到 temp）
"""
import io
import json
import threading
import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import scripts.db as db
import scripts.bridge as bridge


class DBCloseConnTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        db.DB_PATH = Path(self.tmp.name) / "test.db"
        db._local = threading.local()
        db.init_db()

    def tearDown(self):
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        self.tmp.cleanup()

    def test_close_conn_closes_connection(self):
        conn1 = db.get_conn()
        self.assertIsNotNone(getattr(db._local, 'conn', None))
        db.close_conn()
        self.assertIsNone(getattr(db._local, 'conn', None))

    def test_get_conn_after_close_reopens(self):
        conn1 = db.get_conn()
        conn1_id = id(conn1)
        db.close_conn()
        conn2 = db.get_conn()
        self.assertNotEqual(id(conn2), conn1_id)

    def test_close_conn_idempotent(self):
        db.get_conn()
        db.close_conn()
        db.close_conn()
        self.assertIsNone(getattr(db._local, 'conn', None))

    def test_multiple_threads_independent_connections(self):
        results = {}

        def worker(thread_id):
            conn = db.get_conn()
            results[thread_id] = id(conn)
            db.close_conn()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 4)
        self.assertEqual(len(set(results.values())), 4)


# ── Handler 连接释放测试 ────────────────────────────────────────────────────────

class HandlerConnectionReleaseTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        self.orig_inited = bridge._db_inited
        db.DB_PATH = Path(self.tmp.name) / "test.db"
        db._local = threading.local()
        bridge._db_inited = False
        db.init_db()
        db.insert_trade({
            "trade_date": "2026-05-26", "trade_time": "09:32",
            "action": "买入", "code": "000001", "name": "测试",
            "price": 10.0, "qty": 100,
        })

    def tearDown(self):
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        bridge._db_inited = self.orig_inited
        self.tmp.cleanup()

    def _mock_handler(self, method, path, body_bytes=b""):
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
        handler.headers.get = lambda k, d=None: str(len(body_bytes) if body_bytes is not None else 0)
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
        return handler

    def test_get_trades_releases_connection(self):
        self._mock_handler("GET", "/api/trades")
        self.assertIsNone(getattr(db._local, 'conn', None))

    def test_get_pnl_releases_connection(self):
        self._mock_handler("GET", "/api/pnl?range=today")
        self.assertIsNone(getattr(db._local, 'conn', None))

    def test_get_pnl_summary_releases_connection(self):
        self._mock_handler("GET", "/api/pnl/summary")
        self.assertIsNone(getattr(db._local, 'conn', None))

    def test_get_account_state_releases_connection(self):
        self._mock_handler("GET", "/api/account/state")
        self.assertIsNone(getattr(db._local, 'conn', None))

    def test_get_correct_returns_405_releases_connection(self):
        self._mock_handler("GET", "/api/account/correct")
        self.assertIsNone(getattr(db._local, 'conn', None))

    def test_post_correct_releases_connection(self):
        payload = json.dumps({
            "original_trade_id": 1,
            "correction_action": "卖出",
            "correction_price": 11.0,
            "correction_qty": 50,
            "note": "测试",
        }).encode()
        self._mock_handler("POST", "/api/account/correct", body_bytes=payload)
        self.assertIsNone(getattr(db._local, 'conn', None))


# ── log_pnl_snapshot 连接释放测试 ─────────────────────────────────────────────

class PnLSnapshotConnectionReleaseTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        self.orig_inited = bridge._db_inited
        db.DB_PATH = Path(self.tmp.name) / "test.db"
        db._local = threading.local()
        bridge._db_inited = False
        db.init_db()

    def tearDown(self):
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        bridge._db_inited = self.orig_inited
        self.tmp.cleanup()

    def test_log_pnl_snapshot_releases_connection_on_success(self):
        from scripts.collectors import quotes

        db.insert_account_baseline({
            "date": "2026-05-26",
            "effective_at": "2026-05-26T09:30:00",
            "trade_id_cutoff": 0,
            "cash": 100000,
            "day_start_asset": 100000,
            "total_deposit": 100000,
            "positions": [],
            "source": "recovery",
        })

        quotes.CACHE["live_quotes"] = {}
        quotes.CACHE["live_index"] = {}

        quotes.log_pnl_snapshot(force=True)
        self.assertIsNone(getattr(db._local, 'conn', None))

    def test_log_pnl_snapshot_releases_connection_on_incomplete(self):
        from scripts.collectors import quotes

        quotes.CACHE["live_quotes"] = {}
        quotes.CACHE["live_index"] = {}

        quotes.log_pnl_snapshot(force=True)
        self.assertIsNone(getattr(db._local, 'conn', None))


# ── 收盘锚点回调连接释放测试 ───────────────────────────────────────────────────

class ClosingAnchorCallbackTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        self.orig_inited = bridge._db_inited
        self.orig_root = bridge.ROOT
        db.DB_PATH = self.tmp_dir / "test.db"
        db._local = threading.local()
        bridge._db_inited = False
        db.init_db()
        # ROOT 指向 temp，防止 pnl_history 落到真实 data/
        bridge.ROOT = self.tmp_dir

    def tearDown(self):
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        bridge._db_inited = self.orig_inited
        bridge.ROOT = self.orig_root
        self.tmp.cleanup()

    def test_closing_anchor_success_releases_connection(self):
        db.insert_account_baseline({
            "date": "2026-05-26",
            "effective_at": "2026-05-26T09:30:00",
            "trade_id_cutoff": 0,
            "cash": 100000,
            "day_start_asset": 100000,
            "total_deposit": 100000,
            "positions": [],
            "source": "recovery",
        })

        # 注入 temp pnl_history_path
        tmp_history = self.tmp_dir / "pnl_history.json"
        bridge.run_closing_anchor(quotes={}, pnl_history_path=tmp_history)

        self.assertIsNone(getattr(db._local, 'conn', None))

    def test_closing_anchor_exception_releases_connection(self):
        tmp_history = self.tmp_dir / "pnl_history.json"
        bridge.run_closing_anchor(quotes={}, pnl_history_path=tmp_history)

        self.assertIsNone(getattr(db._local, 'conn', None))


# ── 日初健康检查回调连接释放测试 ───────────────────────────────────────────────

class MorningHealthCheckCallbackTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        self.orig_inited = bridge._db_inited
        self.orig_root = bridge.ROOT
        db.DB_PATH = self.tmp_dir / "test.db"
        db._local = threading.local()
        bridge._db_inited = False
        bridge.ROOT = self.tmp_dir
        db.init_db()

    def tearDown(self):
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        bridge._db_inited = self.orig_inited
        bridge.ROOT = self.orig_root
        self.tmp.cleanup()

    def test_morning_health_anchor_exists_releases_connection(self):
        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        db.insert_account_baseline({
            "date": today,
            "effective_at": f"{today}T09:30:00",
            "trade_id_cutoff": 0,
            "cash": 100000,
            "day_start_asset": 100000,
            "total_deposit": 100000,
            "positions": [],
            "source": "recovery",
        })

        bridge.run_morning_health_check()

        self.assertIsNone(getattr(db._local, 'conn', None))

    def test_morning_health_no_anchor_releases_connection(self):
        bridge.run_morning_health_check()

        self.assertIsNone(getattr(db._local, 'conn', None))


# ── LLM 自动研判回调连接释放测试 ──────────────────────────────────────────────

class LLMAutoTriggerCallbackTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        self.orig_inited = bridge._db_inited
        self.orig_data_file = bridge.DATA_FILE
        self.orig_llm_file = bridge.LLM_INSIGHTS_FILE
        self.orig_root = bridge.ROOT
        db.DB_PATH = self.tmp_dir / "test.db"
        db._local = threading.local()
        bridge._db_inited = False
        db.init_db()

        # 全部文件路径隔离到 temp
        self.tmp_data = self.tmp_dir / "dashboard_data.json"
        self.tmp_data.write_text(json.dumps({"positions": [], "decision": {}}))
        bridge.DATA_FILE = self.tmp_data

        self.tmp_llm = self.tmp_dir / "llm_insights.json"
        bridge.LLM_INSIGHTS_FILE = self.tmp_llm

        bridge.ROOT = self.tmp_dir

    def tearDown(self):
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        bridge._db_inited = self.orig_inited
        bridge.DATA_FILE = self.orig_data_file
        bridge.LLM_INSIGHTS_FILE = self.orig_llm_file
        bridge.ROOT = self.orig_root
        self.tmp.cleanup()

    @patch("scripts.bridge._call_llm_api")
    def test_llm_auto_api_failure_early_return_releases_connection(self, mock_api):
        mock_api.return_value = {"ok": False, "error": "simulated API error"}

        with patch("scripts.bridge.datetime") as mock_dt:
            mock_dt.now.return_value = __import__("datetime").datetime(2026, 5, 26, 10, 0, 0)
            mock_dt.strftime = __import__("datetime").datetime.strftime
            bridge.trigger_llm_auto()

        self.assertIsNone(getattr(db._local, 'conn', None))

    def test_llm_auto_insert_error_releases_connection(self):
        with patch("scripts.db.insert_llm", side_effect=RuntimeError("simulated insert error")), \
             patch("scripts.bridge._call_llm_api", return_value={"ok": True, "text": '{"text":"test","signals":[]}'}), \
             patch("scripts.bridge.datetime") as mock_dt:
            mock_dt.now.return_value = __import__("datetime").datetime(2026, 5, 26, 10, 0, 0)
            mock_dt.strftime = __import__("datetime").datetime.strftime
            bridge.trigger_llm_auto()

        self.assertIsNone(getattr(db._local, 'conn', None))


class BrokenPipeReleaseTest(unittest.TestCase):
    """验证各 DB 路径在 BrokenPipeError 后连接释放"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        self.orig_inited = bridge._db_inited
        self.orig_root = bridge.ROOT
        self.orig_data = bridge.DATA_FILE
        self.orig_llm = bridge.LLM_INSIGHTS_FILE
        db.DB_PATH = self.tmp_dir / "test.db"
        db._local = threading.local()
        bridge._db_inited = False
        bridge.ROOT = self.tmp_dir
        bridge.DATA_FILE = self.tmp_dir / "dash.json"
        bridge.DATA_FILE.write_text(
            '{"meta":{"date":"2026-05-26"},"market":{},"sentiment":{},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{},"pnl":{},"style":{"总分":59,"连板占比":54,"趋势占比":46}}'
        )
        bridge.LLM_INSIGHTS_FILE = self.tmp_dir / "llm_insights.json"
        db.init_db()
        db.insert_trade({
            "trade_date": "2026-05-26", "trade_time": "09:32",
            "action": "买入", "code": "000001", "name": "测试",
            "price": 10.0, "qty": 100,
        })

    def tearDown(self):
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        bridge._db_inited = self.orig_inited
        bridge.ROOT = self.orig_root
        bridge.DATA_FILE = self.orig_data
        bridge.LLM_INSIGHTS_FILE = self.orig_llm
        self.tmp.cleanup()

    def _handler_with_broken_write(self, method, path, body_bytes=b""):
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
        handler.headers.get = lambda k, d=None: str(len(body_bytes) if body_bytes is not None else 0)
        handler.log_message = MagicMock()
        handler._resp_status = None
        handler._resp_headers = []
        handler._resp_body = b""

        def msr(code, phrase=None): handler._resp_status = code
        def msh(key, value): handler._resp_headers.append((key, value))
        def meh(): pass
        # wfile.write raises BrokenPipeError — exactly what happens on client disconnect
        def broken_write(self_data, data):
            raise BrokenPipeError()
        handler.send_response = msr
        handler.send_header = msh
        handler.end_headers = meh
        handler.wfile = type("WFile", (), {"write": broken_write})()

        method_func = getattr(handler, f"do_{method}", None)
        if method_func:
            try:
                method_func()
            except BrokenPipeError:
                pass
        return handler

    def test_broken_pipe_pnl_releases(self):
        self._handler_with_broken_write("GET", "/api/pnl?range=today")
        self.assertIsNone(getattr(db._local, "conn", None))

    def test_broken_pipe_pnl_summary_releases(self):
        self._handler_with_broken_write("GET", "/api/pnl/summary")
        self.assertIsNone(getattr(db._local, "conn", None))

    def test_broken_pipe_account_state_releases(self):
        self._handler_with_broken_write("GET", "/api/account/state")
        self.assertIsNone(getattr(db._local, "conn", None))

    def test_broken_pipe_trades_releases(self):
        self._handler_with_broken_write("GET", "/api/trades")
        self.assertIsNone(getattr(db._local, "conn", None))

    def test_broken_pipe_sync_releases(self):
        payload = json.dumps({
            "今日操作": [{"时间": "09:32", "动作": "买入", "代码": "002463",
                        "标的": "测试", "价格": 10.0, "数量": 100}],
        }).encode()
        self._handler_with_broken_write("POST", "/api/sync", body_bytes=payload)
        self.assertIsNone(getattr(db._local, "conn", None))

    def test_broken_pipe_llm_releases(self):
        payload = json.dumps({"mode": "auto", "node": "09:40:00"}).encode()
        with patch("scripts.bridge._call_llm_api",
                   return_value={"ok": True, "text": '{"text":"test","signals":[]}'}):
            self._handler_with_broken_write("POST", "/api/llm", body_bytes=payload)
        self.assertIsNone(getattr(db._local, "conn", None))

    def test_llm_api_failure_releases_connection(self):
        """LLM API 失败 return 后连接必须释放"""
        payload = json.dumps({"mode": "auto", "node": "09:40:00"}).encode()

        handler = object.__new__(bridge.BridgeHandler)
        handler.request = MagicMock()
        handler.command = "POST"
        handler.requestline = "POST /api/llm HTTP/1.1"
        handler.path = "/api/llm"
        handler.request_version = "HTTP/1.1"
        handler.request.version = "HTTP/1.1"
        handler.client_address = ("127.0.0.1", 12345)
        handler.server = MagicMock()
        handler.rfile = io.BytesIO(payload)
        handler.headers = MagicMock()
        handler.headers.get = lambda k, d=None: str(len(payload) if payload is not None else 0)
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

        with patch("scripts.bridge._call_llm_api",
                   return_value={"ok": False, "error": "simulated API failure"}):
            do_post = getattr(handler, "do_POST", None)
            try:
                do_post()
            except Exception:
                pass

        self.assertIsNone(getattr(db._local, "conn", None),
                          "API 失败 return 后连接必须释放")

    def test_llm_handler_does_not_write_real_insights_file(self):
        """Broken pipe LLM POST 不写入真实 data/llm_insights.json"""
        import hashlib
        real_llm = self.orig_llm
        h_before = None
        if real_llm.exists():
            h_before = hashlib.sha256(real_llm.read_bytes()).hexdigest()

        payload = json.dumps({"mode": "auto", "node": "09:40:00"}).encode()
        with patch("scripts.bridge._call_llm_api",
                   return_value={"ok": True, "text": '{"text":"test","signals":[]}'}):
            self._handler_with_broken_write("POST", "/api/llm", body_bytes=payload)

        if h_before is not None and real_llm.exists():
            h_after = hashlib.sha256(real_llm.read_bytes()).hexdigest()
            self.assertEqual(h_before, h_after,
                             "真实 data/llm_insights.json 不应被测试修改")


if __name__ == "__main__":
    unittest.main()
