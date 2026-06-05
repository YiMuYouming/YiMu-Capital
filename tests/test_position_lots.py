"""Tests for position lots and FIFO allocation records."""
import json
import tempfile
import threading
import unittest
from pathlib import Path

import scripts.db as db
from scripts.account_ssot import load_current_account_state


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
        "meta": {"day_start_date": "2026-06-04", "day_start_asset": 200000}
    }, ensure_ascii=False))


def _teardown_temp_db(test):
    db.close_conn()
    db.DB_PATH = test.orig_path
    db._local = test.orig_local
    test.tmp.cleanup()


def _columns(table):
    return {row["name"] for row in db._exec(f"PRAGMA table_info({table})")}


class PositionLotsSchemaTest(unittest.TestCase):
    def setUp(self):
        _setup_temp_db(self)

    def tearDown(self):
        _teardown_temp_db(self)

    def test_lot_tables_exist(self):
        tables = {row["name"] for row in db._exec(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        self.assertIn("position_lots", tables)
        self.assertIn("trade_lot_allocations", tables)

    def test_position_lots_columns_exist(self):
        cols = _columns("position_lots")
        expected = {
            "lot_id", "created_at", "code", "name", "source_trade_id",
            "source_ticket_id", "buy_date", "original_qty", "open_qty",
            "cost_price", "locked_until", "lot_source", "migration_source", "status",
        }
        self.assertTrue(expected <= cols, f"missing columns: {sorted(expected - cols)}")

    def test_trade_lot_allocations_columns_exist(self):
        cols = _columns("trade_lot_allocations")
        expected = {
            "id", "sell_trade_id", "lot_id", "qty", "cost_price", "sell_price",
            "realized_pnl",
        }
        self.assertTrue(expected <= cols, f"missing columns: {sorted(expected - cols)}")

    def test_lot_indexes_exist(self):
        indexes = {row["name"] for row in db._exec(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
        expected = {
            "idx_lot_code_status",
            "idx_lot_locked_until",
            "idx_alloc_sell_trade",
        }
        self.assertTrue(expected <= indexes, f"missing indexes: {sorted(expected - indexes)}")

    def test_buy_trade_creates_locked_lot(self):
        lot_id = db.create_lot_from_buy_trade({
            "id": 1,
            "trade_date": "2026-06-03",
            "action": "买入",
            "code": "002475",
            "name": "立讯精密",
            "price": 75.31,
            "qty": 2000,
        })

        lot = db.query_position_lots(code="002475")[0]
        self.assertEqual(lot["lot_id"], lot_id)
        self.assertEqual(lot["original_qty"], 2000)
        self.assertEqual(lot["open_qty"], 2000)
        self.assertEqual(lot["buy_date"], "2026-06-03")
        self.assertEqual(lot["locked_until"], "2026-06-04")
        self.assertEqual(lot["status"], "open")

    def test_same_day_sell_blocks_locked_shares(self):
        db.create_lot_from_buy_trade({
            "id": 1, "trade_date": "2026-06-03", "action": "买入",
            "code": "002475", "name": "立讯精密", "price": 75.31, "qty": 2000,
        })

        self.assertEqual(db.get_sellable_qty("002475", "2026-06-03"), 0)
        with self.assertRaises(ValueError):
            db.allocate_sell_to_lots({
                "id": 2, "trade_date": "2026-06-03", "action": "卖出",
                "code": "002475", "price": 75.00, "qty": 100,
            })

    def test_next_day_sell_allocates_and_decrements_open_qty(self):
        db.create_lot_from_buy_trade({
            "id": 1, "trade_date": "2026-06-03", "action": "买入",
            "code": "002475", "name": "立讯精密", "price": 75.31, "qty": 2000,
        })

        allocations = db.allocate_sell_to_lots({
            "id": 2, "trade_date": "2026-06-04", "action": "卖出",
            "code": "002475", "price": 76.00, "qty": 500,
        })

        lot = db.query_position_lots(code="002475")[0]
        self.assertEqual(lot["open_qty"], 1500)
        self.assertEqual(allocations[0]["qty"], 500)
        self.assertAlmostEqual(allocations[0]["realized_pnl"], (76.00 - 75.31) * 500)

    def test_fifo_across_multiple_lots_decrements_each_consumed_lot(self):
        for lot_id, qty, cost in [("A", 300, 70), ("B", 400, 72), ("C", 500, 74)]:
            db._exec_write("""INSERT INTO position_lots
                (lot_id, code, name, buy_date, original_qty, open_qty, cost_price,
                 locked_until, lot_source, migration_source, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (lot_id, "002475", "立讯精密", "2026-06-03", qty, qty, cost,
                 "2026-06-04", "test", "test", "open"))

        allocations = db.allocate_sell_to_lots({
            "id": 10, "trade_date": "2026-06-04", "action": "卖出",
            "code": "002475", "price": 76.00, "qty": 650,
        })
        lots = {lot["lot_id"]: lot for lot in db.query_position_lots(code="002475")}

        self.assertEqual([(a["lot_id"], a["qty"]) for a in allocations], [("A", 300), ("B", 350)])
        self.assertEqual(lots["A"]["open_qty"], 0)
        self.assertEqual(lots["A"]["status"], "closed")
        self.assertEqual(lots["B"]["open_qty"], 50)
        self.assertEqual(lots["B"]["status"], "open")
        self.assertEqual(lots["C"]["open_qty"], 500)
        self.assertEqual(lots["C"]["status"], "open")

    def test_target_lot_sell_decrements_selected_lot_instead_of_fifo(self):
        for lot_id, qty, cost in [("overnight", 900, 219.49), ("trade:49", 200, 222.38)]:
            db._exec_write("""INSERT INTO position_lots
                (lot_id, code, name, buy_date, original_qty, open_qty, cost_price,
                 locked_until, lot_source, migration_source, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (lot_id, "002281", "光迅科技", "2026-06-04", qty, qty, cost,
                 "2026-06-05", "test", "test", "open"))

        allocations = db.allocate_sell_to_lots({
            "id": 50, "trade_date": "2026-06-05", "action": "卖出",
            "code": "002281", "price": 232.30, "qty": 200,
            "target_lot_id": "trade:49",
        })
        lots = {lot["lot_id"]: lot for lot in db.query_position_lots(code="002281")}

        self.assertEqual([(a["lot_id"], a["qty"]) for a in allocations], [("trade:49", 200)])
        self.assertEqual(lots["overnight"]["open_qty"], 900)
        self.assertEqual(lots["overnight"]["status"], "open")
        self.assertEqual(lots["trade:49"]["open_qty"], 0)
        self.assertEqual(lots["trade:49"]["status"], "closed")
        self.assertAlmostEqual(allocations[0]["realized_pnl"], (232.30 - 222.38) * 200)

    def test_friday_buy_unlocks_next_monday(self):
        self.assertEqual(db.next_trade_date("2026-06-05"), "2026-06-08")
        db.create_lot_from_buy_trade({
            "id": 1, "trade_date": "2026-06-05", "action": "买入",
            "code": "002475", "name": "立讯精密", "price": 75.31, "qty": 2000,
        })

        lot = db.query_position_lots(code="002475")[0]
        self.assertEqual(lot["locked_until"], "2026-06-08")
        self.assertEqual(db.get_sellable_qty("002475", "2026-06-06"), 0)
        self.assertEqual(db.get_sellable_qty("002475", "2026-06-07"), 0)
        self.assertEqual(db.get_sellable_qty("002475", "2026-06-08"), 2000)

    def test_account_state_includes_lot_breakdown(self):
        db.insert_account_baseline({
            "date": "2026-06-04",
            "effective_at": "2026-06-04T09:00:00",
            "cash": 100000,
            "day_start_asset": 200000,
            "total_deposit": 200000,
            "source": "previous_close",
            "positions": [{
                "标的": "立讯精密", "代码": "002475", "数量": 2000,
                "成本": 75.31, "现价": 76, "状态": "持有",
            }],
            "_meta": {"day_start_prices": {"002475": 75.31}},
        })
        db._exec_write("""INSERT INTO position_lots
            (lot_id, code, name, buy_date, original_qty, open_qty, cost_price,
             locked_until, lot_source, migration_source, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("old", "002475", "立讯精密", "2026-06-03", 1500, 1500, 75.31,
             "2026-06-04", "test", "test", "open"))
        db._exec_write("""INSERT INTO position_lots
            (lot_id, code, name, buy_date, original_qty, open_qty, cost_price,
             locked_until, lot_source, migration_source, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("new", "002475", "立讯精密", "2026-06-04", 500, 500, 76.00,
             "2026-06-05", "test", "test", "open"))

        state = load_current_account_state(
            {"002475": {"最新价": 76}, "_updated": "2026-06-04T10:00:00"},
            now="2026-06-04T10:00:01",
            data_file=self.data_file,
            history_file=self.history_file,
        )

        pos = state["positions"][0]
        self.assertEqual(pos["sellable_qty"], 1500)
        self.assertEqual(pos["locked_qty"], 500)
        self.assertEqual(len(pos["lots"]), 2)
        self.assertTrue(pos["lot_reconciliation_ok"])

    def test_lot_close_only_trade_preserves_anchor_quantity_and_adds_realized_pnl(self):
        db.insert_account_baseline({
            "date": "2026-06-05",
            "effective_at": "2026-06-05T09:25:00",
            "cash": 376215.67,
            "day_start_asset": 723899.67,
            "total_deposit": 700000,
            "source": "previous_close",
            "positions": [{
                "标的": "光迅科技", "代码": "002281", "数量": 900,
                "成本": 219.49, "现价": 224.0, "状态": "持有",
            }],
            "_meta": {"day_start_prices": {"002281": 224.0}},
        })
        for lot_id, qty, cost in [("overnight:2026-06-04:002281", 900, 219.49), ("trade:49", 200, 222.38)]:
            db._exec_write("""INSERT INTO position_lots
                (lot_id, code, name, buy_date, original_qty, open_qty, cost_price,
                 locked_until, lot_source, migration_source, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (lot_id, "002281", "光迅科技", "2026-06-04", qty, qty, cost,
                 "2026-06-05", "test", "test", "open"))
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-05", "code": "002281", "name": "光迅科技",
            "action_type": "reduce", "status": "executable",
            "t1_risk_json": {
                "target_lot_id": "trade:49",
                "account_effect": "realized_pnl_only",
            },
        })

        result = db.record_confirmed_fill({
            "trade_date": "2026-06-05", "trade_time": "14:45", "action": "卖出",
            "code": "002281", "name": "光迅科技", "price": 232.30, "qty": 200,
            "ticket_id": ticket_id, "target_lot_id": "trade:49",
            "leg_type": "sell_target_lot_realized_pnl_only",
            "event_id": "target-lot-sell-001",
        })

        self.assertEqual(result["status"], "inserted")
        lots = {lot["lot_id"]: lot for lot in db.query_position_lots(code="002281")}
        self.assertEqual(lots["overnight:2026-06-04:002281"]["open_qty"], 900)
        self.assertEqual(lots["trade:49"]["open_qty"], 0)
        trade = dict(db._exec("SELECT * FROM trade_records WHERE id = ?", (result["trade_id"],))[0])
        self.assertEqual(trade["leg_type"], "sell_target_lot_realized_pnl_only")
        self.assertAlmostEqual(trade["realized_pnl"], (232.30 - 222.38) * 200)

        state = load_current_account_state(
            {"002281": {"最新价": 232.30}, "_updated": "2026-06-05T14:50:00"},
            now="2026-06-05T14:50:01",
            data_file=self.data_file,
            history_file=self.history_file,
        )

        pos = state["positions"][0]
        self.assertEqual(pos["数量"], 900)
        self.assertEqual(pos["sellable_qty"], 900)
        self.assertTrue(pos["lot_reconciliation_ok"])
        self.assertAlmostEqual(state["cash"], 376215.67 + (232.30 - 222.38) * 200)


if __name__ == "__main__":
    unittest.main()
