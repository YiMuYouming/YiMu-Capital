"""test_anchor_integrity.py — Recovery anchor trust rules (W22-GUARD-R3)"""
import json, tempfile, threading, unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import scripts.db as db
import scripts.account_ssot as ssot


def _setup_temp_db(test):
    test.tmp = tempfile.TemporaryDirectory()
    test.orig_path = db.DB_PATH
    test.orig_local = db._local
    db.DB_PATH = Path(test.tmp.name) / "test.db"
    db._local = threading.local()
    db.init_db()


def _teardown_temp_db(test):
    db.close_conn()
    db.DB_PATH = test.orig_path
    db._local = test.orig_local
    test.tmp.cleanup()


class ExistingRecoveryBlockedTest(unittest.TestCase):

    def setUp(self):
        _setup_temp_db(self)

    def tearDown(self):
        _teardown_temp_db(self)

    def test_existing_recovery_with_positions_blocked(self):
        """DB 中已存在 recovery+持仓 → blocked, valuation_complete=false"""
        db.insert_account_baseline({
            "date": "2026-05-27", "effective_at": "2026-05-27T09:25:00",
            "trade_id_cutoff": 0, "cash": 125279, "day_start_asset": 209786,
            "total_deposit": 200000,
            "positions": [{"标的": "X", "代码": "000001", "成本": 10, "数量": 100, "状态": "持有"}],
            "source": "recovery",
        })
        result = ssot.ensure_today_anchor({"pnl": {}, "positions": []}, day_start_asset=0,
            now="2026-05-27T09:35:00",
            get_anchor=db.query_account_baseline, insert_anchor=db.insert_account_baseline,
            get_last_trade_id=db.query_last_trade_id)
        self.assertEqual(result.get("source"), "blocked")
        self.assertIn("existing recovery", result.get("block_reason", ""))

    def test_existing_recovery_no_positions_allowed(self):
        """recovery+无持仓 → 允许"""
        db.insert_account_baseline({
            "date": "2026-05-27", "effective_at": "2026-05-27T09:25:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 100000,
            "total_deposit": 100000, "positions": [], "source": "recovery",
        })
        result = ssot.ensure_today_anchor({"pnl": {}, "positions": []}, day_start_asset=0,
            now="2026-05-27T09:35:00",
            get_anchor=db.query_account_baseline, insert_anchor=db.insert_account_baseline,
            get_last_trade_id=db.query_last_trade_id)
        self.assertEqual(result.get("source"), "recovery")

    def test_existing_prev_close_with_positions_trusted(self):
        """previous_close+持仓 → 正常"""
        db.insert_account_baseline({
            "date": "2026-05-27", "effective_at": "2026-05-27T09:25:00",
            "trade_id_cutoff": 0, "cash": 67859, "day_start_asset": 209786,
            "total_deposit": 200000,
            "positions": [{"标的": "X", "代码": "000001", "成本": 10, "数量": 100, "状态": "持有"}],
            "source": "previous_close",
        })
        result = ssot.ensure_today_anchor({"pnl": {}, "positions": []}, day_start_asset=0,
            now="2026-05-27T09:35:00",
            get_anchor=db.query_account_baseline, insert_anchor=db.insert_account_baseline,
            get_last_trade_id=db.query_last_trade_id)
        self.assertEqual(result.get("source"), "previous_close")
        self.assertAlmostEqual(result["cash"], 67859, delta=0.01)

    def test_existing_manual_correction_with_positions_trusted(self):
        """manual_correction+持仓 → 正常"""
        db.insert_account_baseline({
            "date": "2026-05-27", "effective_at": "2026-05-27T09:25:00",
            "trade_id_cutoff": 0, "cash": 67859, "day_start_asset": 209786,
            "total_deposit": 200000,
            "positions": [{"标的": "X", "代码": "000001", "成本": 10, "数量": 100, "状态": "持有"}],
            "source": "manual_correction",
        })
        result = ssot.ensure_today_anchor({"pnl": {}, "positions": []}, day_start_asset=0,
            now="2026-05-27T09:35:00",
            get_anchor=db.query_account_baseline, insert_anchor=db.insert_account_baseline,
            get_last_trade_id=db.query_last_trade_id)
        self.assertEqual(result.get("source"), "manual_correction")

    def test_missing_anchor_with_positions_blocked_no_create(self):
        """缺 anchor + 有持仓 → blocked，不创建记录"""
        data = {
            "pnl": {"可用资金": 67859, "累计入金": 200000},
            "positions": [{"标的": "X", "代码": "000001", "成本": 10, "数量": 100, "状态": "持有"}],
            "meta": {"date": "2026-05-27"},
        }
        result = ssot.ensure_today_anchor(data, day_start_asset=209786, now="2026-05-27T09:35:00",
            get_anchor=db.query_account_baseline, insert_anchor=db.insert_account_baseline,
            get_last_trade_id=db.query_last_trade_id)
        self.assertEqual(result.get("source"), "blocked")
        self.assertIsNone(db.query_account_baseline("2026-05-27"))


class AnchorTrustedStateTest(unittest.TestCase):

    def setUp(self):
        _setup_temp_db(self)

    def tearDown(self):
        _teardown_temp_db(self)

    def _load_with(self, source, positions=None):
        if positions is None:
            positions = [{"标的": "X", "代码": "000001", "成本": 10, "数量": 100, "状态": "持有"}]
        db.insert_account_baseline({
            "date": "2026-05-27", "effective_at": "2026-05-27T09:25:00",
            "trade_id_cutoff": 0, "cash": 67859, "day_start_asset": 209786,
            "total_deposit": 200000, "positions": positions, "source": source,
        })
        dp = Path(self.tmp.name) / "d.json"
        hp = Path(self.tmp.name) / "p.json"
        dp.write_text(json.dumps({"pnl": {}, "positions": [], "meta": {"date": "2026-05-27"}}))
        hp.write_text(json.dumps({"meta": {}}))
        return ssot.load_current_account_state(
            {"000001": {"最新价": 12}, "_updated": "2026-05-27T09:40:00+08:00"},
            now="2026-05-27T09:40:00", data_file=str(dp), history_file=str(hp))

    def test_recovery_positions_untrusted(self):
        state = self._load_with("recovery")
        self.assertFalse(state.get("anchor_trusted"))
        self.assertFalse(state.get("valuation_complete"))

    def test_prev_close_positions_trusted(self):
        state = self._load_with("previous_close")
        self.assertTrue(state.get("anchor_trusted"))
        self.assertTrue(state.get("valuation_complete"))

    def test_manual_correction_positions_trusted(self):
        state = self._load_with("manual_correction")
        self.assertTrue(state.get("anchor_trusted"))
        self.assertTrue(state.get("valuation_complete"))


if __name__ == "__main__":
    unittest.main()
