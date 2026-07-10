"""Ticket-aware /api/sync tests."""
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import scripts.db as db
import scripts.bridge as bridge


def _setup(test):
    test.tmp = tempfile.TemporaryDirectory()
    test.orig_path = db.DB_PATH
    test.orig_local = db._local
    test.orig_inited = bridge._db_inited
    test.orig_cache = dict(bridge.CACHE)
    test.orig_ctx = bridge._build_trade_context
    db.DB_PATH = Path(test.tmp.name) / "test.db"
    db._local = threading.local()
    bridge._db_inited = False
    bridge.CACHE.clear()
    bridge.DATA_FILE = Path(test.tmp.name) / "d.json"
    bridge.DATA_FILE.write_text(json.dumps({"meta": {}, "positions": [], "pnl": {}}))
    db.init_db()
    bridge._build_trade_context = lambda: {
        "rule_state": {"version": "g1a-v1", "tradable": True},
        "market_snapshot": {"iwencai": {"情绪值": 65}},
        "context_captured_at": "2026-06-04T10:00:00",
        "context_status": "trusted",
        "context_unavailable_reason": None,
        "rule_pack_version": "g1a-v1",
        "rule_snapshot_hash": "hash-1",
        "today_execution_card_id": "EXEC-20260604",
    }


def _teardown(test):
    db.close_conn()
    db.DB_PATH = test.orig_path
    db._local = test.orig_local
    bridge._db_inited = test.orig_inited
    bridge.CACHE.clear()
    bridge.CACHE.update(test.orig_cache)
    bridge._build_trade_context = test.orig_ctx
    test.tmp.cleanup()


def _handler(payload):
    h = object.__new__(bridge.BridgeHandler)
    h.command = "POST"
    h.path = "/api/sync"
    h.requestline = "POST /api/sync HTTP/1.1"
    h.request_version = "HTTP/1.1"
    h.request = mock.MagicMock()
    h.request.version = "HTTP/1.1"
    h.client_address = ("127.0.0.1", 12345)
    h.server = mock.MagicMock()
    body = json.dumps(payload).encode()
    h.rfile = io.BytesIO(body)
    h.headers = mock.MagicMock()
    h.headers.get = lambda k, d=None: str(len(body))
    h.log_message = mock.MagicMock()
    h._resp_status = None
    h._resp_body = b""
    h.send_response = lambda code, phrase=None: setattr(h, "_resp_status", code)
    h.send_header = lambda key, value: None
    h.end_headers = lambda: None

    def _write(_self, data):
        h._resp_body += data
    h.wfile = type("WFile", (), {"write": _write})()
    return h


def _post(payload):
    h = _handler(payload)
    h.do_POST()
    body = json.loads(h._resp_body.decode()) if h._resp_body else {}
    return h._resp_status, body


class TicketAwareSyncTest(unittest.TestCase):
    def setUp(self):
        _setup(self)

    def tearDown(self):
        _teardown(self)

    def _ticket(self):
        return db.create_trade_ticket({
            "trade_date": "2026-06-04",
            "code": "002281",
            "name": "光迅科技",
            "action_type": "buy",
            "status": "executable",
        })

    def test_confirmed_fill_with_ticket_creates_trade_and_buy_lot(self):
        ticket_id = self._ticket()

        status, body = _post({"entry": {
            "时间": "10:14",
            "动作": "W2买入",
            "标的": "光迅科技",
            "代码": "002281",
            "价格": 225.78,
            "数量": 100,
            "窗口": "W2",
            "原因": "回踩补仓",
            "event_id": "test-event-001",
            "ticket_id": ticket_id,
            "trade_group_id": "TG-20260604-002281-T",
            "leg_type": "buy_add",
            "input_source": "spoken_confirmed",
            "input_text": "已买 光迅科技 100股 225.78",
            "confirmed_by": "yimu",
            "audit_note": "spoken confirmed",
        }})

        self.assertEqual(status, 200, body)
        self.assertEqual(body["status"], "inserted")
        trade = dict(db._exec("SELECT * FROM trade_records")[0])
        self.assertEqual(trade["ticket_id"], ticket_id)
        self.assertEqual(trade["leg_type"], "buy_add")
        self.assertEqual(len(db.query_position_lots(code="002281")), 1)
        self.assertEqual(db.query_trade_ticket(ticket_id)["status"], "filled")

    def test_legacy_sync_without_ticket_is_rejected(self):
        status, body = _post({"entry": {
            "时间": "10:14", "动作": "买入", "标的": "光迅科技", "代码": "002281",
            "价格": 225.78, "数量": 100, "event_id": "legacy-001",
        }})

        self.assertEqual(status, 409, body)
        self.assertEqual(len(db._exec("SELECT * FROM trade_records")), 0)

    def test_manual_backfill_without_ticket_creates_backfill_ticket(self):
        status, body = _post({"entry": {
            "时间": "10:14", "动作": "买入", "标的": "光迅科技", "代码": "002281",
            "价格": 225.78, "数量": 100, "event_id": "backfill-001",
            "input_source": "manual_backfill", "confirmed_by": "yimu",
            "audit_note": "盘后补录", "原因": "盘后补录",
        }})

        self.assertEqual(status, 200, body)
        self.assertTrue(body["ticket_id"].startswith("TICKET-"))
        ticket = db.query_trade_ticket(body["ticket_id"])
        self.assertEqual(ticket["ticket_purpose"], "post_trade_reconciliation")
        self.assertEqual(ticket["rule_snapshot_hash"], "hash-1")
        self.assertEqual(ticket["today_execution_card_id"], "EXEC-20260604")
        self.assertEqual(len(db._exec("SELECT * FROM trade_records")), 1)

    def test_repeated_event_id_is_idempotent(self):
        ticket_id = self._ticket()
        payload = {"entry": {
            "时间": "10:14", "动作": "买入", "标的": "光迅科技", "代码": "002281",
            "价格": 225.78, "数量": 100, "event_id": "repeat-001",
            "ticket_id": ticket_id, "input_source": "spoken_confirmed",
            "confirmed_by": "yimu", "audit_note": "spoken confirmed",
        }}

        first = _post(payload)
        second = _post(payload)

        self.assertEqual(first[0], 200, first)
        self.assertEqual(second[0], 200, second)
        self.assertEqual(second[1]["status"], "idempotent")
        self.assertEqual(len(db._exec("SELECT * FROM trade_records")), 1)
        self.assertEqual(len(db.query_position_lots(code="002281")), 1)

    def test_allocation_failure_rolls_back_trade_and_ticket(self):
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-04",
            "code": "002475",
            "name": "立讯精密",
            "action_type": "sell",
            "status": "executable",
        })
        db._exec_write("""INSERT INTO position_lots
            (lot_id, code, name, buy_date, original_qty, open_qty, cost_price,
             locked_until, lot_source, migration_source, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("old-002475", "002475", "立讯精密", "2026-06-03", 100, 100, 75,
             "2026-06-04", "test", "test", "open"))
        db._exec_write("""
            CREATE TRIGGER fail_alloc BEFORE INSERT ON trade_lot_allocations
            BEGIN
                SELECT RAISE(FAIL, 'forced allocation failure');
            END;
        """)

        status, body = _post({"entry": {
            "时间": "10:14", "动作": "卖出", "标的": "立讯精密", "代码": "002475",
            "价格": 76, "数量": 100, "event_id": "rollback-001",
            "ticket_id": ticket_id, "input_source": "spoken_confirmed",
            "confirmed_by": "yimu", "audit_note": "rollback test",
        }})

        self.assertEqual(status, 500, body)
        self.assertEqual(len(db._exec("SELECT * FROM trade_records")), 0)
        self.assertEqual(db.query_position_lots(code="002475")[0]["open_qty"], 100)
        self.assertEqual(db.query_trade_ticket(ticket_id)["status"], "executable")


if __name__ == "__main__":
    unittest.main()
