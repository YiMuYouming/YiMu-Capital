"""test_health_api.py — /api/health 健康端点 + 竞价补抓 (Gate 2A R2)

全隔离：temp DB、temp DATA_FILE、mock CACHE、tmp auction 文件。
不访问真实 data/**、不调用真实 POST 接口。
"""
import io
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import scripts.bridge as bridge
import scripts.db as db


def _setup_isolated_bridge(test):
    test.tmp = tempfile.TemporaryDirectory()
    d = Path(test.tmp.name)
    test.orig_path = db.DB_PATH
    test.orig_local = db._local
    test.orig_inited = bridge._db_inited
    test.orig_root = bridge.ROOT
    test.orig_data = bridge.DATA_FILE
    test.orig_cache = dict(bridge.CACHE)
    db.DB_PATH = d / "test.db"
    db._local = threading.local()
    bridge._db_inited = False
    bridge.ROOT = d
    bridge.DATA_FILE = d / "dashboard_data.json"
    today = datetime.now().strftime("%Y-%m-%d")
    bridge.DATA_FILE.write_text(json.dumps({
        "meta": {"date": today}, "market": {}, "sentiment": {"情绪值": 65},
        "lianban_pool": [], "trend_pool": [], "positions": [],
        "sectors": [], "decision": {}, "risk": {}, "pnl": {},
        "style": {"总分": 85, "连板占比": 54, "趋势占比": 46},
    }))
    db.init_db()
    db.insert_account_baseline({
        "date": today, "effective_at": f"{today}T09:30:00",
        "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 100000,
        "total_deposit": 100000, "positions": [], "source": "recovery",
    })
    bridge.CACHE["iwencai"] = {
        "情绪值": 65, "昨日涨停收益": 3.0,
        "_updated": f"{today}T09:40:00+08:00",
    }
    bridge.CACHE["live_quotes"] = {"_updated": f"{today}T09:39:00+08:00"}
    bridge.CACHE["live_index"] = {}
    bridge.CACHE["breadth"] = {}
    bridge.CACHE["hot_list"] = {}


def _teardown_isolated_bridge(test):
    db.close_conn()
    db.DB_PATH = test.orig_path
    db._local = test.orig_local
    bridge._db_inited = test.orig_inited
    bridge.ROOT = test.orig_root
    bridge.DATA_FILE = test.orig_data
    test.tmp.cleanup()
    bridge.CACHE.clear()
    bridge.CACHE.update(test.orig_cache)


def _ts(seconds_ago):
    """Timestamp in +08:00 format, seconds_ago from now."""
    ts = datetime.now(timezone(timedelta(hours=8))) - timedelta(seconds=seconds_ago)
    return ts.strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _build_handler(path, method="GET", payload=None):
    handler = object.__new__(bridge.BridgeHandler)
    handler.command = method
    handler.requestline = f"{method} {path} HTTP/1.1"
    handler.path = path
    handler.request_version = "HTTP/1.1"
    handler.request = MagicMock()
    handler.request.version = "HTTP/1.1"
    handler.client_address = ("127.0.0.1", 12345)
    handler.server = MagicMock()
    body = json.dumps(payload).encode() if payload else b"{}"
    handler.rfile = io.BytesIO(body)
    handler.headers = MagicMock()
    handler.headers.get = lambda k, d=None: str(len(body))
    handler.log_message = MagicMock()
    handler._resp_status = None
    handler._resp_headers = []
    handler._resp_body = b""

    def msr(code, p=None):
        handler._resp_status = code

    def msh(k, v):
        handler._resp_headers.append((k, v))

    def meh():
        pass

    def mww(s, d):
        handler._resp_body += d

    handler.send_response = msr
    handler.send_header = msh
    handler.end_headers = meh
    handler.wfile = type("WFile", (), {"write": mww})()
    return handler


def _make_valid_snapshot(fetched_ts=None):
    """Build a valid auction snapshot fixture with minimum actual data."""
    if fetched_ts is None:
        fetched_ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    return {
        "fetched": fetched_ts,
        "指数竞价": [{"名称": "上证", "竞价涨幅": 0.5, "最新价": 3400.0}],
        "涨跌家数": {"上涨": 2800, "下跌": 1500, "涨跌比": 1.87},
        "高标竞价": [],
        "自选池竞价": [],
        "板块竞价": [],
        "信号灯": {"综合": {"灯": "green"}},
    }


def _make_empty_snapshot(fetched_ts=None):
    """A snapshot with correct structure but no actual data (all-empty collect)."""
    if fetched_ts is None:
        fetched_ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    return {
        "fetched": fetched_ts,
        "指数竞价": [],
        "涨跌家数": {"上涨": 0, "下跌": 0, "涨跌比": 0},
        "高标竞价": [],
        "自选池竞价": [],
        "信号灯": {"综合": {"灯": "green"}},
    }


def _valid_account_state():
    return {"total_asset": 100000, "valuation_complete": True,
            "cash": 100000, "mv": 0, "pnl_pct": 0}


def _valid_pnl_summary():
    return {"total_asset": 100000, "valuation_complete": True,
            "cash": 100000, "mv": 0}


# ── Health API tests ──

class HealthAllGreenTest(unittest.TestCase):

    def setUp(self):
        _setup_isolated_bridge(self)
        today = datetime.now().strftime("%Y-%m-%d")
        bridge.CACHE["live_quotes"]["_updated"] = _ts(5)
        bridge.CACHE["iwencai"]["_updated"] = _ts(10)
        (bridge.ROOT / "data").mkdir(parents=True, exist_ok=True)
        (bridge.ROOT / "data" / "auction_snapshot.json").write_text(
            json.dumps(_make_valid_snapshot()))

    def tearDown(self):
        _teardown_isolated_bridge(self)

    def test_health_all_green(self):
        with patch("scripts.bridge._load_api_config",
                   return_value={"token": "t", "base_url": "https://x"}), \
             patch("scripts.bridge.load_current_account_state",
                   return_value=_valid_account_state()), \
             patch("scripts.bridge._current_pnl_summary",
                   return_value=_valid_pnl_summary()):
            result = bridge._build_health()
        self.assertEqual(result["status"], "healthy", f"status={result['status']}")
        self.assertEqual(result["bridge"]["status"], "ok")
        self.assertEqual(result["db"]["status"], "ok")
        self.assertEqual(result["baseline"]["status"], "ok")
        self.assertEqual(result["quotes"]["status"], "live")
        self.assertEqual(result["iwencai"]["status"], "live")
        self.assertEqual(result["account"]["status"], "ok")
        self.assertEqual(result["pnl"]["status"], "ok")
        self.assertEqual(result["auction"]["status"], "ok")
        self.assertEqual(result["llm_config"]["status"], "ok")

    def test_health_route_returns_200(self):
        handler = _build_handler("/api/health", method="GET")
        handler.do_GET()
        self.assertEqual(handler._resp_status, 200)
        body = json.loads(handler._resp_body)
        self.assertIn("status", body)

    def test_health_releases_db_connection(self):
        handler = _build_handler("/api/health", method="GET")
        handler.do_GET()
        self.assertIsNone(getattr(db._local, "conn", None))


class HealthQuotesCoverageTest(unittest.TestCase):

    def setUp(self):
        _setup_isolated_bridge(self)
        bridge.CACHE["live_quotes"]["_updated"] = _ts(5)

    def tearDown(self):
        _teardown_isolated_bridge(self)

    def test_stale_with_no_actual_quotes_not_healthy(self):
        """只有 _updated 时间戳、没有实际报价数据，不能 healthy"""
        bridge.CACHE["live_quotes"]["_updated"] = _ts(120)
        # Add tracked codes but no quotes
        today = datetime.now().strftime("%Y-%m-%d")
        bridge.DATA_FILE.write_text(json.dumps({
            "meta": {"date": today}, "market": {}, "sentiment": {},
            "lianban_pool": [{"代码": "000001", "标的": "测试"}],
            "trend_pool": [], "positions": [],
            "sectors": [], "decision": {}, "risk": {}, "pnl": {},
            "style": {"总分": 85},
        }))
        result = bridge._build_health()
        self.assertEqual(result["quotes"]["covered"], 0)
        self.assertEqual(result["quotes"]["total"], 1)
        self.assertEqual(result["quotes"]["status"], "dead",
                         f"zero coverage should be dead, got {result['quotes']['status']}")
        self.assertNotEqual(result["status"], "healthy")

    def test_fresh_but_positions_missing_quotes_is_degraded(self):
        """行情新鲜但持仓代码缺报价，降级为 delayed"""
        today = datetime.now().strftime("%Y-%m-%d")
        bridge.DATA_FILE.write_text(json.dumps({
            "meta": {"date": today}, "market": {}, "sentiment": {},
            "lianban_pool": [], "trend_pool": [],
            "positions": [{"代码": "000001", "标的": "测试", "成本": 10}],
            "sectors": [], "decision": {}, "risk": {}, "pnl": {},
            "style": {"总分": 85},
        }))
        result = bridge._build_health()
        self.assertEqual(result["quotes"]["total"], 1)
        self.assertEqual(result["quotes"]["covered"], 0)
        self.assertNotEqual(result["status"], "healthy")


class HealthAccountValuationCompleteTest(unittest.TestCase):

    def setUp(self):
        _setup_isolated_bridge(self)

    def tearDown(self):
        _teardown_isolated_bridge(self)

    def test_valuation_complete_false_is_incomplete(self):
        """valuation_complete=false 时 account 不能 ok"""
        with patch("scripts.bridge.load_current_account_state",
                   return_value={"total_asset": 100000, "valuation_complete": False,
                                 "cash": 100000, "mv": 50000}):
            result = bridge._build_health()
        self.assertEqual(result["account"]["status"], "incomplete")
        self.assertIn("valuation_complete", result["account"]["detail"], str(result["account"]))
        self.assertNotEqual(result["status"], "healthy")

    def test_pnl_valuation_complete_false_is_incomplete(self):
        """PnL valuation_complete=false 不能 ok"""
        with patch("scripts.bridge._current_pnl_summary",
                   return_value={"total_asset": 100000, "valuation_complete": False,
                                 "cash": 100000, "mv": 50000}):
            result = bridge._build_health()
        self.assertEqual(result["pnl"]["status"], "incomplete")
        self.assertIn("valuation_complete", result["pnl"]["detail"], str(result["pnl"]))


class HealthAuctionReuseTest(unittest.TestCase):

    def setUp(self):
        _setup_isolated_bridge(self)

    def tearDown(self):
        _teardown_isolated_bridge(self)

    def test_auction_valid_uses_is_auction_valid(self):
        """有效快照通过 is_auction_valid 判定为 ok"""
        today = datetime.now().strftime("%Y-%m-%d")
        (bridge.ROOT / "data").mkdir(parents=True, exist_ok=True)
        (bridge.ROOT / "data" / "auction_snapshot.json").write_text(
            json.dumps(_make_valid_snapshot(f"{today}T09:28:00+08:00")))
        result = bridge._build_health()
        self.assertEqual(result["auction"]["status"], "ok")

    def test_auction_missing_key_dimension_not_ok(self):
        """缺关键维度时 is_auction_valid 返回 False，不能 healthy"""
        today = datetime.now().strftime("%Y-%m-%d")
        (bridge.ROOT / "data").mkdir(parents=True, exist_ok=True)
        (bridge.ROOT / "data" / "auction_snapshot.json").write_text(json.dumps({
            "fetched": f"{today}T09:28:00+08:00",
            "指数竞价": [],
            "涨跌家数": {},
        }))
        result = bridge._build_health()
        self.assertEqual(result["auction"]["status"], "incomplete")
        self.assertNotEqual(result["status"], "healthy")


class HealthQuotesStaleTest(unittest.TestCase):

    def setUp(self):
        _setup_isolated_bridge(self)

    def tearDown(self):
        _teardown_isolated_bridge(self)

    def test_quotes_stale_is_degraded(self):
        bridge.CACHE["live_quotes"]["_updated"] = _ts(120)
        result = bridge._build_health()
        self.assertEqual(result["quotes"]["status"], "stale")
        self.assertNotEqual(result["status"], "healthy")

    def test_quotes_dead_is_unhealthy(self):
        bridge.CACHE["live_quotes"]["_updated"] = _ts(360)
        result = bridge._build_health()
        self.assertEqual(result["quotes"]["status"], "dead")
        self.assertEqual(result["status"], "unhealthy")


class HealthIWencaiStaleTest(unittest.TestCase):

    def setUp(self):
        _setup_isolated_bridge(self)

    def tearDown(self):
        _teardown_isolated_bridge(self)

    def test_iwencai_stale_is_degraded(self):
        bridge.CACHE["iwencai"]["_updated"] = _ts(700)
        result = bridge._build_health()
        self.assertEqual(result["iwencai"]["status"], "stale")


class HealthAccountIncompleteTest(unittest.TestCase):

    def setUp(self):
        _setup_isolated_bridge(self)

    def tearDown(self):
        _teardown_isolated_bridge(self)

    def test_account_none_is_incomplete(self):
        with patch("scripts.bridge.load_current_account_state",
                   return_value=None):
            result = bridge._build_health()
        self.assertEqual(result["account"]["status"], "incomplete")

    def test_account_missing_total_asset(self):
        with patch("scripts.bridge.load_current_account_state",
                   return_value={"cash": 50000, "mv": 0}):
            result = bridge._build_health()
        self.assertEqual(result["account"]["status"], "incomplete")


class HealthLLMConfigTest(unittest.TestCase):

    def setUp(self):
        _setup_isolated_bridge(self)

    def tearDown(self):
        _teardown_isolated_bridge(self)

    def test_llm_config_missing(self):
        with patch("scripts.bridge._load_api_config",
                   return_value={"token": "", "base_url": ""}):
            result = bridge._build_health()
        self.assertEqual(result["llm_config"]["status"], "missing")

    def test_token_not_exposed(self):
        with patch("scripts.bridge._load_api_config",
                   return_value={"token": "sk-secret-token-123", "base_url": "https://api.example.com"}):
            result = bridge._build_health()
        body = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("sk-secret-token-123", body)
        self.assertNotIn("token", body.lower())


# ── Auction catch-up tests ──

class AuctionCatchUpTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_snapshot_not_overwritten(self):
        from scripts.snapshot_auction import auction_catch_up
        snap_path = self.tmp_path / "auction.json"
        snap_path.write_text(json.dumps(_make_valid_snapshot()))
        result, action = auction_catch_up(output_path=str(snap_path))
        self.assertEqual(action, "skip")

    def test_missing_snapshot_catch_up(self):
        from scripts.snapshot_auction import auction_catch_up
        snap_path = self.tmp_path / "auction_nonexist.json"

        def mock_build():
            return _make_valid_snapshot()

        result, action = auction_catch_up(output_path=str(snap_path), build_fn=mock_build)
        self.assertEqual(action, "catch_up")
        self.assertEqual(result.get("source"), "catch_up")

    def test_invalid_snapshot_catch_up(self):
        from scripts.snapshot_auction import auction_catch_up
        snap_path = self.tmp_path / "auction_invalid.json"
        snap_path.write_text(json.dumps({"fetched": "2026-05-20T09:28:00+08:00", "指数竞价": []}))

        def mock_build():
            return _make_valid_snapshot()

        result, action = auction_catch_up(output_path=str(snap_path), build_fn=mock_build)
        self.assertEqual(action, "catch_up")
        self.assertEqual(result.get("source"), "catch_up")

    def test_catch_up_has_source_markers(self):
        from scripts.snapshot_auction import auction_catch_up
        snap_path = self.tmp_path / "auction.json"

        def mock_build():
            return _make_valid_snapshot()

        result, action = auction_catch_up(output_path=str(snap_path), build_fn=mock_build)
        self.assertEqual(action, "catch_up")
        self.assertEqual(result.get("source"), "catch_up")
        self.assertTrue(snap_path.exists())
        self.assertEqual(json.loads(snap_path.read_text()).get("source"), "catch_up")

    def test_build_crash_returns_error(self):
        from scripts.snapshot_auction import auction_catch_up
        snap_path = self.tmp_path / "auction.json"

        def crash_build():
            raise RuntimeError("iwencai unavailable")

        result, action = auction_catch_up(output_path=str(snap_path), build_fn=crash_build)
        self.assertEqual(action, "error")
        self.assertIn("iwencai", result["error"])

    def test_second_trigger_skips_after_first_success(self):
        """09:28 成功后，09:35 补抓 skip，不覆盖"""
        from scripts.snapshot_auction import auction_catch_up
        snap_path = self.tmp_path / "auction.json"
        snap_path.write_text(json.dumps(_make_valid_snapshot()))

        # First trigger (09:28)
        result1, action1 = auction_catch_up(output_path=str(snap_path))
        self.assertEqual(action1, "skip")
        first_fetched = result1["fetched"]

        # Second trigger (09:35) — same function
        result2, action2 = auction_catch_up(output_path=str(snap_path))
        self.assertEqual(action2, "skip", "补抓应跳过已有效快照")
        self.assertEqual(result2["fetched"], first_fetched, "fetched 时间不应变")

    def test_second_trigger_catches_up_after_first_miss(self):
        """09:28 缺失/无效，09:35 补抓写入 catch_up"""
        from scripts.snapshot_auction import auction_catch_up
        snap_path = self.tmp_path / "auction.json"
        # Old invalid snapshot
        snap_path.write_text(json.dumps({"fetched": "2026-05-20T09:28:00+08:00", "指数竞价": []}))

        call_count = [0]

        def mock_build():
            call_count[0] += 1
            return _make_valid_snapshot()

        # First trigger — should catch up (invalid snapshot)
        result1, action1 = auction_catch_up(output_path=str(snap_path), build_fn=mock_build)
        self.assertEqual(action1, "catch_up")
        self.assertEqual(call_count[0], 1)

        # Second trigger — now valid, should skip
        result2, action2 = auction_catch_up(output_path=str(snap_path), build_fn=mock_build)
        self.assertEqual(action2, "skip", "补抓应跳过已补抓的有效快照")
        self.assertEqual(call_count[0], 1, "build 不应被再次调用")


class IsAuctionValidTest(unittest.TestCase):

    def test_valid_snapshot(self):
        from scripts.snapshot_auction import is_auction_valid
        self.assertTrue(is_auction_valid(_make_valid_snapshot()))

    def test_empty_all_collect_is_invalid(self):
        """全空采集结果（结构对但无实际数据）不得 valid"""
        from scripts.snapshot_auction import is_auction_valid
        self.assertFalse(is_auction_valid(_make_empty_snapshot()))

    def test_yesterday_snapshot_is_invalid(self):
        from scripts.snapshot_auction import is_auction_valid
        snap = _make_valid_snapshot("2026-05-25T09:28:00+08:00")
        self.assertFalse(is_auction_valid(snap, now=datetime(2026, 5, 27, 9, 29)))

    def test_missing_dimension_is_invalid(self):
        from scripts.snapshot_auction import is_auction_valid
        today = datetime.now().strftime("%Y-%m-%d")
        snap = {"fetched": f"{today}T09:28:00+08:00", "指数竞价": [], "涨跌家数": {}}
        self.assertFalse(is_auction_valid(snap))

    def test_non_dict_is_invalid(self):
        from scripts.snapshot_auction import is_auction_valid
        self.assertFalse(is_auction_valid(None))
        self.assertFalse(is_auction_valid("string"))

    def test_null_dimension_is_invalid(self):
        from scripts.snapshot_auction import is_auction_valid
        snap = _make_valid_snapshot()
        snap["指数竞价"] = None
        self.assertFalse(is_auction_valid(snap))

    def test_breadth_sentinel_values_not_breadth(self):
        """上涨='—' 下跌='bad' 不抛异常，不视为有效涨跌数据"""
        from scripts.snapshot_auction import is_auction_valid
        snap = _make_valid_snapshot()
        snap["指数竞价"] = []  # remove index data
        snap["涨跌家数"] = {"上涨": "—", "下跌": "bad"}
        self.assertFalse(is_auction_valid(snap))  # no exception

    def test_breadth_mixed_valid_partial_not_enough(self):
        """上涨有效但下跌='—'，无指数数据时应 invalid（涨跌总和=有效值+0）"""
        from scripts.snapshot_auction import is_auction_valid
        snap = _make_valid_snapshot()
        snap["指数竞价"] = []
        snap["涨跌家数"] = {"上涨": 3000, "下跌": "—"}
        # up=3000, dn=0 → sum=3000 > 0 → has_breadth=True → valid
        self.assertTrue(is_auction_valid(snap))


class AuctionEmptyCatchUpTest(unittest.TestCase):
    """全空采集结果的补抓行为"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_build_returns_error_not_overwrites(self):
        """空 build 结果 invalid，返回 error 不写文件"""
        from scripts.snapshot_auction import auction_catch_up
        snap_path = self.tmp_path / "auction.json"
        from datetime import datetime, timedelta
        yest = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        valid_old = _make_valid_snapshot(yest + "T09:00:00+08:00")
        snap_path.write_text(json.dumps(valid_old))

        result, action = auction_catch_up(output_path=str(snap_path), build_fn=_make_empty_snapshot)
        self.assertEqual(action, "error", "空结果应返回 error")
        self.assertIn("error", result)
        self.assertIn("invalid", str(result.get("error", "")))
        # Old file must not be overwritten
        disk = json.loads(snap_path.read_text())
        self.assertEqual(disk["fetched"], yest + "T09:00:00+08:00")

    def test_empty_then_valid_catch_up(self):
        """09:28 空结果，09:35 有效结果仍可写入 catch_up"""
        from scripts.snapshot_auction import auction_catch_up
        snap_path = self.tmp_path / "auction.json"
        # File does not exist at all (09:28 returned empty and was not written)
        # 09:35 second trigger produces valid result
        result, action = auction_catch_up(output_path=str(snap_path), build_fn=_make_valid_snapshot)
        self.assertEqual(action, "catch_up")
        self.assertEqual(result.get("source"), "catch_up")
        # File exists now
        self.assertTrue(snap_path.exists())
        disk = json.loads(snap_path.read_text())
        self.assertEqual(disk.get("source"), "catch_up")

    def test_corrupt_build_does_not_overwrite(self):
        """损坏 build 结果（涨跌='—' 等）不写入，不覆盖已有文件"""
        from scripts.snapshot_auction import auction_catch_up
        snap_path = self.tmp_path / "auction.json"
        from datetime import datetime, timedelta
        yest = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        valid_old = _make_valid_snapshot(yest + "T09:00:00+08:00")
        snap_path.write_text(json.dumps(valid_old))

        def corrupt_build():
            s = _make_valid_snapshot()
            s["指数竞价"] = []
            s["涨跌家数"] = {"上涨": "—", "下跌": "bad"}
            return s

        result, action = auction_catch_up(output_path=str(snap_path), build_fn=corrupt_build)
        self.assertEqual(action, "error", "损坏build应返回error")
        disk = json.loads(snap_path.read_text())
        self.assertEqual(disk["fetched"], yest + "T09:00:00+08:00",
                         "已有文件不应被覆盖")


class HealthEmptyAuctionTest(unittest.TestCase):
    """health endpoint 遇到全空快照时不得 healthy"""

    def setUp(self):
        _setup_isolated_bridge(self)

    def tearDown(self):
        _teardown_isolated_bridge(self)

    def test_empty_snapshot_not_healthy(self):
        """全空快照文件存在但 is_auction_valid=False → 整体不得 healthy"""
        (bridge.ROOT / "data").mkdir(parents=True, exist_ok=True)
        (bridge.ROOT / "data" / "auction_snapshot.json").write_text(
            json.dumps(_make_empty_snapshot()))
        result = bridge._build_health()
        self.assertNotEqual(result["auction"]["status"], "ok",
                            f"全空快照不得显示 ok: {result['auction']}")
        self.assertNotEqual(result["status"], "healthy")

    def test_corrupted_snapshot_returns_200_not_healthy(self):
        """当天 auction_snapshot.json 字段损坏（上涨='—'），health 返回非 healthy 不抛 500"""
        (bridge.ROOT / "data").mkdir(parents=True, exist_ok=True)
        corr = _make_empty_snapshot()
        corr["涨跌家数"] = {"上涨": "—", "下跌": "bad"}
        (bridge.ROOT / "data" / "auction_snapshot.json").write_text(json.dumps(corr))
        result = bridge._build_health()
        self.assertNotEqual(result["auction"]["status"], "ok",
                            f"损坏快照不得 ok: {result['auction']}")
        self.assertNotEqual(result["status"], "healthy")

    def test_corrupted_snapshot_handler_returns_200(self):
        """损坏快照不导致 /api/health HTTP 500"""
        (bridge.ROOT / "data").mkdir(parents=True, exist_ok=True)
        corr = _make_empty_snapshot()
        corr["涨跌家数"] = {"上涨": "—", "下跌": "bad"}
        (bridge.ROOT / "data" / "auction_snapshot.json").write_text(json.dumps(corr))
        handler = _build_handler("/api/health", method="GET")
        handler.do_GET()
        self.assertEqual(handler._resp_status, 200,
                         f"损坏快照不应导致 500: body={handler._resp_body[:200]}")
        body = json.loads(handler._resp_body)
        self.assertIn("auction", body)


if __name__ == "__main__":
    unittest.main()
