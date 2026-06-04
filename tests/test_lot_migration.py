"""Tests for migrating current holdings and same-day trades into position lots."""
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path

import scripts.db as db
from scripts.account_ssot import load_current_account_state
from scripts.ops import migrate_position_lots


DATE = "2026-06-03"


def _setup_temp_db(test):
    test.tmp = tempfile.TemporaryDirectory()
    test.orig_path = db.DB_PATH
    test.orig_local = db._local
    db.DB_PATH = Path(test.tmp.name) / "test.db"
    db._local = threading.local()
    db.init_db()
    test.data_file = Path(test.tmp.name) / "dashboard_data.json"
    test.history_file = Path(test.tmp.name) / "pnl_history.json"
    test.data_file.write_text(json.dumps({"pnl": {}, "positions": []}, ensure_ascii=False))
    test.history_file.write_text(json.dumps({
        "meta": {"day_start_date": DATE, "day_start_asset": 200000}
    }, ensure_ascii=False))


def _teardown_temp_db(test):
    db.close_conn()
    db.DB_PATH = test.orig_path
    db._local = test.orig_local
    test.tmp.cleanup()


def _insert_anchor(qty=900, cost=219.49):
    db.insert_account_baseline({
        "date": DATE,
        "effective_at": f"{DATE}T09:00:00",
        "trade_id_cutoff": 0,
        "cash": 100000,
        "day_start_asset": 200000,
        "total_deposit": 200000,
        "source": "previous_close",
        "positions": [{
            "标的": "光迅科技",
            "代码": "002281",
            "数量": qty,
            "成本": cost,
            "现价": cost,
            "状态": "持有",
        }],
        "_meta": {"day_start_prices": {"002281": cost}},
    })


class LotMigrationTest(unittest.TestCase):
    def setUp(self):
        _setup_temp_db(self)

    def tearDown(self):
        _teardown_temp_db(self)

    def test_overnight_lot_created_from_account_baseline(self):
        _insert_anchor()

        result = migrate_position_lots.run_migration(DATE, apply=True)

        rows = [dict(row) for row in db._exec("SELECT * FROM position_lots")]
        self.assertEqual(result["status"], "applied")
        self.assertEqual(len(rows), 1)
        lot = rows[0]
        self.assertEqual(lot["code"], "002281")
        self.assertEqual(lot["open_qty"], 900)
        self.assertEqual(lot["cost_price"], 219.49)
        self.assertEqual(lot["locked_until"], DATE)
        self.assertEqual(lot["lot_source"], "overnight_anchor")
        self.assertEqual(lot["status"], "open")
        self.assertEqual(migrate_position_lots.get_sellable_qty("002281", DATE), 900)

    def test_replay_same_day_trades_keeps_new_buys_locked(self):
        _insert_anchor()
        for trade_time, action, price, qty in [
            ("10:14", "买入", 225.78, 100),
            ("10:15", "买入", 226.42, 100),
            ("14:56", "卖出", 223.80, 200),
        ]:
            db.insert_trade({
                "trade_date": DATE,
                "trade_time": trade_time,
                "action": action,
                "code": "002281",
                "name": "光迅科技",
                "price": price,
                "qty": qty,
            })

        migrate_position_lots.run_migration(DATE, apply=True)

        lots = [dict(row) for row in db._exec("SELECT * FROM position_lots ORDER BY lot_id")]
        open_sum = sum(row["open_qty"] for row in lots)
        same_day_lots = [row for row in lots if row["lot_source"] == "same_day_trade"]
        overnight = [row for row in lots if row["lot_source"] == "overnight_anchor"][0]
        allocs = [dict(row) for row in db._exec("""
            SELECT a.qty, l.lot_source
            FROM trade_lot_allocations a
            JOIN position_lots l ON l.lot_id = a.lot_id
        """)]

        self.assertEqual(overnight["open_qty"], 700)
        self.assertEqual(open_sum, 900)
        self.assertEqual([row["open_qty"] for row in same_day_lots], [100, 100])
        self.assertEqual({row["locked_until"] for row in same_day_lots}, {"2026-06-04"})
        self.assertEqual(allocs, [{"qty": 200, "lot_source": "overnight_anchor"}])
        self.assertEqual(migrate_position_lots.get_sellable_qty("002281", DATE), 700)

    def test_lot_account_mismatch_exposes_fail_closed_state(self):
        _insert_anchor()
        db._exec_write("""INSERT INTO position_lots
            (lot_id, code, name, buy_date, original_qty, open_qty, cost_price,
             locked_until, lot_source, migration_source, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("manual:002281", "002281", "光迅科技", DATE, 700, 700, 219.49,
             DATE, "manual", "test", "open"))

        state = load_current_account_state(
            {"002281": {"最新价": 220}, "_updated": f"{DATE}T10:00:00"},
            now=f"{DATE}T10:00:01",
            data_file=self.data_file,
            history_file=self.history_file,
        )

        self.assertFalse(state["lot_reconciliation_ok"])
        self.assertIn("sell", state["lot_reconciliation_block_actions"])
        self.assertIn("do_t", state["lot_reconciliation_block_actions"])
        self.assertIn("lot/account quantity mismatch", state["lot_reconciliation_errors"][0]["message"])

    def test_dry_run_reports_without_writing(self):
        _insert_anchor()
        out = io.StringIO()

        result = migrate_position_lots.run_migration(DATE, dry_run=True, out=out)

        self.assertEqual(result["status"], "dry_run")
        self.assertIn("Would create overnight lot", out.getvalue())
        self.assertEqual(len(db._exec("SELECT * FROM position_lots")), 0)


if __name__ == "__main__":
    unittest.main()
