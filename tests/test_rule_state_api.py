"""test_rule_state_api.py — bridge rule_state 契约测试 (Gate 1A)

验证：/api/live/quotes 含 rule_state、SSE 含 rule_state、
_build_full_snapshot 含 rule_state、小数百分数转换、
新增 SSOT 读取的连接释放。
全量隔离：tempfile + mock CACHE，不读/写真实 data/。
"""
import io
import json
import threading
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import scripts.db as db
import scripts.bridge as bridge


class RuleStateBridgeContractTest(unittest.TestCase):
    """bridge 输出契约回归"""

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
        # 隔离所有真实文件路径
        self.tmp_dashboard = self.tmp_dir / "dashboard_data.json"
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-27"},"market":{},"sentiment":{},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{},"pnl":{},"style":{"总分":59,"连板占比":54,"趋势占比":46}}'
        )
        bridge.DATA_FILE = self.tmp_dashboard
        bridge.LLM_INSIGHTS_FILE = self.tmp_dir / "llm_insights.json"
        db.init_db()

        today = datetime.now().strftime("%Y-%m-%d")
        db.insert_account_baseline({
            "date": today, "effective_at": f"{today}T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 100000,
            "total_deposit": 100000, "positions": [], "source": "recovery",
        })

        bridge.CACHE["iwencai"] = {
            "情绪值": 65,
            "昨日涨停收益": 3.0,
            "晋级率": 0.198,
            "炸板率": 0.758,
            "_updated": "2026-05-27T09:40:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {
            "_updated": "2026-05-27T09:39:00+08:00",
        }
        bridge.CACHE["live_index"] = {}
        bridge.CACHE["breadth"] = {}
        bridge.CACHE["hot_list"] = {}

    def tearDown(self):
        bridge.CACHE.clear()
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        bridge._db_inited = self.orig_inited
        bridge.ROOT = self.orig_root
        bridge.DATA_FILE = self.orig_data
        bridge.LLM_INSIGHTS_FILE = self.orig_llm
        self.tmp.cleanup()

    def test_rule_state_function_exists(self):
        """_build_rule_state 可调用且返回契约字段"""
        state = bridge._build_rule_state(now=datetime(2026, 5, 27, 9, 40))
        self.assertEqual(state["version"], "g1a-v1")
        self.assertIn("tradable", state)
        self.assertIn("windows", state)

    def test_cache_decimal_rates_are_converted_to_percent(self):
        """CACHE 中晋级率 0.198、炸板率 0.758 转为百分数 19.8/75.8"""
        state = bridge._build_rule_state(now=datetime(2026, 5, 27, 9, 40))
        codes = [b["code"] for b in state["blocks"]]
        # 75.8% > 30% → W1_BROKEN_BOARD 应触发
        self.assertIn("W1_BROKEN_BOARD", codes,
                      "炸板率 0.758 应转为 75.8% 并触发 W1_BROKEN_BOARD")
        # 晋级率 19.8%，emotion=65 >=40 → min=18，通过
        self.assertNotIn("W1_PROMOTION", codes,
                         "晋级率 0.198 → 19.8% 应通过 ≥18 阈值")

    def test_zero_style_values_are_preserved(self):
        """总分=0、连板占比=0、趋势占比=0 不因 or 回退成 50"""
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-27"},"market":{},"sentiment":{},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{},"pnl":{},"style":{"总分":0,"连板占比":0,"趋势占比":0}}'
        )
        state = bridge._build_rule_state(now=datetime(2026, 5, 27, 9, 40))
        # 全零 style → base_total_cap(0)=20，不是 40
        self.assertEqual(state["caps"]["base_total_pct"], 20,
                         "总分=0 应映射为 base_total_pct=20，不是 40")
        self.assertEqual(state["caps"]["lianban_pct"], 0)
        self.assertEqual(state["caps"]["trend_pct"], 0)

    def test_full_snapshot_contains_rule_state(self):
        """_build_full_snapshot() 输出含 rule_state"""
        snap = bridge._build_full_snapshot()
        self.assertIn("rule_state", snap)
        self.assertEqual(snap["rule_state"]["version"], "g1a-v1")

    def test_live_quotes_response_contains_rule_contract(self):
        """mock GET /api/live/quotes 返回含 rule_state"""
        handler = object.__new__(bridge.BridgeHandler)
        handler.request = MagicMock()
        handler.command = "GET"
        handler.requestline = "GET /api/live/quotes HTTP/1.1"
        handler.path = "/api/live/quotes"
        handler.request_version = "HTTP/1.1"
        handler.request.version = "HTTP/1.1"
        handler.client_address = ("127.0.0.1", 12345)
        handler.server = MagicMock()
        handler.headers = MagicMock()
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

        do_get = getattr(handler, "do_GET", None)
        do_get()

        body = json.loads(handler._resp_body.decode()) if handler._resp_body else {}
        self.assertIn("rule_state", body)
        self.assertIn("windows", body["rule_state"])

    def test_live_quotes_rule_state_releases_connection(self):
        """GET /api/live/quotes 后连接已释放"""
        handler = object.__new__(bridge.BridgeHandler)
        handler.request = MagicMock()
        handler.command = "GET"
        handler.requestline = "GET /api/live/quotes HTTP/1.1"
        handler.path = "/api/live/quotes"
        handler.request_version = "HTTP/1.1"
        handler.request.version = "HTTP/1.1"
        handler.client_address = ("127.0.0.1", 12345)
        handler.server = MagicMock()
        handler.headers = MagicMock()
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

        do_get = getattr(handler, "do_GET", None)
        do_get()

        self.assertIsNone(getattr(db._local, "conn", None),
                          "GET /api/live/quotes 后连接应释放")


class FreshnessBoundaryTest(unittest.TestCase):
    """验证 freshness stale/dead 在 rule_state 中正确传播"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        self.orig_inited = bridge._db_inited
        self.orig_root = bridge.ROOT
        self.orig_data = bridge.DATA_FILE
        db.DB_PATH = self.tmp_dir / "test.db"
        db._local = threading.local()
        bridge._db_inited = False
        bridge.ROOT = self.tmp_dir
        self.tmp_dashboard = self.tmp_dir / "dashboard_data.json"
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-27"},"market":{},"sentiment":{},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{},"pnl":{},"style":{"总分":59,"连板占比":54,"趋势占比":46}}'
        )
        bridge.DATA_FILE = self.tmp_dashboard
        db.init_db()

        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        db.insert_account_baseline({
            "date": today, "effective_at": f"{today}T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 100000,
            "total_deposit": 100000, "positions": [], "source": "recovery",
        })

    def tearDown(self):
        bridge.CACHE.clear()
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        bridge._db_inited = self.orig_inited
        bridge.ROOT = self.orig_root
        bridge.DATA_FILE = self.orig_data
        self.tmp.cleanup()

    def test_stale_quotes_triggers_data_untrusted(self):
        """行情 stale 触发 DATA_UNTRUSTED"""
        bridge.CACHE["iwencai"] = {
            "情绪值": 65, "昨日涨停收益": 3.0,
            "晋级率": 0.22, "炸板率": 0.20,
            "_updated": "2026-05-27T09:40:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {
            "_updated": "2026-05-27T09:10:00+08:00",  # 30min old → stale
        }
        bridge.CACHE["live_index"] = {}
        bridge.CACHE["breadth"] = {}
        bridge.CACHE["hot_list"] = {}

        from datetime import datetime as _dt, timezone as _tz
        now = _dt(2026, 5, 27, 9, 40, tzinfo=_tz.utc)
        state = bridge._build_rule_state(now=now)
        codes = [b["code"] for b in state["blocks"]]
        self.assertIn("DATA_UNTRUSTED", codes)

    def test_production_format_same_minute_is_live(self):
        """生产 +08:00 同分钟数据必须判为 live（时区回归）"""
        bridge.CACHE["iwencai"] = {
            "情绪值": 65, "昨日涨停收益": 3.0,
            "晋级率": 0.22, "炸板率": 0.20,
            "_updated": "2026-05-27T09:40:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {
            "_updated": "2026-05-27T09:40:00+08:00",
        }
        bridge.CACHE["live_index"] = {}
        bridge.CACHE["breadth"] = {}
        bridge.CACHE["hot_list"] = {}

        # Naive now (local time +08:00) — 模拟生产路径
        from datetime import datetime as _dt
        now = _dt(2026, 5, 27, 9, 40)
        state = bridge._build_rule_state(now=now)
        codes = [b["code"] for b in state["blocks"]]
        # 同分钟数据应为 live，不应触发 DATA_UNTRUSTED 或 SENTIMENT_STALE
        self.assertNotIn("DATA_UNTRUSTED", codes,
                         "同分钟生产数据不应判为 DATA_UNTRUSTED")
        self.assertNotIn("SENTIMENT_STALE", codes,
                         "同分钟生产数据不应判为 SENTIMENT_STALE")
        self.assertTrue(state["tradable"],
                        "同分钟生产数据应为可交易")

    def test_dead_sentiment_triggers_sentiment_stale(self):
        """情绪 dead 触发 SENTIMENT_STALE"""
        bridge.CACHE["iwencai"] = {
            "情绪值": 65, "昨日涨停收益": 3.0,
            "晋级率": 0.22, "炸板率": 0.20,
            "_updated": "2026-05-26T09:00:00+08:00",  # >1day old → dead
        }
        bridge.CACHE["live_quotes"] = {
            "_updated": "2026-05-27T09:39:00+08:00",
        }
        bridge.CACHE["live_index"] = {}
        bridge.CACHE["breadth"] = {}
        bridge.CACHE["hot_list"] = {}

        from datetime import datetime as _dt, timezone as _tz
        now = _dt(2026, 5, 27, 9, 40, tzinfo=_tz.utc)
        state = bridge._build_rule_state(now=now)
        codes = [b["code"] for b in state["blocks"]]
        self.assertIn("SENTIMENT_STALE", codes)


class DoubleIceIntegrationTest(unittest.TestCase):
    """验证 DOUBLE_ICE 通过 sentiment_auto.json 日期分组正确找到 previous_emotion"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        self.orig_inited = bridge._db_inited
        self.orig_root = bridge.ROOT
        self.orig_data = bridge.DATA_FILE
        db.DB_PATH = self.tmp_dir / "test.db"
        db._local = threading.local()
        bridge._db_inited = False
        bridge.ROOT = self.tmp_dir
        self.tmp_dashboard = self.tmp_dir / "dashboard_data.json"
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-27"},"market":{},"sentiment":{},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{},"pnl":{},"style":{"总分":59,"连板占比":54,"趋势占比":46}}'
        )
        bridge.DATA_FILE = self.tmp_dashboard
        db.init_db()

        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        db.insert_account_baseline({
            "date": today, "effective_at": f"{today}T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 100000,
            "total_deposit": 100000, "positions": [], "source": "recovery",
        })

        bridge.CACHE["iwencai"] = {
            "情绪值": 15, "昨日涨停收益": 1.0,
            "晋级率": 0.05, "炸板率": 0.20,
            "_updated": "2026-05-27T09:40:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {"_updated": "2026-05-27T09:39:00+08:00"}
        bridge.CACHE["live_index"] = {}
        bridge.CACHE["breadth"] = {}
        bridge.CACHE["hot_list"] = {}

    def tearDown(self):
        bridge.CACHE.clear()
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        bridge._db_inited = self.orig_inited
        bridge.ROOT = self.orig_root
        bridge.DATA_FILE = self.orig_data
        self.tmp.cleanup()

    def test_double_ice_uses_date_grouped_previous_emotion(self):
        """前一日最后节点情绪=10，当前=15 → 双冰触发"""
        import json as _json
        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        # 前一日期
        prev_date = "2026-05-20"
        snap = {prev_date: [{"情绪值": 10, "time": f"{prev_date}T15:00:00+08:00"}],
                today: [{"情绪值": 15, "time": f"{today}T09:25:00+08:00"}]}
        snap_path = self.tmp_dir / "data" / "sentiment_auto.json"
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(_json.dumps(snap))

        # mock ROOT to point temp so sentiment_auto is found
        state = bridge._build_rule_state(now=__import__("datetime").datetime(2026, 5, 27, 9, 40))
        codes = [b["code"] for b in state["blocks"]]
        self.assertIn("DOUBLE_ICE", codes,
                      "前一日情绪=10 + 当前=15 应触发 DOUBLE_ICE")


class DebugSnapshotExceptionReleaseTest(unittest.TestCase):
    """验证 /api/debug/snapshot 异常路径也关闭 DB 连接"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        self.orig_inited = bridge._db_inited
        self.orig_root = bridge.ROOT
        self.orig_data = bridge.DATA_FILE
        db.DB_PATH = self.tmp_dir / "test.db"
        db._local = threading.local()
        bridge._db_inited = False
        bridge.ROOT = self.tmp_dir
        bridge.DATA_FILE = self.tmp_dir / "dashboard_data.json"
        db.init_db()

    def tearDown(self):
        bridge.CACHE.clear()
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        bridge._db_inited = self.orig_inited
        bridge.ROOT = self.orig_root
        bridge.DATA_FILE = self.orig_data
        self.tmp.cleanup()

    def test_debug_snapshot_exception_releases_connection(self):
        """_build_full_snapshot 抛错时连接也释放"""
        handler = object.__new__(bridge.BridgeHandler)
        handler.request = MagicMock()
        handler.command = "GET"
        handler.requestline = "GET /api/debug/snapshot HTTP/1.1"
        handler.path = "/api/debug/snapshot"
        handler.request_version = "HTTP/1.1"
        handler.request.version = "HTTP/1.1"
        handler.client_address = ("127.0.0.1", 12345)
        handler.server = MagicMock()
        handler.headers = MagicMock()
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

        # Patch _build_full_snapshot to raise
        with patch.object(bridge, "_build_full_snapshot", side_effect=RuntimeError("boom")):
            do_get = getattr(handler, "do_GET", None)
            try:
                do_get()
            except Exception:
                pass

        self.assertIsNone(getattr(db._local, "conn", None),
                          "异常路径也必须在 finally 中释放连接")


class SseConnectionReleaseTest(unittest.TestCase):
    """验证 SSE 每轮循环释放 DB 连接"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        self.orig_inited = bridge._db_inited
        self.orig_root = bridge.ROOT
        self.orig_data = bridge.DATA_FILE
        db.DB_PATH = self.tmp_dir / "test.db"
        db._local = threading.local()
        bridge._db_inited = False
        bridge.ROOT = self.tmp_dir
        self.tmp_dashboard = self.tmp_dir / "dashboard_data.json"
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-27"},"market":{},"sentiment":{},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{},"pnl":{},"style":{"总分":59,"连板占比":54,"趋势占比":46}}'
        )
        bridge.DATA_FILE = self.tmp_dashboard
        db.init_db()

        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        db.insert_account_baseline({
            "date": today, "effective_at": f"{today}T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 100000,
            "total_deposit": 100000, "positions": [], "source": "recovery",
        })

        bridge.CACHE["iwencai"] = {
            "情绪值": 65, "昨日涨停收益": 3.0,
            "晋级率": 0.22, "炸板率": 0.20,
            "_updated": "2026-05-27T09:40:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {
            "_updated": "2026-05-27T09:39:00+08:00",
        }
        bridge.CACHE["live_index"] = {}
        bridge.CACHE["breadth"] = {}
        bridge.CACHE["hot_list"] = {}

    def tearDown(self):
        bridge.CACHE.clear()
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        bridge._db_inited = self.orig_inited
        bridge.ROOT = self.orig_root
        bridge.DATA_FILE = self.orig_data
        self.tmp.cleanup()

    def test_sse_first_message_contains_rule_state_and_releases(self):
        """SSE 首条消息含 rule_state 且本轮结束后连接释放"""
        handler = object.__new__(bridge.BridgeHandler)
        handler.request = MagicMock()
        handler.command = "GET"
        handler.requestline = "GET /api/live/stream HTTP/1.1"
        handler.path = "/api/live/stream"
        handler.request_version = "HTTP/1.1"
        handler.request.version = "HTTP/1.1"
        handler.client_address = ("127.0.0.1", 12345)
        handler.server = MagicMock()
        handler.headers = MagicMock()
        handler.log_message = MagicMock()
        handler._resp_status = None
        handler._resp_headers = []
        handler._resp_body = b""
        handler._writes = []

        def msr(code, phrase=None): handler._resp_status = code
        def msh(key, value): handler._resp_headers.append((key, value))
        def meh(): pass
        def mww(self_data, data):
            handler._resp_body += data
            handler._writes.append(data)
            # Raise after first write to break SSE loop
            if len(handler._writes) >= 1:
                raise BrokenPipeError()
        handler.send_response = msr
        handler.send_header = msh
        handler.end_headers = meh
        handler.wfile = type("WFile", (), {"write": mww})()

        do_get = getattr(handler, "do_GET", None)
        try:
            do_get()
        except Exception:
            pass

        body = handler._resp_body.decode() if handler._resp_body else ""
        self.assertIn("rule_state", body, "SSE 首条消息应含 rule_state")
        self.assertIsNone(getattr(db._local, "conn", None),
                          "SSE 本轮结束后连接应释放")


if __name__ == "__main__":
    unittest.main()
