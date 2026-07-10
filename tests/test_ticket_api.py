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
    test.orig_ai_context = bridge._build_ai_context
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
    bridge._build_ai_context = lambda: {
        "schema_version": "ai_context.v1",
        "decision_gate": {
            "schema_version": "decision_gate.v1",
            "allowed": True,
            "reason": None,
            "source": "/api/ai/context",
        },
    }
    bridge.load_current_account_state = lambda live_quotes, **kwargs: {
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
    bridge._build_ai_context = test.orig_ai_context
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
        self.assertEqual(body["ticket"]["ticket_purpose"], "execution")

    def test_prepare_post_trade_reconciliation_never_returns_executable(self):
        bridge._build_ai_context = lambda: {
            "decision_gate": {
                "schema_version": "decision_gate.v1",
                "allowed": False,
                "reason": "SENTIMENT_STALE",
                "source": "/api/ai/context",
            }
        }

        status, body = _call("POST", "/api/trade/tickets/prepare", {
            "intent_text": "已买 瑞芯微 200股 220.58",
            "action_type": "buy",
            "code": "603893",
            "name": "瑞芯微",
            "window": "W2",
            "trade_time": "11:00",
            "ticket_purpose": "post_trade_reconciliation",
            "human_override_reason": "券商已成交，仅补录事实",
        })

        self.assertEqual(200, status, body)
        self.assertEqual("post_trade_reconciliation", body["ticket"]["ticket_purpose"])
        self.assertEqual("reconciliation_ready", body["ticket"]["status"])
        self.assertNotEqual("executable", body["ticket"]["status"])

    def test_legacy_posthoc_trade_without_reconciliation_purpose_is_blocked(self):
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
        self.assertEqual(body["ticket"]["status"], "blocked")
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

    def test_prepare_w1_ice_polarized_mainline_ticket_requires_manual_review(self):
        bridge._build_trade_context = lambda: {
            "rule_state": {
                "version": "g1a-v1",
                "tradable": True,
                "blocks": [
                    {"code": "WIN-ICE-W1-001", "scope": "w1"},
                    {"code": "W1_EMOTION", "scope": "w1"},
                ],
                "warnings": [{
                    "code": "WIN-ICE-POLAR-MAINLINE-001",
                    "scope": "w1",
                    "message": "冰点 W1 极化主线强回踩仅人工复核",
                }],
                "windows": {
                    "w1": {
                        "blocks": ["WIN-ICE-W1-001", "W1_EMOTION"],
                        "manual_review_allowed": True,
                        "manual_review_rules": ["WIN-ICE-POLAR-MAINLINE-001"],
                    },
                    "w2": {"blocks": []},
                },
            },
            "market_snapshot": {"iwencai": {"情绪值": 25.6}},
            "account_snapshot": {"account_day_return_pct": 1.0},
            "context_captured_at": "2026-06-04T09:58:00",
            "context_status": "trusted",
            "rule_pack_version": "test-pack",
            "rule_snapshot_hash": "hash-1",
            "today_execution_card_id": "EXEC-20260604",
        }

        status, body = _call("POST", "/api/trade/tickets/prepare", {
            "intent_text": "冰点极化主线回踩，准备人工复核海光信息",
            "action_type": "buy",
            "code": "688041",
            "name": "海光信息",
            "window": "W1",
        })

        self.assertEqual(status, 200, body)
        self.assertEqual(body["ticket"]["status"], "manual_review")
        self.assertIn("WIN-ICE-W1-001", body["ticket"]["blocking_rule_ids"])
        self.assertIn("W1_EMOTION", body["ticket"]["blocking_rule_ids"])

    def test_manual_review_ticket_is_valid_but_cannot_accept_fills(self):
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-04",
            "code": "688041",
            "name": "海光信息",
            "action_type": "buy",
            "status": "manual_review",
            "window": "W1",
        })

        with self.assertRaisesRegex(ValueError, "cannot accept fills"):
            db.record_confirmed_fill({
                "ticket_id": ticket_id,
                "action": "买入",
                "code": "688041",
                "name": "海光信息",
                "qty": 100,
                "price": 318.78,
                "trade_date": "2026-06-04",
            })

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
        bridge.load_current_account_state = lambda live_quotes, **kwargs: {
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

    def test_reduce_ticket_is_not_blocked_by_loss_streak_all_scope(self):
        bridge._build_trade_context = lambda: {
            "rule_state": {
                "version": "g1a-v1",
                "tradable": False,
                "blocks": [{"code": "LOSS_STREAK", "scope": "all"}],
                "warnings": [],
                "windows": {"w1": {"blocks": []}, "w2": {"blocks": []}},
            },
            "market_snapshot": {"iwencai": {"情绪值": 25}},
            "account_snapshot": {"account_day_return_pct": -1.2, "lot_reconciliation_ok": True},
            "context_captured_at": "2026-06-05T14:30:00",
            "context_status": "trusted",
            "rule_pack_version": "test-pack",
            "rule_snapshot_hash": "hash-1",
            "today_execution_card_id": "EXEC-20260605",
        }
        bridge.load_current_account_state = lambda live_quotes, **kwargs: {
            "date": "2026-06-05",
            "pnl_pct": -1.2,
            "account_day_return_pct": -1.2,
            "positions": [{
                "代码": "002281",
                "标的": "光迅科技",
                "数量": 900,
                "sellable_qty": 900,
                "locked_qty": 0,
                "lot_reconciliation_ok": True,
            }],
            "lot_reconciliation_ok": True,
        }

        status, body = _call("POST", "/api/trade/tickets/prepare", {
            "intent_text": "光迅跌破230主动风险线，减300股降仓位",
            "action_type": "reduce",
            "code": "002281",
            "name": "光迅科技",
            "qty": 300,
        })

        self.assertEqual(status, 200, body)
        self.assertEqual(body["ticket"]["status"], "executable")
        self.assertNotIn("LOSS_STREAK", body["ticket"]["blocking_rule_ids"])
        self.assertEqual(body["ticket"]["sellable_quantity"], 900)

    def test_clear_ticket_context_unavailable_is_audit_degraded_when_sellable(self):
        bridge._build_trade_context = lambda: {
            "rule_state": None,
            "market_snapshot": None,
            "account_snapshot": {"account_day_return_pct": 1.1, "lot_reconciliation_ok": True},
            "context_captured_at": None,
            "context_status": "unavailable",
            "context_unavailable_reason": "行情数据不可信 (SENTIMENT_STALE)",
            "rule_pack_version": None,
            "rule_snapshot_hash": None,
            "today_execution_card_id": None,
        }
        bridge.load_current_account_state = lambda live_quotes, **kwargs: {
            "date": "2026-06-09",
            "pnl_pct": 1.1,
            "account_day_return_pct": 1.1,
            "positions": [{
                "代码": "002281",
                "标的": "光迅科技",
                "数量": 200,
                "sellable_qty": 200,
                "locked_qty": 0,
                "lot_reconciliation_ok": True,
            }],
            "lot_reconciliation_ok": True,
        }

        status, body = _call("POST", "/api/trade/tickets/prepare", {
            "intent_text": "清仓 光迅科技 200股",
            "action_type": "clear",
            "code": "002281",
            "name": "光迅科技",
            "qty": 200,
        })

        self.assertEqual(status, 200, body)
        self.assertEqual(body["ticket"]["status"], "audit_degraded")
        self.assertIn("context_status", body["ticket"]["blocking_rule_ids"])
        self.assertEqual(body["ticket"]["sellable_quantity"], 200)

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
        bridge.load_current_account_state = lambda live_quotes, **kwargs: {
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

    def test_legacy_posthoc_human_override_cannot_impersonate_reconciliation(self):
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
        self.assertEqual(body["ticket"]["status"], "blocked")
        self.assertIn("LOSS_STREAK", body["ticket"]["blocking_rule_ids"])
        self.assertIn("snapshot_captured_after_trade", body["ticket"]["blocking_rule_ids"])
        self.assertEqual(body["ticket"]["human_override_reason"], "实盘已成交，盘后按执行卡补票据")

    def test_build_trade_context_hashes_today_execution_card_rule_snapshot(self):
        rule_root = Path(self.tmp.name) / "ai-rule-system"
        runtime = rule_root / "daily-runtime"
        runtime.mkdir(parents=True)
        rule_snapshot = {"rules": [{"id": "ACCT-RISK-002", "requires_data": ["account_day_return_pct"]}]}
        trade_date = datetime.now().strftime("%Y-%m-%d")
        card = {
            "schema_version": "1.0",
            "generated_at": f"{trade_date}T09:00:00+08:00",
            "next_trade_date": trade_date,
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
        self.assertEqual(ctx["today_execution_card_id"], f"EXEC-{trade_date.replace('-', '')}-{trade_date.replace('-', '')}T090000+0800")

    def test_execution_card_metadata_rejects_wrong_trade_date(self):
        rule_root = Path(self.tmp.name) / "ai-rule-system"
        runtime = rule_root / "daily-runtime"
        runtime.mkdir(parents=True)
        card = {
            "schema_version": "1.0",
            "generated_at": "2026-06-05T09:00:00+08:00",
            "next_trade_date": "2026-06-05",
            "rule_snapshot": {"rules": [{"id": "OLD"}]},
        }
        (runtime / "today_execution_card.json").write_text(json.dumps(card), encoding="utf-8")
        bridge.AI_RULE_SYSTEM_ROOT = rule_root

        meta = bridge._execution_card_metadata(trade_date="2026-06-24")

        self.assertTrue(meta["execution_card_stale"])
        self.assertIsNone(meta.get("rule_snapshot_hash"))
        self.assertIsNone(meta.get("today_execution_card_id"))

    def test_execution_card_metadata_prefers_explicit_hash_and_id(self):
        rule_root = Path(self.tmp.name) / "ai-rule-system"
        runtime = rule_root / "daily-runtime"
        runtime.mkdir(parents=True)
        trade_date = datetime.now().strftime("%Y-%m-%d")
        card = {
            "schema_version": "1.0",
            "generated_at": f"{trade_date}T09:00:00+08:00",
            "next_trade_date": trade_date,
            "today_execution_card_id": "EXEC-CUSTOM",
            "rule_snapshot_hash": "sha256:custom",
            "rule_snapshot": {"rules": [{"id": "ACCT-RISK-002"}]},
        }
        (runtime / "today_execution_card.json").write_text(json.dumps(card), encoding="utf-8")
        bridge.AI_RULE_SYSTEM_ROOT = rule_root

        meta = bridge._execution_card_metadata(trade_date=trade_date)

        self.assertEqual(meta["rule_snapshot_hash"], "sha256:custom")
        self.assertEqual(meta["today_execution_card_id"], "EXEC-CUSTOM")

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

    def test_rule_inputs_use_closed_daily_summary_for_premarket_loss_streak(self):
        db.insert_daily_summary({
            "date": "2026-06-05",
            "nav": 0.9949,
            "pnl_pct": -0.51,
        })
        db.insert_daily_summary({
            "date": "2026-06-08",
            "nav": 0.9814,
            "pnl_pct": -1.36,
        })
        db.insert_daily_summary({
            "date": "2026-06-09",
            "nav": 0.9868,
            "pnl_pct": 0.55,
        })
        with mock.patch.object(bridge, "_load_dashboard_data", return_value={
            "risk": {"连亏天数": 2},
            "style": {"总分": 80, "连板占比": 0, "趋势占比": 100},
            "sentiment": {},
            "market": {},
        }):
            inputs = bridge._build_rule_inputs(
                datetime(2026, 6, 10, 9, 10),
                account_state={
                    "pnl_pct": 0.0,
                    "account_day_return_pct": 0.0,
                    "valuation_complete": True,
                    "mv": 100000,
                },
            )

        self.assertEqual(inputs["risk"]["losing_account_days"], 0)

    def test_full_snapshot_uses_rule_loss_streak_not_stale_baseline(self):
        db.insert_daily_summary({
            "date": "2026-06-08",
            "nav": 0.9814,
            "pnl_pct": -1.36,
        })
        db.insert_daily_summary({
            "date": "2026-06-09",
            "nav": 0.9868,
            "pnl_pct": 0.55,
        })
        dashboard = {
            "risk": {"连亏天数": 2, "周累计回撤": 0, "月累计回撤": 0},
            "style": {"总分": 80, "连板占比": 0, "趋势占比": 100},
            "sentiment": {},
            "market": {},
            "lianban_pool": [],
            "trend_pool": [],
            "sectors": [],
        }
        with mock.patch.object(bridge, "_load_dashboard_data", return_value=dashboard):
            with mock.patch.object(bridge, "_current_pnl_summary", return_value={
                "pnl_pct": 0.0,
                "account_day_return_pct": 0.0,
                "valuation_complete": True,
                "total_asset": 100000,
                "mv": 0,
                "positions": [],
            }):
                snapshot = bridge._build_full_snapshot()

        self.assertEqual(snapshot["风控"]["连亏天数"], 0)

    def test_baseline_payload_overlays_stale_loss_streak_from_rule_inputs(self):
        stale_dashboard = {
            "meta": {"date": "2026-06-09", "updated": "2026-06-10T09:17:01+08:00"},
            "risk": {"连亏天数": 2, "周累计回撤": 0, "月累计回撤": 0},
            "style": {},
            "sentiment": {},
            "market": {},
        }
        with mock.patch.object(bridge, "_load_dashboard_data", return_value=stale_dashboard):
            with mock.patch.object(bridge, "_build_rule_inputs", return_value={
                "risk": {
                    "losing_account_days": 1,
                    "weekly_drawdown_pct": 0,
                    "monthly_drawdown_pct": 0,
                }
            }):
                payload = bridge._baseline_payload(now=datetime(2026, 6, 11, 9, 0))

        self.assertEqual(payload["risk"]["连亏天数"], 1)
        self.assertEqual(payload["risk"]["_legacy_连亏天数"], 2)
        self.assertEqual(payload["risk"]["_source"], "rule_inputs_live_overlay")
        self.assertTrue(payload["meta"]["_baseline_stale"])
        self.assertEqual(payload["meta"]["_served_date"], "2026-06-11")

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
        self.assertEqual(body["data_date"], "2026-06-04")
        self.assertEqual(body["date_source"], "query_param")
        self.assertEqual(len(body["tickets"]), 1)

    def test_get_trade_tickets_without_date_defaults_to_today_only(self):
        today = datetime.now().strftime("%Y-%m-%d")
        db.create_trade_ticket({
            "trade_date": today,
            "code": "002281",
            "name": "光迅科技",
            "action_type": "buy",
            "status": "executable",
        })
        db.create_trade_ticket({
            "trade_date": "2026-06-04",
            "code": "600030",
            "name": "中信证券",
            "action_type": "sell",
            "status": "filled",
        })

        status, body = _call("GET", "/api/trade/tickets")

        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"])
        self.assertEqual(body["data_date"], today)
        self.assertEqual(body["date_source"], "default_today")
        self.assertEqual([ticket["trade_date"] for ticket in body["tickets"]], [today])

    def test_close_trade_ticket_marks_closed_with_audit_reason(self):
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-04",
            "code": "002281",
            "name": "光迅科技",
            "action_type": "buy",
            "status": "executable",
        })

        status, body = _call("POST", f"/api/trade/tickets/{ticket_id}/close", {
            "status": "closed",
            "close_reason": "方向误判废票，未使用",
            "review_note": "人工关闭测试",
        })

        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"])
        self.assertEqual(body["ticket"]["status"], "closed")
        self.assertEqual(body["ticket"]["close_reason"], "方向误判废票，未使用")
        self.assertEqual(body["ticket"]["review_note"], "人工关闭测试")
        self.assertEqual(db.query_trade_ticket(ticket_id)["status"], "closed")

    def test_close_trade_ticket_requires_reason_and_rejects_non_terminal_status(self):
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-04",
            "code": "002281",
            "name": "光迅科技",
            "action_type": "buy",
            "status": "executable",
        })

        missing_reason_status, missing_reason_body = _call("POST", f"/api/trade/tickets/{ticket_id}/close", {
            "status": "closed",
        })
        bad_status, bad_body = _call("POST", f"/api/trade/tickets/{ticket_id}/close", {
            "status": "executable",
            "close_reason": "bad",
        })

        self.assertEqual(missing_reason_status, 400)
        self.assertIn("close_reason required", missing_reason_body["error"])
        self.assertEqual(bad_status, 400)
        self.assertIn("invalid close status", bad_body["error"])
        self.assertEqual(db.query_trade_ticket(ticket_id)["status"], "executable")

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

    def test_fill_preview_can_use_ticket_qty_and_live_quote_without_spoken_input(self):
        bridge.CACHE["live_quotes"] = {
            "002281": {"最新价": 232.30},
            "_updated": datetime.now().astimezone().isoformat(),
        }
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-04",
            "code": "002281",
            "name": "光迅科技",
            "action_type": "buy",
            "status": "executable",
            "max_qty": 200,
        })

        status, body = _call("POST", "/api/trade/fills/preview", {
            "ticket_id": ticket_id,
        })

        self.assertEqual(status, 200, body)
        self.assertTrue(body["requires_confirmation"])
        self.assertEqual(body["parsed"]["qty"], 200)
        self.assertEqual(body["parsed"]["price"], 232.30)
        self.assertIn("auto_from_ticket", body["parsed"]["input_source"])
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

    def test_execution_buy_preview_rechecks_decision_gate(self):
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-04", "code": "002281", "name": "光迅科技",
            "action_type": "buy", "status": "executable", "ticket_purpose": "execution",
        })
        bridge._build_ai_context = lambda: {
            "decision_gate": {
                "schema_version": "decision_gate.v1",
                "allowed": False,
                "reason": "SENTIMENT_STALE",
                "source": "/api/ai/context",
            }
        }

        status, body = _call("POST", "/api/trade/fills/preview", {
            "input_text": "已买 光迅科技 100股 225.78",
            "ticket_id": ticket_id,
        })

        self.assertEqual(400, status, body)
        self.assertIn("decision gate blocked", body["error"])
        self.assertEqual(0, len(db._exec("SELECT * FROM pending_fill_confirmations")))

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

    def test_execution_buy_confirm_rechecks_decision_gate(self):
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-04", "code": "002281", "name": "光迅科技",
            "action_type": "buy", "status": "executable", "ticket_purpose": "execution",
        })
        preview = _call("POST", "/api/trade/fills/preview", {
            "input_text": "已买 光迅科技 100股 225.78",
            "ticket_id": ticket_id,
        })[1]
        bridge._build_ai_context = lambda: {
            "decision_gate": {
                "schema_version": "decision_gate.v1",
                "allowed": False,
                "reason": "SENTIMENT_STALE",
                "source": "/api/ai/context",
            }
        }

        status, body = _call("POST", "/api/trade/fills/confirm", {
            "confirmation_id": preview["confirmation_id"],
            "preview_token": preview["preview_token"],
            "preview_hash": preview["preview_hash"],
            "confirmed_by": "yimu",
        })

        self.assertEqual(409, status, body)
        self.assertIn("decision gate blocked", body["error"])
        self.assertEqual(0, len(db._exec("SELECT * FROM trade_records")))

    def test_reconciliation_fill_can_record_user_confirmed_broker_fact_when_gate_closed(self):
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-04", "code": "002281", "name": "光迅科技",
            "action_type": "buy", "status": "reconciliation_ready",
            "ticket_purpose": "post_trade_reconciliation",
        })
        bridge._build_ai_context = lambda: {
            "decision_gate": {
                "schema_version": "decision_gate.v1",
                "allowed": False,
                "reason": "SENTIMENT_STALE",
                "source": "/api/ai/context",
            }
        }
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

        self.assertEqual(200, status, body)
        self.assertEqual(1, len(db._exec("SELECT * FROM trade_records")))
        trade = dict(db._exec("SELECT * FROM trade_records")[0])
        self.assertEqual("post_trade_reconciliation", trade["input_source"])

    def test_reconciliation_fill_rejects_agent_confirmation(self):
        ticket_id = db.create_trade_ticket({
            "trade_date": "2026-06-04", "code": "002281", "name": "光迅科技",
            "action_type": "buy", "status": "reconciliation_ready",
            "ticket_purpose": "post_trade_reconciliation",
        })
        preview = _call("POST", "/api/trade/fills/preview", {
            "input_text": "已买 光迅科技 100股 225.78",
            "ticket_id": ticket_id,
        })[1]

        status, body = _call(
            "POST",
            "/api/trade/fills/confirm",
            {
                "confirmation_id": preview["confirmation_id"],
                "preview_token": preview["preview_token"],
                "preview_hash": preview["preview_hash"],
                "confirmed_by": "agent:oumi",
            },
            headers_extra={"X-YM-Confirm-Actor": "agent:oumi"},
        )

        self.assertEqual(403, status, body)
        self.assertIn("requires confirmed_by=yimu", body["error"])
        self.assertEqual(0, len(db._exec("SELECT * FROM trade_records")))

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
