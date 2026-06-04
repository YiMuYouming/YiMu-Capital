"""Schema tests for trade tickets and ticket-linked trade records."""
import tempfile
import threading
import unittest
from pathlib import Path

import scripts.db as db


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


def _columns(table):
    return {row["name"] for row in db._exec(f"PRAGMA table_info({table})")}


class TradeTicketsSchemaTest(unittest.TestCase):
    def setUp(self):
        _setup_temp_db(self)

    def tearDown(self):
        _teardown_temp_db(self)

    def test_ticket_tables_exist(self):
        tables = {row["name"] for row in db._exec(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        for table in {
            "trade_tickets",
            "pending_fill_confirmations",
            "ticket_conflict_log",
        }:
            self.assertIn(table, tables)

    def test_trade_tickets_columns_exist(self):
        cols = _columns("trade_tickets")
        expected = {
            "ticket_id", "created_at", "updated_at", "trade_date", "code", "name",
            "action_type", "status", "window", "intent_text", "rule_state_json",
            "market_snapshot_json", "account_snapshot_json", "max_qty", "max_amount",
            "stop_line", "expected_r", "missing_data_json", "blocking_rule_ids_json",
            "triggered_rule_ids_json", "account_day_return_pct", "trade_return_pct",
            "realized_pnl_pct", "unrealized_pnl_pct", "losing_account_days",
            "losing_trades_streak", "sellable_quantity", "t1_risk_json",
            "human_override_reason", "funds_evidence_json", "style_score_raw",
            "style_score_adjusted", "style_adjustment_reason",
            "style_adjustment_approver", "style_script_version", "rule_pack_version",
            "rule_snapshot_hash", "today_execution_card_id", "funds_source_freshness",
            "funds_query_time", "funds_unit", "eod_outcome_json", "linked_ticket_id",
            "close_reason", "review_note",
        }
        self.assertTrue(expected <= cols, f"missing columns: {sorted(expected - cols)}")

    def test_pending_confirmation_columns_exist(self):
        cols = _columns("pending_fill_confirmations")
        expected = {
            "confirmation_id", "created_at", "expires_at", "ticket_id", "input_text",
            "parsed_entry_json", "preview_token", "preview_hash", "status",
            "confirmed_at", "confirmed_by",
        }
        self.assertTrue(expected <= cols, f"missing columns: {sorted(expected - cols)}")

    def test_ticket_conflict_log_columns_exist(self):
        cols = _columns("ticket_conflict_log")
        expected = {
            "id", "created_at", "trade_date", "ticket_id", "code", "conflict_type",
            "severity", "expected_json", "actual_json", "resolution_status", "note",
        }
        self.assertTrue(expected <= cols, f"missing columns: {sorted(expected - cols)}")

    def test_trade_records_has_ticket_aware_columns(self):
        cols = _columns("trade_records")
        expected = {
            "ticket_id", "trade_group_id", "leg_type", "sellable_qty_before",
            "locked_until", "input_source", "input_text", "confirmed_by", "audit_note",
        }
        self.assertTrue(expected <= cols, f"missing columns: {sorted(expected - cols)}")

    def test_ticket_indexes_exist(self):
        indexes = {row["name"] for row in db._exec(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
        expected = {
            "idx_ticket_date_status",
            "idx_ticket_code_date",
            "idx_pending_confirm_status",
            "idx_ticket_conflict",
        }
        self.assertTrue(expected <= indexes, f"missing indexes: {sorted(expected - indexes)}")

    def test_create_and_query_trade_ticket(self):
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-03",
            "code": "002281",
            "name": "光迅科技",
            "action_type": "buy",
            "status": "draft",
            "window": "W2",
            "intent_text": "准备买 光迅科技",
            "max_qty": 100,
            "stop_line": 202.76,
            "rule_state_json": {"tradable": True},
            "triggered_rule_ids_json": ["WIN-W2-001"],
            "today_execution_card_id": "EXEC-20260603",
            "rule_snapshot_hash": "hash-1",
        })

        self.assertTrue(ticket_id.startswith("TICKET-20260603-002281"))
        ticket = db.query_trade_ticket(ticket_id)
        self.assertEqual(ticket["status"], "draft")
        self.assertEqual(ticket["code"], "002281")
        self.assertEqual(ticket["rule_state"], {"tradable": True})
        self.assertEqual(ticket["triggered_rule_ids"], ["WIN-W2-001"])

    def test_query_update_and_link_ticket(self):
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-03",
            "code": "002281",
            "name": "光迅科技",
            "action_type": "buy",
            "status": "draft",
        })
        db.insert_trade({
            "trade_date": "2026-06-03",
            "trade_time": "10:00",
            "action": "买入",
            "code": "002281",
            "name": "光迅科技",
            "price": 220,
            "qty": 100,
        })
        trade_id = db._exec("SELECT id FROM trade_records")[0]["id"]

        self.assertTrue(db.update_trade_ticket_status(
            ticket_id, "closed", close_reason="filled", review_note="ok"
        ))
        self.assertTrue(db.link_trade_to_ticket(
            trade_id, ticket_id, "grp-1", "open", sellable_qty_before=900,
            locked_until="2026-06-04",
        ))

        tickets = db.query_trade_tickets(date_from="2026-06-03", code="002281", status="closed")
        trade = dict(db._exec("SELECT * FROM trade_records WHERE id = ?", (trade_id,))[0])
        self.assertEqual([row["ticket_id"] for row in tickets], [ticket_id])
        self.assertEqual(trade["ticket_id"], ticket_id)
        self.assertEqual(trade["trade_group_id"], "grp-1")
        self.assertEqual(trade["sellable_qty_before"], 900)


if __name__ == "__main__":
    unittest.main()
