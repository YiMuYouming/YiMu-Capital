"""API tests for trade ticket preparation."""
import io
import hashlib
import json
import tempfile
import threading
import unittest
from datetime import datetime
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
    test.orig_load_state = bridge.load_current_account_state
    test.orig_rule_state = bridge._build_rule_state
    test.orig_rule_root = getattr(bridge, "AI_RULE_SYSTEM_ROOT", None)
    db.DB_PATH = Path(test.tmp.name) / "test.db"
    db._local = threading.local()
    bridge._db_inited = False
    bridge.CACHE.clear()
    db.init_db()
    bridge._build_trade_context = lambda: {
        "rule_state": {
            "version": "g1a-v1",
            "tradable": True,
            "blocks": [],
            "warnings": [],
            "windows": {"w1": {"blocks": []}, "w2": {"blocks": []}},
        },
        "market_snapshot": {"iwencai": {"情绪值": 65}},
        "account_snapshot": {"account_day_return_pct": 0.5},
        "context_captured_at": "2026-06-04T10:00:00",
        "context_status": "trusted",
        "context_unavailable_reason": None,
        "rule_pack_version": "test-pack",
        "rule_snapshot_hash": "hash-1",
        "today_execution_card_id": "EXEC-20260604",
    }
    bridge.load_current_account_state = lambda live_quotes: {
        "date": "2026-06-04",
        "pnl_pct": 0.5,
        "account_day_return_pct": 0.5,
        "positions": [{
            "代码": "002475",
            "标的": "立讯精密",
            "数量": 2000,
            "sellable_qty": 0,
            "locked_qty": 2000,
            "lot_reconciliation_ok": True,
        }],
        "lot_reconciliation_ok": True,
    }


def _teardown(test):
    db.close_conn()
    db.DB_PATH = test.orig_path
    db._local = test.orig_local
    bridge._db_inited = test.orig_inited
    bridge.CACHE.clear()
    bridge.CACHE.update(test.orig_cache)
    bridge._build_trade_context = test.orig_ctx
    bridge.load_current_account_state = test.orig_load_state
    bridge._build_rule_state = test.orig_rule_state
    if test.orig_rule_root is None and hasattr(bridge, "AI_RULE_SYSTEM_ROOT"):
        delattr(bridge, "AI_RULE_SYSTEM_ROOT")
    elif test.orig_rule_root is not None:
        bridge.AI_RULE_SYSTEM_ROOT = test.orig_rule_root
    test.tmp.cleanup()


def _handler(method, path, payload=None, headers_extra=None):
    h = object.__new__(bridge.BridgeHandler)
    h.command = method
    h.path = path
    h.requestline = f"{method} {path} HTTP/1.1"
    h.request_version = "HTTP/1.1"
    h.request = mock.MagicMock()
    h.request.version = "HTTP/1.1"
    h.client_address = ("127.0.0.1", 12345)
    h.server = mock.MagicMock()
    body = json.dumps(payload or {}).encode()
    h.rfile = io.BytesIO(body)
    h.headers = mock.MagicMock()
    headers_extra = headers_extra or {}
    h.headers.get = lambda k, d=None: (
        headers_extra[k] if k in headers_extra else
        (str(len(body)) if k == "Content-Length" else d)
    )
    h.log_message = mock.MagicMock()
    h._resp_status = None
    h._resp_body = b""
    h._resp_headers = []
    h.send_response = lambda code, phrase=None: setattr(h, "_resp_status", code)
    h.send_header = lambda key, value: h._resp_headers.append((key, value))
    h.end_headers = lambda: None

    def _write(_self, data):
        h._resp_body += data
    h.wfile = type("WFile", (), {"write": _write})()
    return h


def _call(method, path, payload=None, headers_extra=None):
    h = _handler(method, path, payload, headers_extra=headers_extra)
    getattr(h, f"do_{method}")()
    body = json.loads(h._resp_body.decode()) if h._resp_body else {}
    return h._resp_status, body


class TicketApiTest(unittest.TestCase):
    def setUp(self):
        _setup(self)

    def tearDown(self):
        _teardown(self)

    def test_prepare_buy_ticket(self):
        status, body = _call("POST", "/api/trade/tickets/prepare", {
            "intent_text": "准备买 光迅科技",
            "action_type": "buy",
            "code": "002281",
            "name": "光迅科技",
            "window": "W2",
        })

        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"])
        self.assertTrue(body["ticket"]["ticket_id"].startswith("TICKET-"))
        self.assertEqual(body["ticket"]["code"], "002281")
        self.assertEqual(body["ticket"]["action_type"], "buy")
        self.assertIn(body["ticket"]["status"], ("executable", "blocked"))

    def test_prepare_posthoc_trade_with_late_snapshot_is_audit_degraded(self):
        bridge._build_trade_context = lambda: {
            "rule_state": {
                "version": "g1a-v1",
                "tradable": True,
                "blocks": [],
                "warnings": [],
                "windows": {"w1": {"blocks": []}, "w2": {"blocks": []}},
            },
            "market_snapshot": {"iwencai": {"情绪值": 65}},
            "account_snapshot": {"account_day_return_pct": 0.5},
            "context_captured_at": "2026-06-04T15:11:29",
            "context_status": "trusted",
            "rule_pack_version": "test-pack",
            "rule_snapshot_hash": "hash-1",
            "today_execution_card_id": "EXEC-20260604",
        }

        status, body = _call("POST", "/api/trade/tickets/prepare", {
            "intent_text": "盘后补票据 光迅科技 14:10 已买",
            "action_type": "buy",
            "code": "002281",
            "name": "光迅科技",
            "window": "W2",
            "trade_time": "14:10",
        })

        self.assertEqual(status, 200, body)
        self.assertEqual(body["ticket"]["status"], "audit_degraded")
        self.assertIn("snapshot_captured_after_trade", body["ticket"]["blocking_rule_ids"])

    def test_w1_emotion_block_does_not_block_w2_ticket(self):
        bridge._build_trade_context = lambda: {
            "rule_state": {
                "version": "g1a-v1",
                "tradable": True,
                "blocks": [{"code": "WIN-ICE-W1-001", "scope": "w1"}],
                "warnings": [],
                "windows": {"w1": {"blocks": ["WIN-ICE-W1-001"]}, "w2": {"blocks": []}},
            },
            "market_snapshot": {"iwencai": {"情绪值": 24.1}},
            "account_snapshot": {"account_day_return_pct": 0.5},
            "context_captured_at": "2026-06-04T10:00:00",
            "context_status": "trusted",
            "rule_pack_version": "test-pack",
            "rule_snapshot_hash": "hash-1",
            "today_execution_card_id": "EXEC-20260604",
        }

        status, body = _call("POST", "/api/trade/tickets/prepare", {
            "intent_text": "准备 W2 买 光迅科技",
            "action_type": "buy",
            "code": "002281",
            "name": "光迅科技",
            "window": "W2",
        })

        self.assertEqual(status, 200, body)
        self.assertEqual(body["ticket"]["status"], "executable")
        self.assertNotIn("WIN-ICE-W1-001", body["ticket"]["blocking_rule_ids"])

    def test_reduce_ticket_is_not_blocked_by_lot_reconciliation_or_missing_rule_snapshot(self):
        bridge._build_trade_context = lambda: {
            "rule_state": {
                "version": "g1a-v1",
                "tradable": True,
                "blocks": [],
                "warnings": [],
                "windows": {"w1": {"blocks": []}, "w2": {"blocks": []}},
            },
            "market_snapshot": {"iwencai": {"情绪值": 65}},
            "account_snapshot": {"account_day_return_pct": 0.9, "lot_reconciliation_ok": False},
            "context_captured_at": "2026-06-05T10:46:00",
            "context_status": "trusted",
            "rule_pack_version": "test-pack",
            "rule_snapshot_hash": None,
            "today_execution_card_id": None,
        }
        bridge.load_current_account_state = lambda live_quotes: {
            "date": "2026-06-05",
            "pnl_pct": 0.9,
            "account_day_return_pct": 0.9,
            "positions": [{
                "代码": "002281",
                "标的": "光迅科技",
                "数量": 900,
                "sellable_qty": 1100,
                "locked_qty": 0,
                "lot_reconciliation_ok": False,
            }],
            "lot_reconciliation_ok": False,
        }

        status, body = _call("POST", "/api/trade/tickets/prepare", {
            "intent_text": "卖出200股锁利",
            "action_type": "reduce",
            "code": "002281",
            "name": "光迅科技",
            "qty": 200,
        })

        self.assertEqual(status, 200, body)
        self.assertEqual(body["ticket"]["status"], "executable")
        self.assertNotIn("lot_reconciliation", body["ticket"]["blocking_rule_ids"])
        self.assertNotIn("rule_snapshot_hash", body["ticket"]["blocking_rule_ids"])
        self.assertEqual(body["ticket"]["sellable_quantity"], 1100)

    def test_prepare_reduce_ticket_records_target_lot_and_realized_pnl_only_effect(self):
        bridge._build_trade_context = lambda: {
            "rule_state": {
                "version": "g1a-v1",
                "tradable": True,
                "blocks": [],
                "warnings": [],
                "windows": {"w1": {"blocks": []}, "w2": {"blocks": []}},
            },
            "market_snapshot": {"iwencai": {"情绪值": 65}},
            "account_snapshot": {"account_day_return_pct": 0.9, "lot_reconciliation_ok": False},
            "context_captured_at": "2026-06-05T14:45:00",
            "context_status": "trusted",
            "rule_pack_version": "test-pack",
            "rule_snapshot_hash": None,
            "today_execution_card_id": None,
        }
        bridge.load_current_account_state = lambda live_quotes: {
            "date": "2026-06-05",
            "pnl_pct": 0.9,
            "account_day_return_pct": 0.9,
            "positions": [{
                "代码": "002281",
                "标的": "光迅科技",
                "数量": 900,
                "sellable_qty": 1100,
                "locked_qty": 0,
                "lot_reconciliation_ok": False,
            }],
            "lot_reconciliation_ok": False,
        }
        db._exec_write("""INSERT INTO position_lots
            (lot_id, code, name, buy_date, original_qty, open_qty, cost_price,
             locked_until, lot_source, migration_source, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("trade:49", "002281", "光迅科技", "2026-06-04", 200, 200, 222.38,
             "2026-06-05", "trade_record", "test", "open"))

        status, body = _call("POST", "/api/trade/tickets/prepare", {
            "intent_text": "卖掉昨天W2加仓200股，底仓900不动",
            "action_type": "reduce",
            "code": "002281",
            "name": "光迅科技",
            "qty": 200,
            "target_lot_id": "trade:49",
        })

        self.assertEqual(status, 200, body)
        self.assertEqual(body["ticket"]["status"], "executable")
        self.assertEqual(body["ticket"]["t1_risk"]["target_lot_id"], "trade:49")
        self.assertEqual(body["ticket"]["t1_risk"]["target_lot_mode"], "explicit")
        self.assertEqual(body["ticket"]["t1_risk"]["account_effect"], "realized_pnl_only")

    def test_fill_preview_inherits_target_lot_from_ticket(self):
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-05",
            "code": "002281",
            "name": "光迅科技",
            "action_type": "reduce",
            "status": "executable",
            "t1_risk_json": {
                "target_lot_id": "trade:49",
                "account_effect": "realized_pnl_only",
            },
        })

        status, body = _call("POST", "/api/trade/fills/preview", {
            "input_text": "已卖 光迅科技 200股 232.30",
            "ticket_id": ticket_id,
        })

        self.assertEqual(status, 200, body)
        self.assertEqual(body["parsed"]["target_lot_id"], "trade:49")
        self.assertEqual(body["parsed"]["leg_type"], "sell_target_lot_realized_pnl_only")

    def test_posthoc_human_override_preserves_hard_blocks_as_audit_degraded(self):
        bridge._build_trade_context = lambda: {
            "rule_state": {
                "version": "g1a-v1",
                "tradable": False,
                "blocks": [{"code": "LOSS_STREAK", "scope": "all"}],
                "warnings": [],
                "windows": {"w1": {"blocks": []}, "w2": {"blocks": []}},
            },
            "market_snapshot": {"iwencai": {"情绪值": 24.1}},
            "account_snapshot": {"account_day_return_pct": 0.5},
            "context_captured_at": "2026-06-04T15:11:29",
            "context_status": "trusted",
            "rule_pack_version": "test-pack",
            "rule_snapshot_hash": "hash-1",
            "today_execution_card_id": "EXEC-20260604",
        }

        status, body = _call("POST", "/api/trade/tickets/prepare", {
            "intent_text": "盘后补票据 光迅科技 14:10 已买",
            "action_type": "buy",
            "code": "002281",
            "name": "光迅科技",
            "window": "W2",
            "trade_time": "14:10",
            "human_override_reason": "实盘已成交，盘后按执行卡补票据",
        })

        self.assertEqual(status, 200, body)
        self.assertEqual(body["ticket"]["status"], "audit_degraded")
        self.assertIn("LOSS_STREAK", body["ticket"]["blocking_rule_ids"])
        self.assertIn("snapshot_captured_after_trade", body["ticket"]["blocking_rule_ids"])
        self.assertEqual(body["ticket"]["human_override_reason"], "实盘已成交，盘后按执行卡补票据")

    def test_build_trade_context_hashes_today_execution_card_rule_snapshot(self):
        rule_root = Path(self.tmp.name) / "ai-rule-system"
        runtime = rule_root / "daily-runtime"
        runtime.mkdir(parents=True)
        rule_snapshot = {"rules": [{"id": "ACCT-RISK-002", "requires_data": ["account_day_return_pct"]}]}
        card = {
            "schema_version": "1.0",
            "generated_at": "2026-06-04T09:00:00+08:00",
            "next_trade_date": "2026-06-04",
            "rule_snapshot": rule_snapshot,
        }
        (runtime / "today_execution_card.json").write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
        expected_hash = "sha256:" + hashlib.sha256(
            json.dumps(rule_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        bridge._build_trade_context = self.orig_ctx
        bridge.AI_RULE_SYSTEM_ROOT = rule_root
        bridge.CACHE["live_quotes"] = {"_updated": datetime.now().astimezone().isoformat()}
        bridge.CACHE["iwencai"] = {"情绪值": 65}
        bridge.CACHE["live_index"] = {"上证指数涨幅": "+0.1%", "深证指数涨幅": "+0.2%"}
        bridge._build_rule_state = lambda: {"version": "g1a-v1", "tradable": True, "blocks": []}

        ctx = bridge._build_trade_context()

        self.assertEqual(ctx["context_status"], "trusted")
        self.assertEqual(ctx["rule_snapshot_hash"], expected_hash)
        self.assertEqual(ctx["rule_pack_version"], "g1a-v1")
        self.assertEqual(ctx["today_execution_card_id"], "EXEC-20260604-20260604T090000+0800")

    def test_rule_inputs_reset_legacy_loss_streak_when_account_day_is_profitable(self):
        with mock.patch.object(bridge, "_load_dashboard_data", return_value={
            "risk": {"连亏天数": 2},
            "style": {"总分": 80, "连板占比": 0, "趋势占比": 100},
            "sentiment": {
                "情绪值": 65,
                "昨日涨停收益": 3.0,
                "连板风险值": 0.2,
            },
            "market": {"炸板率": 20},
        }):
            inputs = bridge._build_rule_inputs(
                datetime(2026, 6, 4, 9, 40),
                account_state={
                    "pnl_pct": 1.12,
                    "account_day_return_pct": 1.12,
                    "valuation_complete": True,
                    "mv": 100000,
                },
            )

        self.assertEqual(inputs["risk"]["losing_account_days"], 0)
        self.assertNotIn("loss_streak", inputs["risk"])

    def test_reduce_is_sell_alias_and_uses_sellable_gate(self):
        status, body = _call("POST", "/api/trade/tickets/prepare", {
            "intent_text": "准备减仓 立讯精密 500股",
            "action_type": "reduce",
            "code": "002475",
            "name": "立讯精密",
            "qty": 500,
        })

        self.assertEqual(status, 200, body)
        self.assertEqual(body["ticket"]["status"], "blocked")
        self.assertEqual(body["ticket"]["leg_type"], "sell_reduce")
        self.assertIn("sellable_qty", body["ticket"]["blocking_rule_ids"])

    def test_prepare_sell_ticket_checks_sellable_quantity(self):
        status, body = _call("POST", "/api/trade/tickets/prepare", {
            "intent_text": "准备卖 立讯精密 2000股",
            "action_type": "sell",
            "code": "002475",
            "name": "立讯精密",
            "qty": 2000,
        })

        self.assertEqual(status, 200, body)
        self.assertEqual(body["ticket"]["status"], "blocked")
        self.assertIn("sellable_qty", body["ticket"]["blocking_rule_ids"])

    def test_get_trade_tickets(self):
        db.create_trade_ticket({
            "trade_date": "2026-06-04",
            "code": "002281",
            "name": "光迅科技",
            "action_type": "buy",
            "status": "executable",
        })

        status, body = _call("GET", "/api/trade/tickets?date=2026-06-04&code=002281&status=executable")

        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["tickets"]), 1)

    def test_fill_preview_persists_pending_without_writing_facts(self):
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-04", "code": "002281", "name": "光迅科技",
            "action_type": "buy", "status": "executable",
        })

        status, body = _call("POST", "/api/trade/fills/preview", {
            "input_text": "已买 光迅科技 100股 225.78",
            "ticket_id": ticket_id,
        })

        self.assertEqual(status, 200, body)
        self.assertTrue(body["requires_confirmation"])
        self.assertTrue(body["confirmation_id"].startswith("CONFIRM-"))
        self.assertTrue(body["preview_hash"].startswith("sha256:"))
        self.assertEqual(body["parsed"]["qty"], 100)
        self.assertEqual(len(db._exec("SELECT * FROM pending_fill_confirmations")), 1)
        self.assertEqual(len(db._exec("SELECT * FROM trade_records")), 0)

    def test_blocked_ticket_cannot_create_fill_preview(self):
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-04", "code": "002281", "name": "光迅科技",
            "action_type": "buy", "status": "blocked",
            "blocking_rule_ids_json": ["context_status"],
        })

        status, body = _call("POST", "/api/trade/fills/preview", {
            "input_text": "已买 光迅科技 100股 225.78",
            "ticket_id": ticket_id,
        })

        self.assertEqual(status, 400, body)
        self.assertIn("cannot accept fills", body["error"])
        self.assertEqual(len(db._exec("SELECT * FROM pending_fill_confirmations")), 0)
        self.assertEqual(len(db._exec("SELECT * FROM trade_records")), 0)

    def test_fill_confirm_writes_trade_once(self):
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-04", "code": "002281", "name": "光迅科技",
            "action_type": "buy", "status": "executable",
        })
        preview = _call("POST", "/api/trade/fills/preview", {
            "input_text": "已买 光迅科技 100股 225.78",
            "ticket_id": ticket_id,
        })[1]

        status, body = _call("POST", "/api/trade/fills/confirm", {
            "confirmation_id": preview["confirmation_id"],
            "preview_token": preview["preview_token"],
            "preview_hash": preview["preview_hash"],
            "confirmed_by": "yimu",
        })
        replay_status, replay_body = _call("POST", "/api/trade/fills/confirm", {
            "confirmation_id": preview["confirmation_id"],
            "preview_token": preview["preview_token"],
            "preview_hash": preview["preview_hash"],
            "confirmed_by": "yimu",
        })

        self.assertEqual(status, 200, body)
        self.assertEqual(replay_status, 409, replay_body)
        self.assertEqual(len(db._exec("SELECT * FROM trade_records")), 1)
        self.assertEqual(len(db.query_position_lots(code="002281")), 1)

    def test_fill_confirm_closes_target_lot_instead_of_fifo(self):
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-05",
            "code": "002281",
            "name": "光迅科技",
            "action_type": "reduce",
            "status": "executable",
            "t1_risk_json": {
                "target_lot_id": "trade:49",
                "account_effect": "realized_pnl_only",
            },
        })
        for lot_id, qty, cost in [("overnight", 900, 219.49), ("trade:49", 200, 222.38)]:
            db._exec_write("""INSERT INTO position_lots
                (lot_id, code, name, buy_date, original_qty, open_qty, cost_price,
                 locked_until, lot_source, migration_source, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (lot_id, "002281", "光迅科技", "2026-06-04", qty, qty, cost,
                 "2026-06-05", "test", "test", "open"))
        preview = _call("POST", "/api/trade/fills/preview", {
            "input_text": "已卖 光迅科技 200股 232.30",
            "ticket_id": ticket_id,
        })[1]

        status, body = _call("POST", "/api/trade/fills/confirm", {
            "confirmation_id": preview["confirmation_id"],
            "preview_token": preview["preview_token"],
            "preview_hash": preview["preview_hash"],
            "confirmed_by": "yimu",
        })

        self.assertEqual(status, 200, body)
        lots = {lot["lot_id"]: lot for lot in db.query_position_lots(code="002281")}
        self.assertEqual(lots["overnight"]["open_qty"], 900)
        self.assertEqual(lots["trade:49"]["open_qty"], 0)
        trade = dict(db._exec("SELECT * FROM trade_records")[0])
        self.assertEqual(trade["leg_type"], "sell_target_lot_realized_pnl_only")
        self.assertAlmostEqual(trade["realized_pnl"], (232.30 - 222.38) * 200)
        self.assertEqual(db.query_trade_ticket(ticket_id)["status"], "filled")

    def test_ticket_blocked_after_preview_cannot_confirm_fill(self):
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-04", "code": "002281", "name": "光迅科技",
            "action_type": "buy", "status": "executable",
        })
        preview = _call("POST", "/api/trade/fills/preview", {
            "input_text": "已买 光迅科技 100股 225.78",
            "ticket_id": ticket_id,
        })[1]
        db.update_trade_ticket_status(ticket_id, "blocked")

        status, body = _call("POST", "/api/trade/fills/confirm", {
            "confirmation_id": preview["confirmation_id"],
            "preview_token": preview["preview_token"],
            "preview_hash": preview["preview_hash"],
            "confirmed_by": "yimu",
        })

        self.assertEqual(status, 409, body)
        self.assertIn("cannot accept fills", body["error"])
        self.assertEqual(len(db._exec("SELECT * FROM trade_records")), 0)

    def test_fill_confirm_rejects_bad_or_expired_confirmation(self):
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-04", "code": "002281", "name": "光迅科技",
            "action_type": "buy", "status": "executable",
        })
        preview = _call("POST", "/api/trade/fills/preview", {
            "input_text": "已买 光迅科技 100股 225.78",
            "ticket_id": ticket_id,
        })[1]

        bad_hash_status, _ = _call("POST", "/api/trade/fills/confirm", {
            "confirmation_id": preview["confirmation_id"],
            "preview_token": preview["preview_token"],
            "preview_hash": "sha256:bad",
            "confirmed_by": "yimu",
        })
        bad_actor_status, _ = _call("POST", "/api/trade/fills/confirm", {
            "confirmation_id": preview["confirmation_id"],
            "preview_token": preview["preview_token"],
            "preview_hash": preview["preview_hash"],
            "confirmed_by": "unknown",
        })
        db._exec_write(
            "UPDATE pending_fill_confirmations SET expires_at = '2000-01-01T00:00:00' WHERE confirmation_id = ?",
            (preview["confirmation_id"],),
        )
        expired_status, _ = _call("POST", "/api/trade/fills/confirm", {
            "confirmation_id": preview["confirmation_id"],
            "preview_token": preview["preview_token"],
            "preview_hash": preview["preview_hash"],
            "confirmed_by": "yimu",
        })

        self.assertEqual(bad_hash_status, 409)
        self.assertEqual(bad_actor_status, 403)
        self.assertEqual(expired_status, 409)
        self.assertEqual(len(db._exec("SELECT * FROM trade_records")), 0)

    def test_closed_ticket_cannot_be_confirmed(self):
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-04", "code": "002281", "name": "光迅科技",
            "action_type": "buy", "status": "executable",
        })
        preview = _call("POST", "/api/trade/fills/preview", {
            "input_text": "已买 光迅科技 100股 225.78",
            "ticket_id": ticket_id,
        })[1]
        db.update_trade_ticket_status(ticket_id, "closed")

        status, _ = _call("POST", "/api/trade/fills/confirm", {
            "confirmation_id": preview["confirmation_id"],
            "preview_token": preview["preview_token"],
            "preview_hash": preview["preview_hash"],
            "confirmed_by": "yimu",
        })

        self.assertEqual(status, 409)
        self.assertEqual(len(db._exec("SELECT * FROM trade_records")), 0)


if __name__ == "__main__":
    unittest.main()
