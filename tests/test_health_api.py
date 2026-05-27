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
