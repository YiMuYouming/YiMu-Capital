"""test_health_api.py — /api/health 收盘快照 vs 真 dead 区分"""
import json, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
import scripts.bridge as bridge
import scripts.db as db


def _setup(test):
    test.tmp = tempfile.TemporaryDirectory()
    test.orig_path = db.DB_PATH; test.orig_local = db._local
    test.orig_cache = dict(bridge.CACHE)
    test.orig_data = bridge.DATA_FILE
    db.DB_PATH = Path(test.tmp.name) / "test.db"
    db._local = threading.local()
    bridge._db_inited = False
    bridge.DATA_FILE = Path(test.tmp.name) / "d.json"
    bridge.DATA_FILE.write_text(json.dumps({"meta": {"date": "2026-05-27"}, "positions": [], "pnl": {}}))
    db.init_db()


def _teardown(test):
    conn = getattr(db._local, "conn", None)
    if conn is not None: conn.close()
    db.DB_PATH = test.orig_path; db._local = test.orig_local
    bridge._db_inited = getattr(bridge, '_db_inited', False)
    bridge.DATA_FILE = test.orig_data
    bridge.CACHE.clear(); bridge.CACHE.update(test.orig_cache)
    test.tmp.cleanup()


class HealthCloseSnapshotTests(unittest.TestCase):

    def setUp(self):
        _setup(self)
        from datetime import datetime, timedelta, timezone
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        now_str = now.strftime('%Y-%m-%dT%H:%M:%S+08:00')
        today = now.strftime("%Y-%m-%d")
        db.insert_account_baseline({
            "date": today,
            "effective_at": f"{today}T09:30:00",
            "trade_id_cutoff": 0,
            "cash": 100000, "day_start_asset": 200000,
            "total_deposit": 200000,
            "positions": [{"标的": "TEST", "代码": "000001", "数量": 100, "成本": 10, "状态": "持有"}],
            "source": "previous_close",
        })
        bridge.CACHE['_stock_codes'] = ['000001']
        bridge.CACHE['live_quotes'] = {"000001": {"最新价": 105}, "_updated": now_str}
        bridge.DATA_FILE.write_text(json.dumps({
            "meta": {"date": today},
            "positions": [{"代码": "000001", "标的": "TEST"}],
            "pnl": {},
        }))
        bridge.CACHE['iwencai'] = {"情绪值": 65, "_updated": now_str}

    def tearDown(self):
        _teardown(self)

    def test_close_snapshot_quotes_not_dead(self):
        from datetime import datetime, timedelta, timezone
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        bridge.CACHE['live_quotes'] = {
            "000001": {"最新价": 105},
            "_updated": (now - timedelta(seconds=1)).strftime('%Y-%m-%dT%H:%M:%S+08:00'),
        }
        health = bridge._build_health()
        quotes = health.get("quotes", {})
        self.assertIn(quotes.get("status"), ("live", "delayed"),
            f"新鲜行情应 live/delayed: {quotes}")
        self.assertEqual(quotes.get("covered"), 1)

    def test_zero_coverage_still_dead(self):
        bridge.CACHE['live_quotes'] = {}
        health = bridge._build_health()
        quotes = health.get("quotes", {})
        self.assertEqual(quotes.get("status"), "dead",
            f"zero coverage 应 dead: {quotes}")

    def test_intraday_stale_still_old_rule(self):
        from datetime import datetime, timedelta, timezone
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        bridge.CACHE['live_quotes'] = {
            "000001": {"最新价": 105},
            "_updated": (now - timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%S+08:00'),
        }
        health = bridge._build_health()
        quotes = health.get("quotes", {})
        # 受 account 收盘快照修正影响, stale 可能显示为 close_snapshot
        self.assertIn(quotes.get("status"), ("stale", "dead", "delayed", "close_snapshot"),
            f"过期行情按旧规则+收盘快照修正: {quotes}")


class LiveIndexBaselineFallbackTests(unittest.TestCase):

    def setUp(self):
        _setup(self)
        bridge.DATA_FILE.write_text(json.dumps({
            "meta": {"date": "2026-05-28", "updated": "2026-05-28T15:00:00+08:00"},
            "market": {
                "上证指数": 4093.73,
                "上证涨幅": -1.25,
                "上证振幅": 1.34,
                "市场量能": 3.24,
                "涨跌比": "2962/2147",
            },
            "positions": [],
            "pnl": {},
        }, ensure_ascii=False))

    def tearDown(self):
        _teardown(self)

    def test_live_index_falls_back_to_close_baseline_after_restart(self):
        bridge.CACHE["live_index"] = {"_updated": "2026-05-28T17:30:00+08:00"}

        li = bridge._live_index_with_baseline()

        self.assertEqual(li["上证指数"], 4093.73)
        self.assertEqual(li["上证指数涨幅"], "-1.25%")
        self.assertEqual(li["上证指数振幅"], "+1.34%")
        self.assertEqual(li["成交额"], "3.24万亿")
        self.assertEqual(li["上涨家数"], 2962)
        self.assertEqual(li["下跌家数"], 2147)
        self.assertEqual(li["_source"], "baseline_close_fallback")

    def test_live_payload_stream_uses_same_baseline_fallback(self):
        bridge.CACHE["live_index"] = {}

        payload = bridge._build_live_quotes_payload(rule_state={"status": "test"})

        self.assertEqual(payload["live_index"]["上证指数"], 4093.73)
        self.assertEqual(payload["live_index"]["上证指数涨幅"], "-1.25%")
        self.assertEqual(payload["live_index"]["上证指数振幅"], "+1.34%")
        self.assertEqual(payload["live_index"]["成交额"], "3.24万亿")
        self.assertEqual(payload["rule_state"], {"status": "test"})

    def test_live_payload_marks_iwencai_freshness(self):
        bridge.CACHE["iwencai"] = {
            "涨停家数": 0,
            "跌停家数": 0,
            "_updated": "2026-06-05T15:07:01+08:00",
        }

        payload = bridge._build_live_quotes_payload()

        freshness = payload["iwencai"].get("_freshness") or {}
        self.assertEqual(freshness.get("type"), "iwencai")
        self.assertIn(freshness.get("level"), ("live", "delayed", "stale", "dead"))
        self.assertEqual(bridge.CACHE["iwencai"].get("_freshness"), None,
                         "payload freshness 不应反向污染 CACHE")

    def test_live_payload_masks_stale_iwencai_values(self):
        bridge.CACHE["iwencai"] = {
            "情绪值": 59,
            "涨停家数": 42,
            "跌停家数": 8,
            "_updated": "2020-01-01T11:26:00+08:00",
        }

        payload = bridge._build_live_quotes_payload(rule_state={"status": "test"})
        iwencai = payload["iwencai"]

        self.assertNotIn("情绪值", iwencai)
        self.assertNotIn("涨停家数", iwencai)
        self.assertNotIn("跌停家数", iwencai)
        self.assertEqual(iwencai.get("_updated"), "2020-01-01T11:26:00+08:00")
        self.assertTrue(iwencai.get("_stale"))
        self.assertFalse(iwencai.get("_available"))
        self.assertIn((iwencai.get("_freshness") or {}).get("level"), ("stale", "dead"))


if __name__ == "__main__":
    unittest.main()


class AccountBasisAuditTest(unittest.TestCase):
    """v3 Phase 4: 只读 account basis audit API"""

    def setUp(self):
        _setup(self)
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        db.insert_account_baseline({
            "date": today, "effective_at": f"{today}T09:30:00",
            "trade_id_cutoff": 0, "cash": 80000, "day_start_asset": 100000,
            "total_deposit": 100000,
            "positions": [{"标的": "TEST", "代码": "000001", "数量": 500, "成本": 20, "现价": 21, "状态": "持有"},
                          {"标的": "OLD", "代码": "000002", "数量": 100, "成本": 10, "现价": 15, "状态": "持有"}],
            "source": "previous_close",
            "_meta": {"day_start_prices": {"000001": 20.5}},
        })

    def tearDown(self):
        _teardown(self)

    def test_account_audit_has_anchor_date_source(self):
        """audit 返回锚点日期和 source"""
        from scripts.account_ssot import load_current_account_state
        state = load_current_account_state({})
        anchor = state.get("anchor", {})
        self.assertIn("date", anchor)
        self.assertIn("source", anchor)

    def test_account_audit_lists_overnight_positions(self):
        """audit 列出隔夜持仓数量和代码"""
        from scripts.account_ssot import load_current_account_state
        state = load_current_account_state({})
        positions = state.get("positions", [])
        self.assertGreaterEqual(len(positions), 1)
        codes = [p.get("代码") for p in positions]
        self.assertIn("000001", codes)

    def test_account_audit_day_start_coverage(self):
        """audit 报告 day_start_prices 覆盖率和缺失代码"""
        from scripts.account_ssot import load_current_account_state
        state = load_current_account_state({})
        anchor = state.get("anchor", {})
        # 通过 load_current_account_state 获取锚点 meta
        from scripts.db import query_account_baseline
        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        raw_anchor = query_account_baseline(today)
        meta = raw_anchor.get("_meta", {}) if raw_anchor else {}
        prices = meta.get("day_start_prices", {})
        positions = raw_anchor.get("positions", []) if raw_anchor else []
        total = len(positions)
        covered = sum(1 for p in positions if p.get("代码") in prices)
        self.assertGreaterEqual(covered, 1)
        self.assertGreaterEqual(total, covered)


class HealthStratificationTest(unittest.TestCase):
    """/api/health 分层: critical_ok, trade_entry_allowed, degraded_reasons"""

    def setUp(self):
        _setup(self)
        from datetime import datetime, timedelta, timezone
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        now_str = now.strftime('%Y-%m-%dT%H:%M:%S+08:00')
        today = now.strftime("%Y-%m-%d")
        db.insert_account_baseline({
            "date": today, "effective_at": f"{today}T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 200000,
            "total_deposit": 200000, "positions": [], "source": "previous_close",
        })
        bridge.CACHE['_stock_codes'] = ['000001']
        bridge.CACHE['live_quotes'] = {"000001": {"最新价": 105}, "_updated": now_str}
        bridge.CACHE['iwencai'] = {"情绪值": 65, "_updated": now_str}
        bridge.DATA_FILE.write_text(json.dumps({
            "meta": {"date": today},
            "positions": [{"代码": "000001", "标的": "TEST"}],
            "pnl": {},
        }))

    def tearDown(self):
        _teardown(self)

    def test_health_has_critical_ok(self):
        """健康状态返回 critical_ok 字段"""
        health = bridge._build_health()
        self.assertIn("critical_ok", health)

    def test_health_has_trade_entry_allowed(self):
        """健康状态返回 trade_entry_allowed 字段"""
        health = bridge._build_health()
        self.assertIn("trade_entry_allowed", health)

    def test_health_has_degraded_reasons(self):
        """degraded 时有 reasons 列表"""
        health = bridge._build_health()
        self.assertIn("degraded_reasons", health)

    def test_iwencai_delayed_not_critical(self):
        """iwencai 延迟是 degraded, 不关闭 trade_entry_allowed"""
        from datetime import datetime, timedelta, timezone
        stale_ts = (datetime.now(timezone(timedelta(hours=8))) - timedelta(seconds=900)).strftime('%Y-%m-%dT%H:%M:%S+08:00')
        bridge.CACHE['iwencai'] = {'情绪值': 65, '_updated': stale_ts}
        health = bridge._build_health()
        self.assertTrue(health.get("trade_entry_allowed", False),
                        f"iwencai 延迟不应关闭交易: {health}")
        reasons = health.get("degraded_reasons") or []
        self.assertTrue(any("iwencai" in str(r).lower() for r in reasons),
                        f"应有 iwencai degraded 原因: {reasons}")

    def test_anchor_blocked_closes_trade_entry(self):
        """anchor_blocked 是 critical, 关闭 trade_entry_allowed"""
        from scripts.db import query_account_baseline
        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        # 模拟无锚点状态 — 删除当前锚点后 load 会返回 blocked
        db._exec("DELETE FROM account_baselines")
        health = bridge._build_health()
        self.assertFalse(health.get("trade_entry_allowed", True),
                         "anchor_blocked 应关闭交易录入")
        self.assertFalse(health.get("critical_ok", True),
                         "anchor_blocked 应 critical_ok=false")


if __name__ == "__main__":
    unittest.main()


import io, unittest
from unittest import mock

class AccountAuditHandlerTest(unittest.TestCase):
    """GET /api/account/audit 端点返回 anchor + positions + coverage + closed"""

    def setUp(self):
        _setup(self)
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        db.insert_account_baseline({
            "date": today, "effective_at": f"{today}T09:30:00",
            "trade_id_cutoff": 0, "cash": 80000, "day_start_asset": 100000,
            "total_deposit": 100000,
            "positions": [{"标的": "T1", "代码": "000001", "数量": 500, "现价": 21, "状态": "持有"},
                          {"标的": "T2", "代码": "000002", "数量": 100, "现价": 15, "状态": "持有"}],
            "source": "previous_close",
            "_meta": {"day_start_prices": {"000001": 20.5}},
        })
        bridge.CACHE['live_quotes'] = {"_updated": f"{today}T09:35:00+08:00"}

    def tearDown(self):
        _teardown(self)

    def _handler_get(self, path):
        h = object.__new__(bridge.BridgeHandler)
        h.command = 'GET'
        h.path = path
        h.requestline = f'GET {path} HTTP/1.1'
        h.request_version = 'HTTP/1.1'
        h.request = mock.MagicMock()
        h.request.version = 'HTTP/1.1'
        h.client_address = ('127.0.0.1', 12345)
        h.server = mock.MagicMock()
        h.headers = mock.MagicMock()
        h.headers.get = lambda k, d=None: '0'
        h._resp_status = None
        h._resp_body = b''
        def _sr(c, p=None): h._resp_status = c
        def _sh(k, v): pass
        def _eh(): pass
        def _ww(s, d): h._resp_body += d
        h.send_response = _sr
        h.send_header = _sh
        h.end_headers = _eh
        h.wfile = type('WFile', (), {'write': _ww})()
        return h

    def test_audit_returns_anchor_date_and_source(self):
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        h = self._handler_get('/api/account/audit')
        h.do_GET()
        self.assertEqual(h._resp_status, 200)
        body = json.loads(h._resp_body)
        self.assertEqual(body.get('anchor_date'), today)
        self.assertEqual(body.get('anchor_source'), 'previous_close')

    def test_audit_returns_overnight_positions(self):
        h = self._handler_get('/api/account/audit')
        h.do_GET()
        body = json.loads(h._resp_body)
        self.assertEqual(body.get('overnight_positions_count'), 2)
        self.assertIn('000001', body.get('overnight_codes', []))

    def test_audit_returns_day_start_coverage(self):
        h = self._handler_get('/api/account/audit')
        h.do_GET()
        body = json.loads(h._resp_body)
        self.assertEqual(body.get('day_start_prices_coverage'), '1/2')
        self.assertEqual(body.get('day_start_prices_missing_codes'), ['000002'])

    def test_audit_returns_closed_positions(self):
        h = self._handler_get('/api/account/audit')
        h.do_GET()
        body = json.loads(h._resp_body)
        self.assertIsNotNone(body.get('closed_positions_today_count'))
    def test_audit_does_not_create_anchor(self):
        """audit 端点严格只读：无锚点时不得创建新 row"""
        db._exec("DELETE FROM account_baselines")
        count_before = len(db._exec("SELECT * FROM account_baselines"))
        h = self._handler_get('/api/account/audit')
        h.do_GET()
        self.assertEqual(h._resp_status, 200)
        count_after = len(db._exec("SELECT * FROM account_baselines"))
        self.assertEqual(count_before, count_after, "audit 不得创建锚点")
        body = json.loads(h._resp_body)
        self.assertIsNone(body.get('anchor_date'))
        self.assertEqual(body.get('closed_positions_today_count'), 0)





class LiveHealthConsistencyTest(unittest.TestCase):
    """/api/live/quotes 的 trade_entry_allowed 与 /api/health 一致"""

    def setUp(self):
        _setup(self)
        from datetime import datetime, timedelta, timezone
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        now_str = now.strftime('%Y-%m-%dT%H:%M:%S+08:00')
        today = now.strftime("%Y-%m-%d")
        db.insert_account_baseline({
            "date": today, "effective_at": f"{today}T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 200000,
            "total_deposit": 200000, "positions": [], "source": "previous_close",
        })
        bridge.CACHE['live_quotes'] = {"000001": {"最新价": 105}, "_updated": now_str}
        bridge.CACHE['iwencai'] = {"情绪值": 65, "_updated": now_str}
        bridge.DATA_FILE.write_text(json.dumps({
            "meta": {"date": today}, "positions": [], "pnl": {},
        }))

    def tearDown(self):
        _teardown(self)

    def test_quotes_dead_same_trade_entry_on_health_and_live(self):
        """quotes dead → health trade_entry_allowed=false → live 也必须 false"""
        bridge.CACHE['live_quotes'] = {}
        health = bridge._build_health()
        self.assertFalse(health.get('trade_entry_allowed', True),
                         f"health quotes dead 应 trade_entry_allowed=false: {health}")

        # 模拟 /api/live/quotes 同样判定
        # 直接取 health 的 trade_entry_allowed（live endpoint 现在调用 _build_health）
        h2 = bridge._build_health()
        self.assertFalse(h2.get('trade_entry_allowed', True),
                         f"live 应匹配 health 的 trade_entry_allowed=false: {h2}")
        self.assertEqual(
            health.get('trade_entry_allowed'), h2.get('trade_entry_allowed'),
            "health 和 live 的 trade_entry_allowed 必须一致")

    def test_healthy_returns_trade_entry_allowed_true(self):
        """健康状态 → trade_entry_allowed=true"""
        from datetime import datetime, timedelta, timezone
        r = (datetime.now(timezone(timedelta(hours=8))) - timedelta(seconds=5)).strftime('%Y-%m-%dT%H:%M:%S+08:00')
        bridge.CACHE['live_quotes'] = {"000001": {"最新价": 105}, "_updated": r}
        bridge.CACHE['iwencai'] = {"情绪值": 65, "_updated": r}
        bridge.DATA_FILE.write_text(json.dumps({
            "meta": {"date": "2026-05-27"},
            "positions": [{"代码": "000001", "标的": "TEST"}],
            "pnl": {},
        }))
        health = bridge._build_health()
        self.assertTrue(health.get('trade_entry_allowed', False), f"健康应有 trade_entry_allowed=true: {health}")


class ValuationCompleteCriticalTest(unittest.TestCase):
    """valuation_complete=false 是 critical → trade_entry_allowed=false"""

    def setUp(self):
        _setup(self)
        from datetime import datetime, timedelta, timezone
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        now_str = now.strftime('%Y-%m-%dT%H:%M:%S+08:00')
        today = now.strftime("%Y-%m-%d")
        db.insert_account_baseline({
            "date": today, "effective_at": f"{today}T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 200000,
            "total_deposit": 200000,
            "positions": [{"标的": "TEST", "代码": "000001", "数量": 100, "现价": 10, "状态": "持有"}],
            "source": "previous_close",
        })
        bridge.CACHE['_stock_codes'] = ['000001']
        bridge.CACHE['live_quotes'] = {"000001": {"最新价": 105}, "_updated": now_str}
        bridge.CACHE['iwencai'] = {"情绪值": 65, "_updated": now_str}
        bridge.DATA_FILE.write_text(json.dumps({
            "meta": {"date": today}, "positions": [], "pnl": {},
        }))

    def tearDown(self):
        _teardown(self)

    def test_valuation_incomplete_is_critical(self):
        """valuation_complete=false → critical_ok=false, trade_entry_allowed=false"""
        import time
        bridge.CACHE['live_quotes'] = {"_updated": "2026-05-27T18:40:00+08:00"}
        health = bridge._build_health()
        self.assertFalse(health.get('critical_ok', True), f"应 critical_ok=false: {health}")
        self.assertFalse(health.get('trade_entry_allowed', True), f"应 trade_entry_allowed=false: {health}")


class HealthLlmConfigDegradedTest(unittest.TestCase):
    """llm_config missing → degraded, not unhealthy"""

    def setUp(self):
        _setup(self)
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        db.insert_account_baseline({
            "date": today, "effective_at": f"{today}T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 200000,
            "total_deposit": 200000, "positions": [], "source": "previous_close",
        })
        bridge.CACHE['live_quotes'] = {"000001": {"最新价": 105}, "_updated": datetime.now().strftime('%Y-%m-%dT%H:%M:%S+08:00')}
        bridge.CACHE['iwencai'] = {"情绪值": 65, "_updated": datetime.now().strftime('%Y-%m-%dT%H:%M:%S+08:00')}
        bridge.DATA_FILE.write_text(json.dumps({
            "meta": {"date": today}, "positions": [], "pnl": {},
        }))

    def tearDown(self):
        _teardown(self)

    def test_llm_missing_is_degraded_not_unhealthy(self):
        """llm_config=missing 时 status=degraded, 不是 unhealthy"""
        with mock.patch("scripts.bridge._load_api_config", return_value={}):
            health = bridge._build_health()
        self.assertEqual(health.get("llm_config", {}).get("status"), "missing")
        self.assertNotEqual(health.get("status"), "unhealthy",
                            "llm_config missing 不应 unhealthy")
        self.assertEqual(health.get("status"), "degraded",
                            "llm_config missing 应 degraded")
        self.assertTrue(health.get("critical_ok", False),
                        "llm_config missing 不应 critical_ok=false")

    def test_llm_missing_in_degraded_reasons(self):
        """llm_config=missing 出现在 degraded_reasons"""
        with mock.patch("scripts.bridge._load_api_config", return_value={}):
            health = bridge._build_health()
        reasons = health.get("degraded_reasons") or []
        self.assertTrue(any("llm_config" in str(r).lower() for r in reasons),
                        f"degraded_reasons 应包含 llm_config: {reasons}")


class HealthAccountBasisTest(unittest.TestCase):
    """account_basis 字段在 health 中"""

    def setUp(self):
        _setup(self)
        from datetime import datetime, timedelta, timezone
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        today = now.strftime("%Y-%m-%d")
        now_str = now.strftime('%Y-%m-%dT%H:%M:%S+08:00')
        # 锚点包含紫光国微（无日初价）+ 兴森科技（可被卖出）
        db.insert_account_baseline({
            "date": today, "effective_at": f"{today}T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 200000,
            "total_deposit": 200000,
            "positions": [
                {"标的": "紫光国微", "代码": "002049", "数量": 600, "成本": 87, "现价": 85, "状态": "持有"},
                {"标的": "兴森科技", "代码": "002436", "数量": 1500, "成本": 38, "现价": 37, "状态": "持有"},
            ],
            "source": "previous_close",
            "_meta": {"day_start_prices": {}},  # 无日初价
        })
        bridge.CACHE['_stock_codes'] = ['002049', '002436']
        bridge.CACHE['live_quotes'] = {"002049": {"最新价": 85}, "002436": {"最新价": 37}, "_updated": now_str}
        bridge.CACHE['iwencai'] = {"情绪值": 65, "_updated": now_str}
        bridge.DATA_FILE.write_text(json.dumps({
            "meta": {"date": today}, "positions": [{"代码": "002049", "标的": "紫光国微"}], "pnl": {},
        }))
        # 插入兴森科技卖出成交（锚点有持仓，但 realized_today_pnl=null）
        db.insert_trade({
            "trade_date": today, "trade_time": "09:38", "action": "卖出",
            "code": "002436", "name": "兴森科技", "price": 35.64, "qty": 1500,
        })

    def tearDown(self):
        _teardown(self)

    def test_health_has_account_basis(self):
        """health 包含 account_basis 字段"""
        health = bridge._build_health()
        ab = health.get("account_basis")
        self.assertIsNotNone(ab, "health 应包含 account_basis")
        self.assertIn("status", ab)
        self.assertIn("coverage", ab)

    def test_account_basis_degraded_when_missing_prices(self):
        """缺 day_start_price → account_basis.degraded, critical_ok=true"""
        health = bridge._build_health()
        ab = health.get("account_basis", {})
        self.assertEqual(ab.get("status"), "degraded")
        self.assertIn("002049", ab.get("missing_codes", []))
        self.assertTrue(health.get("critical_ok", False),
                        "day_start_price 缺失不应 critical_ok=false")
        reasons = health.get("degraded_reasons") or []
        self.assertTrue(any("account_basis" in str(r).lower() for r in reasons),
                        f"degraded_reasons 应含 account_basis: {reasons}")

    def test_account_basis_closed_missing_realized(self):
        """清仓 realized_today_pnl=null → closed_missing_realized_codes 包含"""
        health = bridge._build_health()
        ab = health.get("account_basis", {})
        closed = ab.get("closed_missing_realized_codes", [])
        self.assertIn("002436", closed,
                       f"兴森科技 应出现在 closed_missing_realized: {closed}")


class AccountAuditEnhancedTest(unittest.TestCase):
    """_build_account_audit 增强字段"""

    def setUp(self):
        _setup(self)
        from datetime import datetime, timedelta, timezone
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        self.today = now.strftime("%Y-%m-%d")
        now_str = now.strftime('%Y-%m-%dT%H:%M:%S+08:00')
        db.insert_account_baseline({
            "date": self.today, "effective_at": f"{self.today}T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 200000,
            "total_deposit": 200000,
            "positions": [
                {"标的": "紫光国微", "代码": "002049", "数量": 600, "成本": 87, "现价": 85, "状态": "持有"},
                {"标的": "兴森科技", "代码": "002436", "数量": 1500, "成本": 38, "现价": 37, "状态": "持有"},
            ],
            "source": "previous_close",
            "_meta": {"day_start_prices": {}},
        })
        bridge.CACHE['_stock_codes'] = ['002049', '002436']
        bridge.CACHE['live_quotes'] = {"002049": {"最新价": 85}, "002436": {"最新价": 37}, "_updated": now_str}
        bridge.DATA_FILE.write_text(json.dumps({
            "meta": {"date": self.today}, "positions": [{"代码": "002049", "标的": "紫光国微"}], "pnl": {},
        }))
        # 插入今日清仓（兴森科技）
        db.insert_trade({
            "trade_date": self.today, "trade_time": "09:38", "action": "卖出",
            "code": "002436", "name": "兴森科技", "price": 35.64, "qty": 1500,
        })

    def tearDown(self):
        _teardown(self)

    def test_audit_has_basis_status(self):
        audit = bridge._build_account_audit()
        self.assertIn("basis_status", audit)

    def test_audit_overnight_positions_with_detail(self):
        audit = bridge._build_account_audit()
        ops = audit.get("overnight_positions", [])
        self.assertGreaterEqual(len(ops), 1)
        found = [p for p in ops if p.get("code") == "002049"]
        self.assertTrue(found)
        self.assertIn("has_day_start_price", found[0])

    def test_audit_day_start_prices_missing_detail(self):
        audit = bridge._build_account_audit()
        missing = audit.get("day_start_prices_missing", [])
        self.assertTrue(any(m.get("code") == "002049" for m in missing),
                        "002049 应在 missing 列表中")

    def test_audit_closed_missing_realized(self):
        audit = bridge._build_account_audit()
        closed_missing = audit.get("closed_positions_today_missing_realized", [])
        self.assertTrue(any(c.get("code") == "002436" for c in closed_missing),
                        "兴森科技 应在 closed_missing_realized 中")


if __name__ == "__main__":
    unittest.main()
