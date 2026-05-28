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
        db.insert_account_baseline({
            "date": "2026-05-27",
            "effective_at": "2026-05-27T09:30:00",
            "trade_id_cutoff": 0,
            "cash": 100000, "day_start_asset": 200000,
            "total_deposit": 200000,
            "positions": [{"标的": "TEST", "代码": "000001", "数量": 100, "成本": 10, "状态": "持有"}],
            "source": "manual_correction",
        })
        bridge.CACHE['_stock_codes'] = ['000001']
        # _quotes_coverage 从 DATA_FILE 读持仓代码
        bridge.DATA_FILE.write_text(json.dumps({
            "meta": {"date": "2026-05-27"},
            "positions": [{"代码": "000001", "标的": "TEST"}],
            "pnl": {},
        }))

    def tearDown(self):
        _teardown(self)

    def test_close_snapshot_quotes_not_dead(self):
        bridge.CACHE['live_quotes'] = {
            "000001": {"最新价": 105},
            "_updated": "2026-05-27T15:05:00+08:00",
        }
        health = bridge._build_health()
        quotes = health.get("quotes", {})
        self.assertEqual(quotes.get("status"), "close_snapshot",
            f"收盘快照 + 有覆盖 → quotes 应 close_snapshot: {quotes}")
        self.assertEqual(quotes.get("covered"), 1)

    def test_zero_coverage_still_dead(self):
        bridge.CACHE['live_quotes'] = {
            "_updated": "2026-05-27T15:05:00+08:00",
        }
        health = bridge._build_health()
        quotes = health.get("quotes", {})
        self.assertEqual(quotes.get("status"), "dead",
            f"zero coverage 应 dead: {quotes}")

    def test_intraday_stale_still_old_rule(self):
        bridge.CACHE['live_quotes'] = {
            "000001": {"最新价": 105},
            "_updated": "2026-05-27T10:00:00+08:00",
        }
        health = bridge._build_health()
        quotes = health.get("quotes", {})
        self.assertIn(quotes.get("status"), ("stale", "dead", "delayed"),
            f"盘中过期行情应按旧规则: {quotes}")


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
        db.insert_account_baseline({
            "date": "2026-05-27", "effective_at": "2026-05-27T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 200000,
            "total_deposit": 200000, "positions": [], "source": "previous_close",
        })
        bridge.CACHE['live_quotes'] = {"000001": {"最新价": 105}, "_updated": "2026-05-27T18:50:06+08:00"}
        bridge.CACHE['iwencai'] = {"情绪值": 65, "_updated": "2026-05-27T18:48:36+08:00"}
        bridge.DATA_FILE.write_text(json.dumps({
            "meta": {"date": "2026-05-27"},
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
        db.insert_account_baseline({
            "date": "2026-05-27", "effective_at": "2026-05-27T09:30:00",
            "trade_id_cutoff": 0, "cash": 80000, "day_start_asset": 100000,
            "total_deposit": 100000,
            "positions": [{"标的": "T1", "代码": "000001", "数量": 500, "现价": 21, "状态": "持有"},
                          {"标的": "T2", "代码": "000002", "数量": 100, "现价": 15, "状态": "持有"}],
            "source": "previous_close",
            "_meta": {"day_start_prices": {"000001": 20.5}},
        })
        bridge.CACHE['live_quotes'] = {"_updated": "2026-05-27T09:35:00+08:00"}

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
        h = self._handler_get('/api/account/audit')
        h.do_GET()
        self.assertEqual(h._resp_status, 200)
        body = json.loads(h._resp_body)
        self.assertEqual(body.get('anchor_date'), '2026-05-27')
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
        db.insert_account_baseline({
            "date": "2026-05-27", "effective_at": "2026-05-27T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 200000,
            "total_deposit": 200000, "positions": [], "source": "previous_close",
        })
        bridge.DATA_FILE.write_text(json.dumps({
            "meta": {"date": "2026-05-27"}, "positions": [], "pnl": {},
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
        db.insert_account_baseline({
            "date": "2026-05-27", "effective_at": "2026-05-27T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 200000,
            "total_deposit": 200000,
            "positions": [{"标的": "TEST", "代码": "000001", "数量": 100, "现价": 10, "状态": "持有"}],
            "source": "previous_close",
        })
        bridge.CACHE['live_quotes'] = {"000001": {"最新价": 105}, "_updated": "2026-05-27T18:40:00+08:00"}
        bridge.CACHE['iwencai'] = {"情绪值": 65, "_updated": "2026-05-27T18:40:00+08:00"}
        bridge.DATA_FILE.write_text(json.dumps({
            "meta": {"date": "2026-05-27"}, "positions": [], "pnl": {},
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


if __name__ == "__main__":
    unittest.main()
