import hashlib
import json
import os
import sqlite3
import unittest
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import scripts.bridge as bridge
import scripts.db as db
from scripts.collectors import quotes

try:
    from scripts.account_ssot import ensure_today_anchor, load_current_account_state, reduce_account_state, backfill_day_start_price
except ImportError:
    ensure_today_anchor = None
    load_current_account_state = None
    reduce_account_state = None
    backfill_day_start_price = None


class AccountBaselinePositionCorrectionTests(unittest.TestCase):
    def test_late_buy_rebuilds_position_cash_and_day_start_asset(self):
        import scripts.account_ssot as account_ssot_module

        build_correction = getattr(
            account_ssot_module,
            "build_account_baseline_position_correction",
            None,
        )
        self.assertIsNotNone(build_correction)

        anchor = {
            "date": "2026-07-10",
            "effective_at": "2026-07-10T09:25:00",
            "cash": 430179.47,
            "day_start_asset": 716389.47,
            "total_deposit": 711059.23,
            "source": "previous_close",
            "positions": [
                {"标的": "徐工机械", "代码": "000425", "数量": 5000,
                 "成本": 9.07, "现价": 8.35, "状态": "持有"},
            ],
            "_meta": {"day_start_prices": {"000425": 8.35}},
        }
        late_trade = {
            "id": 127,
            "trade_date": "2026-07-08",
            "action": "买入",
            "code": "000425",
            "name": "徐工机械",
            "price": 8.51,
            "qty": 5000,
            "fee": 0,
        }
        open_lots = [
            {"open_qty": 5000, "cost_price": 9.07},
            {"open_qty": 5000, "cost_price": 8.51},
        ]

        result = build_correction(
            anchor=anchor,
            late_trade=late_trade,
            open_lots=open_lots,
            expected_actual_qty=10000,
            source="yimu_broker_confirmation",
            reason="15:06 late backfill missed 15:05 closing anchor",
            now="2026-07-10T10:45:00",
        )

        self.assertEqual(result["action"], "would_write")
        corrected = result["corrected_anchor"]
        self.assertEqual(corrected["source"], "manual_correction")
        self.assertEqual(corrected["cash"], 387629.47)
        self.assertEqual(corrected["day_start_asset"], 715589.47)
        position = corrected["positions"][0]
        self.assertEqual(position["数量"], 10000)
        self.assertEqual(position["成本"], 8.79)
        repair = corrected["_meta"]["account_position_repairs"][-1]
        self.assertEqual(repair["late_trade_id"], 127)
        self.assertEqual(repair["before_qty"], 5000)
        self.assertEqual(repair["after_qty"], 10000)


class AccountReducerTests(unittest.TestCase):
    def setUp(self):
        self.anchor = {
            "date": "2026-05-26",
            "effective_at": "2026-05-26T09:30:00",
            "cash": 125000,
            "day_start_asset": 210477,
            "total_deposit": 200000,
            "positions": [
                {"标的": "中芯国际", "代码": "688981", "数量": 500, "成本": 135, "现价": 150},
            ],
        }

    def test_trade_replay_derives_cash_positions_and_asset(self):
        self.assertIsNotNone(reduce_account_state)
        state = reduce_account_state(
            self.anchor,
            [
                {"trade_date": "2026-05-26", "trade_time": "09:32", "action": "W1追涨", "code": "002463", "name": "沪电股份", "price": 122.5, "qty": 300},
                {"trade_date": "2026-05-26", "trade_time": "10:59", "action": "卖出", "code": "688981", "name": "中芯国际", "price": 147.77, "qty": 200},
            ],
            {"688981": {"最新价": 146.01}, "002463": {"最新价": 131.6}, "_updated": "2026-05-26T11:00:00"},
            now="2026-05-26T11:00:01",
        )

        self.assertEqual(state["cash"], 117804)
        self.assertEqual({p["代码"]: p["数量"] for p in state["positions"]}, {"688981": 300, "002463": 300})
        self.assertEqual(state["mv"], 83283)
        self.assertEqual(state["total_asset"], 201087)

    def test_recovery_anchor_does_not_replay_earlier_trades(self):
        anchor = dict(self.anchor, effective_at="2026-05-26T11:30:00", cash=125279)
        state = reduce_account_state(
            anchor,
            [{"trade_date": "2026-05-26", "trade_time": "10:59", "action": "卖出", "code": "688981", "name": "中芯国际", "price": 147.77, "qty": 200}],
            {"688981": {"最新价": 146.01}, "_updated": "2026-05-26T11:30:01"},
            now="2026-05-26T11:30:01",
        )
        self.assertEqual(state["cash"], 125279)
        self.assertEqual(state["positions"][0]["数量"], 500)

    def test_quote_tick_changes_valuation_but_not_cash_or_quantity(self):
        first = reduce_account_state(self.anchor, [], {"688981": {"最新价": 146}, "_updated": "2026-05-26T10:00:00"}, now="2026-05-26T10:00:01")
        second = reduce_account_state(self.anchor, [], {"688981": {"最新价": 147}, "_updated": "2026-05-26T10:00:05"}, now="2026-05-26T10:00:06")
        self.assertEqual(first["cash"], second["cash"])
        self.assertEqual(first["positions"][0]["数量"], second["positions"][0]["数量"])
        self.assertEqual(second["mv"] - first["mv"], 500)

    def test_missing_open_position_quote_degrades_snapshot_authority(self):
        state = reduce_account_state(self.anchor, [], {}, now="2026-05-26T10:00:00")
        self.assertFalse(state["valuation_complete"])

    def test_stale_quote_degrades_snapshot_authority(self):
        state = reduce_account_state(
            self.anchor,
            [],
            {"688981": {"最新价": 146}, "_updated": "2026-05-26T10:00:00"},
            now="2026-05-26T10:06:00",
        )
        self.assertFalse(state["valuation_complete"])

    # —— R1: 收盘后行情新鲜度 ——

    def test_post_close_quote_accepted_after_300s(self):
        """15:30 使用当天 15:05 quote → close_snapshot, valuation_complete=true"""
        state = reduce_account_state(
            self.anchor,
            [],
            {"688981": {"最新价": 146}, "_updated": "2026-05-26T15:05:00"},
            now="2026-05-26T15:30:00",
        )
        self.assertTrue(state["valuation_complete"])
        self.assertEqual(state.get("quote_status"), "close_snapshot")

    def test_intraday_stale_still_rejected(self):
        """盘中 10:30 使用 10:20 quote → stale, valuation_complete=false"""
        state = reduce_account_state(
            self.anchor,
            [],
            {"688981": {"最新价": 146}, "_updated": "2026-05-26T10:20:00"},
            now="2026-05-26T10:30:00",
        )
        self.assertFalse(state["valuation_complete"])
        self.assertEqual(state.get("quote_status"), "stale")

    def test_yesterday_quote_rejected_post_close(self):
        """今天用昨天 quote → stale, valuation_complete=false"""
        state = reduce_account_state(
            self.anchor,
            [],
            {"688981": {"最新价": 146}, "_updated": "2026-05-25T15:05:00"},
            now="2026-05-26T15:30:00",
        )
        self.assertFalse(state["valuation_complete"])
        self.assertEqual(state.get("quote_status"), "stale")

    def test_premarket_previous_close_quote_is_close_snapshot(self):
        """09:15前允许上一交易日收盘行情展示账户快照"""
        state = reduce_account_state(
            self.anchor,
            [],
            {"688981": {"最新价": 146}, "_updated": "2026-05-25T15:05:00"},
            now="2026-05-26T08:45:00",
        )
        self.assertTrue(state["valuation_complete"])
        self.assertEqual(state.get("quote_status"), "close_snapshot")

    def test_premarket_same_day_snapshot_remains_usable_before_collector_window(self):
        """09:15前同日盘前快照超过300s，仍可用于展示账户估值"""
        state = reduce_account_state(
            self.anchor,
            [],
            {"688981": {"最新价": 146}, "_updated": "2026-05-26T08:54:00+08:00"},
            now="2026-05-26T09:08:00+08:00",
        )
        self.assertTrue(state["valuation_complete"])
        self.assertEqual(state.get("quote_status"), "premarket_snapshot")

    def test_1501_with_1500_quote_is_close_snapshot(self):
        """15:01 使用 15:00 quote → close_snapshot(收盘后，非live)"""
        state = reduce_account_state(
            self.anchor,
            [],
            {"688981": {"最新价": 146}, "_updated": "2026-05-26T15:00:00"},
            now="2026-05-26T15:01:00",
        )
        self.assertTrue(state["valuation_complete"])
        self.assertEqual(state.get("quote_status"), "close_snapshot",
            "15:01已是收盘后，应返回close_snapshot")

    def test_live_quote_returns_live_status(self):
        """盘中实时行情返回 live"""
        state = reduce_account_state(
            self.anchor,
            [],
            {"688981": {"最新价": 146}, "_updated": "2026-05-26T10:00:01"},
            now="2026-05-26T10:00:02",
        )
        self.assertTrue(state["valuation_complete"])
        self.assertEqual(state.get("quote_status"), "live")

    def test_non_trading_day_cached_prices_are_close_snapshot(self):
        """非交易日缓存中仍有个股价格时，作为上一交易日收盘快照展示。"""
        state = reduce_account_state(
            self.anchor,
            [],
            {"688981": {"最新价": 146}, "_updated": "2026-06-06T09:45:00+08:00"},
            now="2026-06-06T10:00:00+08:00",
        )
        self.assertTrue(state["valuation_complete"])
        self.assertEqual(state.get("quote_status"), "close_snapshot")

    def test_1558_with_1557_quote_is_close_snapshot(self):
        """R2: 15:57 quote + 15:58 now → close_snapshot, val_complete=true"""
        state = reduce_account_state(
            self.anchor,
            [],
            {"688981": {"最新价": 146}, "_updated": "2026-05-26T15:57:00"},
            now="2026-05-26T15:58:00",
        )
        self.assertTrue(state["valuation_complete"])
        self.assertEqual(state.get("quote_status"), "close_snapshot",
            "收盘后1秒也不应返回live")

    def test_same_minute_trades_replay_in_append_id_order(self):
        anchor = dict(self.anchor, positions=[], cash=100000, effective_at="2026-05-26T09:00:00")
        state = reduce_account_state(
            anchor,
            [
                {"id": 2, "trade_date": "2026-05-26", "trade_time": "09:32", "action": "卖出", "code": "002463", "name": "沪电股份", "price": 122.5, "qty": 100},
                {"id": 1, "trade_date": "2026-05-26", "trade_time": "09:32", "action": "W1追涨", "code": "002463", "name": "沪电股份", "price": 122.5, "qty": 100},
            ],
            {},
            now="2026-05-26T09:33:00",
        )
        self.assertEqual(state["positions"], [])

    def test_oversell_trade_fail_closed_without_cash_inflation(self):
        """历史账本超卖：不能先加现金，必须标记 ledger_error / anchor_blocked。"""
        anchor = {
            "date": "2026-05-27", "effective_at": "2026-05-27T09:30:00",
            "cash": 100000, "day_start_asset": 101000,
            "total_deposit": 100000, "source": "previous_close",
            "positions": [{"标的": "TEST", "代码": "000001", "数量": 100, "成本": 10, "状态": "持有"}],
            "_meta": {"day_start_prices": {"000001": 10}},
        }
        trades = [{
            "id": 1, "trade_date": "2026-05-27", "trade_time": "10:00",
            "action": "卖出", "code": "000001", "name": "TEST",
            "price": 20, "qty": 150,
        }]
        quotes = {"000001": {"最新价": 21}, "_updated": "2026-05-27T10:30:00"}

        state = reduce_account_state(anchor, trades, quotes, now="2026-05-27T10:30:00")

        self.assertEqual(state["cash"], 100000, "非法超卖不得增加现金")
        self.assertFalse(state.get("ledger_ok"), f"应标记账本不可信: {state}")
        self.assertTrue(state.get("anchor_blocked"), f"应复用现有阻断语义: {state}")
        self.assertFalse(state.get("valuation_complete"), f"账本错误时估值不得可信: {state}")
        self.assertIn("ledger", state.get("block_reason", ""))
        self.assertEqual(state.get("ledger_errors", [])[0]["code"], "000001")
        self.assertEqual(state.get("ledger_errors", [])[0]["available_qty"], 100)
        self.assertEqual(state.get("ledger_errors", [])[0]["sell_qty"], 150)

    def test_oversell_nonexistent_position_fail_closed(self):
        """空持仓卖出：position 不存在时 qty > 0 也走 oversell，不增现金。"""
        anchor = {
            "date": "2026-05-27", "effective_at": "2026-05-27T09:30:00",
            "cash": 100000, "day_start_asset": 100000,
            "total_deposit": 100000, "source": "previous_close",
            "positions": [],
        }
        trades = [{
            "id": 1, "trade_date": "2026-05-27", "trade_time": "10:00",
            "action": "卖出", "code": "999999", "name": "NONEXIST",
            "price": 20, "qty": 100,
        }]
        quotes = {"999999": {"最新价": 21}, "_updated": "2026-05-27T10:30:00"}

        state = reduce_account_state(anchor, trades, quotes, now="2026-05-27T10:30:00")

        self.assertEqual(state["cash"], 100000, "空持仓卖出不得增加现金")
        self.assertFalse(state.get("ledger_ok"), f"应标记账本不可信: {state}")
        self.assertTrue(state.get("anchor_blocked"), f"应复用现有阻断语义: {state}")
        self.assertFalse(state.get("valuation_complete"), f"账本错误时估值不得可信: {state}")
        self.assertIn("ledger", state.get("block_reason", ""))
        self.assertEqual(state.get("ledger_errors", [])[0]["code"], "999999")
        self.assertEqual(state.get("ledger_errors", [])[0]["available_qty"], 0)
        self.assertEqual(state.get("ledger_errors", [])[0]["sell_qty"], 100)
        self.assertEqual(len(state.get("positions", [])), 0, "空仓不应产生持仓")
        self.assertEqual(state.get("mv"), 0, "空仓市值应为0")


class SyncBoundaryTests(unittest.TestCase):
    def test_client_cannot_overwrite_account_asset_fields(self):
        self.assertTrue(bridge._payload_overwrites_account({"pnl": {"可用资金": 0}}))
        self.assertFalse(bridge._payload_overwrites_account({"今日操作": []}))

    def test_ssot_asset_values_supersede_poisoned_snapshot_summary(self):
        merged = bridge._merge_pnl_summary(
            {"total_asset": 142546, "mv": 83571, "today_snapshots": 3},
            {"total_asset": 208562, "mv": 83283, "cash": 125279, "pnl_amount": -1915, "pnl_pct": -0.91},
        )
        self.assertEqual(merged["total_asset"], 208562)
        self.assertEqual(merged["cash"], 125279)
        self.assertEqual(merged["today_snapshots"], 3)

    def test_snapshot_row_is_derived_from_complete_account_state_only(self):
        self.assertIsNone(quotes._snapshot_from_account({"valuation_complete": False}, {}, "2026-05-26T13:02:00"))
        row = quotes._snapshot_from_account(
            {
                "valuation_complete": True, "total_asset": 208562, "mv": 83283,
                "pnl_pct": -0.91, "pos_pct": 39.93, "total_deposit": 200000,
            },
            {"上证指数涨幅": "-0.22", "深证指数涨幅": "0.10", "创业板指涨幅": "+0.05"},
            "2026-05-26T13:02:00",
        )
        self.assertEqual(row["total_asset"], 208562)
        self.assertEqual(row["pnl_pct"], -0.91)
        self.assertEqual(row["sh_pct"], -0.22)

    def test_snapshot_row_skips_non_trading_day(self):
        row = quotes._snapshot_from_account(
            {
                "valuation_complete": True, "total_asset": 720227.67, "mv": 136548,
                "pnl_pct": -0.51, "pos_pct": 18.96, "total_deposit": 711059.2252961266,
            },
            {"上证指数涨幅": "-0.74", "深证指数涨幅": "-2.21"},
            "2026-06-06T09:55:27",
        )
        self.assertIsNone(row, "非交易日不得写 intraday_snapshots")

    def test_bridge_binds_port_before_any_bootstrap_side_effect(self):
        source = Path("scripts/bridge.py").read_text(encoding="utf-8")
        main = source.index("if __name__ == '__main__':")
        bind = source.index("server = ThreadingHTTPServer(('', port), BridgeHandler)", main)
        bootstrap = source.index("_load_cache()", main)
        self.assertLess(bind, bootstrap)


class AccountAnchorStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_path = db.DB_PATH
        self.original_local = db._local
        db.DB_PATH = Path(self.tmp.name) / "pnl.db"
        db._local = threading.local()
        db.init_db()

    def tearDown(self):
        # 先从当前 _local（temp）关闭连接，再恢复原始 _local
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
        db._local = self.original_local
        db.DB_PATH = self.original_path
        self.tmp.cleanup()

    def test_first_anchor_is_locked_and_reused(self):
        self.assertIsNotNone(ensure_today_anchor)
        # Insert previous_close anchor (required by new trust rules)
        db.insert_account_baseline({
            "date": "2026-05-26", "effective_at": "2026-05-26T09:25:00",
            "trade_id_cutoff": 0, "cash": 125279, "day_start_asset": 210477,
            "total_deposit": 200000, "positions": self._positions(300),
            "source": "previous_close",
        })
        changed = {"pnl": {"可用资金": 0}, "positions": self._positions(0)}
        second = ensure_today_anchor(
            changed,
            day_start_asset=1,
            now="2026-05-26T12:00:00",
            get_anchor=db.query_account_baseline,
            insert_anchor=db.insert_account_baseline,
        )
        self.assertEqual(second["cash"], 125279)
        self.assertEqual(second["positions"][0]["数量"], 300)
        self.assertEqual(second["effective_at"], "2026-05-26T09:25:00")

    def test_load_state_replays_only_new_transactions_after_persisted_anchor(self):
        self.assertIsNotNone(load_current_account_state)
        dashboard_path = Path(self.tmp.name) / "dashboard_data.json"
        history_path = Path(self.tmp.name) / "pnl_history.json"
        dashboard_path.write_text(json.dumps({
            "pnl": {"可用资金": 125279, "累计入金": 200000},
            "positions": self._positions(300),
        }, ensure_ascii=False), encoding="utf-8")
        history_path.write_text(json.dumps({
            "meta": {"day_start_date": "2026-05-26", "day_start_asset": 210477}
        }, ensure_ascii=False), encoding="utf-8")
        # Insert previous_close anchor with 1 position (中芯国际 300 shares)
        db.insert_account_baseline({
            "date": "2026-05-26", "effective_at": "2026-05-26T09:25:00",
            "trade_id_cutoff": 0, "cash": 125279, "day_start_asset": 210477,
            "total_deposit": 200000, "positions": self._positions(300),
            "source": "previous_close",
        })
        db.insert_trade({
            "trade_date": "2026-05-26", "trade_time": "10:59", "action": "卖出",
            "code": "688981", "name": "中芯国际", "price": 147.77, "qty": 200,
        })
        load_current_account_state(
            {"688981": {"最新价": 146.01}, "_updated": "2026-05-26T11:37:10"},
            now="2026-05-26T11:37:10",
            data_file=dashboard_path,
            history_file=history_path,
        )
        db.insert_trade({
            "trade_date": "2026-05-26", "trade_time": "09:20", "action": "W2买入",
            "code": "002463", "name": "沪电股份", "price": 122.5, "qty": 100,
        })
        state = load_current_account_state(
            {"688981": {"最新价": 146.01}, "002463": {"最新价": 131.6}, "_updated": "2026-05-26T13:02:00"},
            now="2026-05-26T13:02:00",
            data_file=dashboard_path,
            history_file=history_path,
        )
        # cash: 125279 + sell(200*147.77=29554) - buy(100*122.5=12250) = 142583
        self.assertAlmostEqual(state["cash"], 142583.0, delta=1)
        self.assertEqual({p["代码"]: p["数量"] for p in state["positions"]}, {"688981": 100, "002463": 100})
        self.assertEqual([trade["id"] for trade in state["trades"]], [2, 1])
        self.assertEqual(state["_updated"], "2026-05-26T13:02:00")

    def test_non_trading_day_uses_last_trading_close_snapshot(self):
        """周末/非交易日无新行情时，账户停留在上个交易日收盘快照。"""
        self.assertIsNotNone(load_current_account_state)
        dashboard_path = Path(self.tmp.name) / "dashboard_data.json"
        history_path = Path(self.tmp.name) / "pnl_history.json"
        dashboard_path.write_text(json.dumps({
            "pnl": {"可用资金": 0, "累计入金": 200000},
            "positions": [{"标的": "光迅科技", "代码": "002281", "数量": 600, "成本": 219.49, "现价": 227.58, "状态": "持有"}],
        }, ensure_ascii=False), encoding="utf-8")
        history_path.write_text(json.dumps({
            "meta": {"day_start_date": "2026-06-05", "day_start_asset": 723899.67}
        }, ensure_ascii=False), encoding="utf-8")
        db.insert_account_baseline({
            "date": "2026-06-05", "effective_at": "2026-06-05T09:25:00",
            "trade_id_cutoff": 0, "cash": 583679.67, "day_start_asset": 723899.67,
            "total_deposit": 711059.2252961266,
            "positions": [{"标的": "光迅科技", "代码": "002281", "数量": 600, "成本": 219.49, "现价": 227.58, "状态": "持有"}],
            "source": "previous_close",
            "_meta": {"day_start_prices": {"002281": 220.56}},
        })
        state = load_current_account_state(
            {"002281": {"最新价": 227.58}, "_updated": "2026-06-05T16:07:58"},
            now="2026-06-06T09:45:00",
            data_file=dashboard_path,
            history_file=history_path,
        )
        self.assertEqual(state["date"], "2026-06-05")
        self.assertFalse(state.get("anchor_blocked"), state)
        self.assertTrue(state.get("valuation_complete"), state)
        self.assertEqual(state.get("quote_status"), "close_snapshot")
        self.assertEqual(state["mv"], 136548.0)
        self.assertAlmostEqual(state["total_asset"], 720227.67, places=2)

    @staticmethod
    def _positions(qty):
        return [{"标的": "中芯国际", "代码": "688981", "数量": qty, "现价": 146.01, "状态": "持有"}]


class ClosingAnchorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_path = db.DB_PATH
        self.original_local = db._local
        db.DB_PATH = Path(self.tmp.name) / "pnl.db"
        db._local = threading.local()
        db.init_db()

    def tearDown(self):
        # 先从当前 _local（temp）关闭连接，再恢复原始 _local
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
        db._local = self.original_local
        db.DB_PATH = self.original_path
        self.tmp.cleanup()

    def test_closing_anchor_generates_next_day_previous_close_anchor(self):
        from scripts.account_ssot import generate_closing_anchor, query_previous_close_anchor

        # 1. 先建今日锚点 + 一笔买入
        dashboard_path = Path(self.tmp.name) / "dashboard_data.json"
        history_path = Path(self.tmp.name) / "pnl_history.json"
        dashboard_path.write_text(json.dumps({
            "pnl": {"可用资金": 100000, "累计入金": 100000},
            "positions": [{"标的": "沪电", "代码": "002463", "数量": 0, "现价": 100, "状态": "持有"}],
        }, ensure_ascii=False), encoding="utf-8")

        db.insert_account_baseline({
            "date": "2026-05-26",
            "effective_at": "2026-05-26T09:30:00",
            "trade_id_cutoff": 0,
            "cash": 100000,
            "day_start_asset": 100000,
            "total_deposit": 100000,
            "positions": [],
            "source": "recovery",
        })
        db.insert_trade({
            "trade_date": "2026-05-26", "trade_time": "09:32", "action": "买入",
            "code": "002463", "name": "沪电股份", "price": 100.0, "qty": 300,
        })

        # 2. 执行收盘锚点生成（模拟收盘行情）
        # 传入 pnl_history_path=history_path，避免写入真实 data/pnl_history.json
        result = generate_closing_anchor(
            {"002463": {"最新价": 105.0}, "_updated": "2026-05-26T15:00:00"},
            now="2026-05-26T15:05:00",
            pnl_history_path=history_path,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["next_date"], "2026-05-27")
        self.assertGreater(result["nav"], 1.0)  # 沪电涨了，NAV 应大于 1

        # 验证次日锚点存在且 source=previous_close
        next_anchor = query_previous_close_anchor("2026-05-27", db.query_account_baseline)
        self.assertIsNotNone(next_anchor)
        self.assertEqual(next_anchor["source"], "previous_close")
        # 锚点 cash 来自锚点持仓快照，不重放流水（已有沪电持仓 0 股，数量来自 dashboard）
        # reduce 不会改变锚点中的现金，只更新市值；锚点 cash=100000，重放无新流水所以不变
        # 收盘时：cash=70000（无新流水），mv=300*105=31500，total_asset=101500
        self.assertEqual(next_anchor["cash"], 70000)  # 100000 + 0流水 + reduce调整
        # 次日 day_start_asset = 今日收盘总资产
        self.assertEqual(next_anchor["day_start_asset"], 101500)  # 收盘总资产

        # 验证今日锚点被更新了 _meta
        today_anchor = db.query_account_baseline("2026-05-26")
        self.assertIsNotNone(today_anchor.get("_meta"))
        self.assertIn("nav", today_anchor["_meta"])
        self.assertIn("pnl_pct", today_anchor["_meta"])

    def test_closing_anchor_preserves_existing_day_start_prices(self):
        from scripts.account_ssot import generate_closing_anchor

        history_path = Path(self.tmp.name) / "pnl_history.json"
        db.insert_account_baseline({
            "date": "2026-05-26",
            "effective_at": "2026-05-26T09:30:00",
            "trade_id_cutoff": 0,
            "cash": 70000,
            "day_start_asset": 101500,
            "total_deposit": 100000,
            "positions": [{"标的": "沪电", "代码": "002463", "数量": 300, "成本": 100, "现价": 105}],
            "source": "previous_close",
            "_meta": {"day_start_prices": {"002463": 105.0}},
        })

        result = generate_closing_anchor(
            {"002463": {"最新价": 106.0}, "_updated": "2026-05-26T15:00:00"},
            now="2026-05-26T15:05:00",
            pnl_history_path=history_path,
        )

        self.assertIsNotNone(result)
        today_anchor = db.query_account_baseline("2026-05-26")
        meta = today_anchor.get("_meta") or {}
        self.assertEqual(meta.get("day_start_prices"), {"002463": 105.0})
        self.assertIn("nav", meta)
        self.assertIn("pnl_pct", meta)

    def test_previous_close_anchor_is_used_by_ensure_today_anchor(self):
        from scripts.account_ssot import ensure_today_anchor, load_current_account_state

        # 建次日 previous_close 锚点
        db.insert_account_baseline({
            "date": "2026-05-27",
            "effective_at": "2026-05-27T09:25:00",
            "trade_id_cutoff": 0,
            "cash": 68500,
            "day_start_asset": 101500,
            "total_deposit": 100000,
            "positions": [{"标的": "沪电", "代码": "002463", "数量": 300, "成本": 100, "现价": 105}],
            "source": "previous_close",
        })

        # 模拟 load_current_account_state 调用 ensure_today_anchor
        dashboard_path = Path(self.tmp.name) / "dashboard_data.json"
        history_path = Path(self.tmp.name) / "pnl_history.json"
        dashboard_path.write_text(json.dumps({"pnl": {}, "positions": []}, ensure_ascii=False), encoding="utf-8")
        history_path.write_text(json.dumps({"meta": {}}, ensure_ascii=False), encoding="utf-8")

        state = load_current_account_state(
            {"002463": {"最新价": 106.0}, "_updated": "2026-05-27T09:35:00"},
            now="2026-05-27T09:35:00",
            data_file=dashboard_path,
            history_file=history_path,
        )

        # 现金来自 previous_close 锚点，不是 dashboard_data
        self.assertEqual(state["cash"], 68500)
        # day_start_asset 来自 previous_close
        self.assertEqual(state["day_start_asset"], 101500)
        # 当日买入沪电（trade_id_cutoff=0，所以不跳过任何流水）
        # 但这里我们没有插入任何新流水，所以持仓保持 300 股不变
        self.assertEqual(state["positions"][0]["数量"], 300)


class CorrectionTradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_path = db.DB_PATH
        self.original_local = db._local
        db.DB_PATH = Path(self.tmp.name) / "pnl.db"
        db._local = threading.local()
        db.init_db()

    def tearDown(self):
        # 先从当前 _local（temp）关闭连接，再恢复原始 _local
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
        db._local = self.original_local
        db.DB_PATH = self.original_path
        self.tmp.cleanup()

    def test_correction_creates_reversal_trade(self):
        # 插入原始成交
        db.insert_trade({
            "trade_date": "2026-05-26", "trade_time": "09:32",
            "action": "买入", "code": "002463", "name": "沪电股份",
            "price": 122.5, "qty": 300,
        })
        # 纠错：部分卖出
        new_id = db.insert_correction_trade(
            original_trade_id=1,
            correction_action="卖出",
            correction_price=120.0,
            correction_qty=100,
            note="部分纠错",
        )
        self.assertIsNotNone(new_id)
        trades = db.query_trades(date_from="2026-05-26", limit=10)
        reversal = next((t for t in trades if t["is_reversal"] == 1), None)
        self.assertIsNotNone(reversal)
        self.assertEqual(reversal["reversal_of_id"], 1)
        self.assertEqual(reversal["action"], "卖出")
        self.assertEqual(reversal["qty"], 100)
        self.assertIn("纠错", reversal["reason"])

    def test_reversal_of_nonexistent_trade_raises(self):
        with self.assertRaises(ValueError):
            db.insert_correction_trade(999, None, None, None, "no such trade")

    def test_reversing_sell_restores_quantity_without_repricing_position(self):
        anchor = {
            "date": "2026-07-13",
            "effective_at": "2026-07-13T09:25:00",
            "cash": 388947.47,
            "day_start_asset": 0,
            "source": "previous_close",
            "positions": [{
                "标的": "海兰信", "代码": "300065", "数量": 8000,
                "成本": 22.40, "现价": 25.64, "状态": "持有",
            }],
        }
        trades = [
            {"id": 137, "trade_date": "2026-07-13", "trade_time": "14:50",
             "action": "卖出", "code": "300065", "name": "海兰信",
             "price": 26.11, "qty": 3000, "fee": 0},
            {"id": 134, "trade_date": "2026-07-13", "trade_time": "17:28:57",
             "action": "卖出", "code": "300065", "name": "海兰信",
             "price": 25.64, "qty": 3000, "fee": 0},
            {"id": 136, "trade_date": "2026-07-13", "trade_time": "17:49:35",
             "action": "买入", "code": "300065", "name": "海兰信",
             "price": 25.64, "qty": 3000, "fee": 0,
             "is_reversal": 1, "reversal_of_id": 134},
        ]

        state = reduce_account_state(anchor, trades, {}, now="2026-07-13T18:00:00")

        self.assertEqual(467277.47, state["cash"])
        self.assertEqual(5000, state["positions"][0]["数量"])
        self.assertEqual(22.40, state["positions"][0]["成本"])


class FullLifecycleReplayTests(unittest.TestCase):
    """完整生命周期回放：日初锚点 → 盘中交易 → 重复提交幂等 → 冲销纠错 → bridge 重启 → 收盘日结 → 次日启动"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_path = db.DB_PATH
        self.original_local = db._local
        db.DB_PATH = Path(self.tmp.name) / "pnl.db"
        db._local = threading.local()
        db.init_db()
        # 创建今日（2026-05-26）的 previous_close 锚点：
        # 这模拟的是"今日开盘前，日结流程已生成好了次日锚点"的状态。
        # day_start_asset = 昨日收盘 total_asset = cash + mv = 80000 + 500*40 = 100000
        db.insert_account_baseline({
            "date": "2026-05-26",
            "effective_at": "2026-05-26T09:25:00",
            "trade_id_cutoff": 0,
            "cash": 80000,
            "day_start_asset": 100000,
            "total_deposit": 100000,
            "positions": [{"标的": "A股票", "代码": "000001", "数量": 500, "成本": 40, "现价": 40}],
            "source": "previous_close",
        })

    def tearDown(self):
        # 先从当前 _local（temp）关闭连接，再恢复原始 _local
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
        db._local = self.original_local
        db.DB_PATH = self.original_path
        self.tmp.cleanup()

    def test_full_day_replay_lifecycle(self):
        from scripts.account_ssot import (load_current_account_state, generate_closing_anchor,
                                          reduce_account_state, query_previous_close_anchor)

        # === 阶段1：次日开盘锚点自动锁定 ===
        # (simulate: ensure_today_anchor uses previous_close anchor)
        dashboard_path = Path(self.tmp.name) / "dashboard_data.json"
        history_path = Path(self.tmp.name) / "pnl_history.json"
        dashboard_path.write_text(json.dumps({"pnl": {}, "positions": []}, ensure_ascii=False), encoding="utf-8")
        history_path.write_text(json.dumps({"meta": {}}, ensure_ascii=False), encoding="utf-8")

        state_day1 = load_current_account_state(
            {"000001": {"最新价": 41.0}, "_updated": "2026-05-26T09:35:00"},
            now="2026-05-26T09:35:00",
            data_file=dashboard_path,
            history_file=history_path,
        )
        # day_start_asset 来自昨日收盘 total_asset = 80000 + 500*40 = 100000
        self.assertEqual(state_day1["day_start_asset"], 100000)
        # cash 来自 previous_close
        self.assertEqual(state_day1["cash"], 80000)
        # 市值 = 500 * 41 = 20500
        self.assertEqual(state_day1["mv"], 20500)
        # total_asset = 80000 + 20500 = 100500
        self.assertEqual(state_day1["total_asset"], 100500)

        # === 阶段2：盘中买入 ===
        db.insert_trade({
            "trade_date": "2026-05-26", "trade_time": "09:40", "action": "W2买入",
            "code": "000001", "name": "A股票", "price": 41.0, "qty": 200,
        })
        state_after_buy = load_current_account_state(
            {"000001": {"最新价": 41.5}, "_updated": "2026-05-26T09:41:00"},
            now="2026-05-26T09:41:00",
            data_file=dashboard_path,
            history_file=history_path,
        )
        # 现金: 80000 - 200*41 = 71800
        self.assertEqual(state_after_buy["cash"], 71800)
        # 持仓: 500 + 200 = 700
        self.assertEqual(state_after_buy["positions"][0]["数量"], 700)
        # 市值: 700 * 41.5 = 29050
        self.assertEqual(state_after_buy["mv"], 29050)
        # total_asset: 71800 + 29050 = 100850
        self.assertEqual(state_after_buy["total_asset"], 100850)

        # === 阶段3：重复提交幂等 ===
        inserted = db.insert_trade({
            "trade_date": "2026-05-26", "trade_time": "09:40", "action": "W2买入",
            "code": "000001", "name": "A股票", "price": 41.0, "qty": 200,
        })
        self.assertFalse(inserted)  # 唯一索引幂等，不重复插入

        # === 阶段4：资金入金 ===
        db.insert_fund_event({
            "event_date": "2026-05-26",
            "event_type": "入金",
            "amount": 10000,
            "note": "追加本金",
        })
        state_after_deposit = load_current_account_state(
            {"000001": {"最新价": 41.5}, "_updated": "2026-05-26T10:00:00"},
            now="2026-05-26T10:00:00",
            data_file=dashboard_path,
            history_file=history_path,
        )
        # 现金: 71800 + 10000 = 81800
        self.assertEqual(state_after_deposit["cash"], 81800)

        # === 阶段5：部分卖出 ===
        db.insert_trade({
            "trade_date": "2026-05-26", "trade_time": "10:30", "action": "卖出",
            "code": "000001", "name": "A股票", "price": 42.0, "qty": 300,
        })
        state_after_sell = load_current_account_state(
            {"000001": {"最新价": 42.0}, "_updated": "2026-05-26T10:31:00"},
            now="2026-05-26T10:31:00",
            data_file=dashboard_path,
            history_file=history_path,
        )
        # 现金: 81800 + 300*42 = 94400
        self.assertEqual(state_after_sell["cash"], 94400)
        # 持仓: 700 - 300 = 400
        self.assertEqual(state_after_sell["positions"][0]["数量"], 400)
        # 市值: 400 * 42 = 16800
        self.assertEqual(state_after_sell["mv"], 16800)
        # total_asset: 94400 + 16800 = 111200
        self.assertEqual(state_after_sell["total_asset"], 111200)

        # === 阶段6：收盘日结 ===
        # 收盘价=42.5 → 持仓市值=400*42.5=17000，cash=94400，total_asset=111400
        # 传入 pnl_history_path=history_path，避免写入真实 data/pnl_history.json
        result = generate_closing_anchor(
            {"000001": {"最新价": 42.5}, "_updated": "2026-05-26T15:00:00"},
            now="2026-05-26T15:05:00",
            pnl_history_path=history_path,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["next_date"], "2026-05-27")

        # === 阶段7：次日开盘锚点锁定 ===
        dashboard_path.write_text(json.dumps({"pnl": {}, "positions": []}, ensure_ascii=False), encoding="utf-8")
        history_path.write_text(json.dumps({"meta": {}}, ensure_ascii=False), encoding="utf-8")

        state_day2 = load_current_account_state(
            {"000001": {"最新价": 43.0}, "_updated": "2026-05-27T09:35:00"},
            now="2026-05-27T09:35:00",
            data_file=dashboard_path,
            history_file=history_path,
        )
        # 现金: 94400（昨日收盘现金不变）
        self.assertEqual(state_day2["cash"], 94400)
        # day_start_asset: 昨日收盘 total_asset = 111400（持仓400股×42.5=17000 + cash=94400）
        self.assertEqual(state_day2["day_start_asset"], 111400)
        # 市值: 400 * 43 = 17200
        self.assertEqual(state_day2["mv"], 17200)
        # total_asset: 94400 + 17200 = 111600
        self.assertEqual(state_day2["total_asset"], 111600)

        # === 阶段8：次日新买入 ===
        db.insert_trade({
            "trade_date": "2026-05-27", "trade_time": "09:36", "action": "W1追涨",
            "code": "600001", "name": "B股票", "price": 10.0, "qty": 500,
        })
        state_day2_after_buy = load_current_account_state(
            {"000001": {"最新价": 43.0}, "600001": {"最新价": 10.5}, "_updated": "2026-05-27T09:37:00"},
            now="2026-05-27T09:37:00",
            data_file=dashboard_path,
            history_file=history_path,
        )
        # 现金: 94400 - 500*10 = 89400
        self.assertEqual(state_day2_after_buy["cash"], 89400)
        # A持仓: 400, B持仓: 500
        pos_by_code = {p["代码"]: p["数量"] for p in state_day2_after_buy["positions"]}
        self.assertEqual(pos_by_code.get("000001"), 400)
        self.assertEqual(pos_by_code.get("600001"), 500)


class BackfillDayStartPriceTests(unittest.TestCase):
    """R7: backfill_day_start_price 受控补录（注入式回调 + 审计分离）"""

    def setUp(self):
        import tempfile, threading
        self.tmp = tempfile.TemporaryDirectory()
        self.original_path = db.DB_PATH
        self.original_local = db._local
        db.DB_PATH = Path(self.tmp.name) / "pnl.db"
        db._local = threading.local()
        db.init_db()

    def tearDown(self):
        conn = getattr(db._local, "conn", None)
        if conn is not None: conn.close()
        db._local = self.original_local
        db.DB_PATH = self.original_path
        self.tmp.cleanup()

    def _callbacks(self):
        """返回注入临时库的 get_anchor / update_meta"""
        from scripts.db import query_account_baseline, _exec_write
        def get_anchor(d):
            return query_account_baseline(d)
        def update_meta(d, m):
            _exec_write(
                "UPDATE account_baselines SET _meta_json = ? WHERE date = ?",
                (json.dumps(m, ensure_ascii=False), d))
        return get_anchor, update_meta

    def _make_anchor(self, code="002436", qty=1500, cost=38.28,
                     day_start_prices=None, source="manual_correction"):
        """Helper: 在临时DB创建锚点"""
        meta = None
        if day_start_prices:
            meta = {"day_start_prices": day_start_prices}
        db.insert_account_baseline({
            "date": "2026-05-27",
            "effective_at": "2026-05-27T09:30:00",
            "trade_id_cutoff": 0,
            "cash": 100187,
            "day_start_asset": 209786,
            "total_deposit": 200000,
            "positions": [{"标的": "兴森科技", "代码": code, "数量": qty,
                           "成本": cost, "状态": "持有"}],
            "source": source,
            "_meta": meta,
        })

    # —— 拒绝场景 ——

    def test_reject_source_empty(self):
        self.assertIsNotNone(backfill_day_start_price)
        self._make_anchor()
        ga, um = self._callbacks()
        for bad in ["", "  ", None]:
            result = backfill_day_start_price(
                "2026-05-27", "002436", 38.11,
                bad, "reason ok", get_anchor=ga, update_meta=um)
            self.assertEqual(result["action"], "rejected",
                             f"source={bad!r} 应拒绝: {result}")
            self.assertIn("source", result["error"].lower())

    def test_reject_reason_empty(self):
        self._make_anchor()
        ga, um = self._callbacks()
        for bad in ["", "  ", None]:
            result = backfill_day_start_price(
                "2026-05-27", "002436", 38.11,
                "source ok", bad, get_anchor=ga, update_meta=um)
            self.assertEqual(result["action"], "rejected",
                             f"reason={bad!r} 应拒绝: {result}")
            self.assertIn("reason", result["error"].lower())

    def test_reject_code_not_in_anchor(self):
        self.assertIsNotNone(backfill_day_start_price)
        self._make_anchor(code="002436")
        ga, um = self._callbacks()
        result = backfill_day_start_price(
            "2026-05-27", "999999", 38.11,
            "test", "code不在锚点", get_anchor=ga, update_meta=um)
        self.assertEqual(result["action"], "rejected")
        self.assertIn("不在", result["error"])

    def test_reject_price_zero_or_negative(self):
        self._make_anchor()
        ga, um = self._callbacks()
        for bad in [0, -1, "abc"]:
            result = backfill_day_start_price(
                "2026-05-27", "002436", bad,
                "test", "非法价格", get_anchor=ga, update_meta=um)
            self.assertEqual(result["action"], "rejected",
                             f"price={bad} 应拒绝: {result}")

    def test_reject_already_exists(self):
        self._make_anchor(day_start_prices={"002436": 38.28})
        ga, um = self._callbacks()
        result = backfill_day_start_price(
            "2026-05-27", "002436", 38.11,
            "test", "已有价格", get_anchor=ga, update_meta=um)
        self.assertEqual(result["action"], "idempotent")
        self.assertEqual(result["existing_price"], 38.28)

    def test_reject_no_anchor_for_date(self):
        ga, um = self._callbacks()
        result = backfill_day_start_price(
            "2026-05-20", "002436", 38.11,
            "test", "无锚点", get_anchor=ga, update_meta=um)
        self.assertEqual(result["action"], "rejected")
        self.assertIn("无锚点", result["error"])

    # —— 成功场景 ——

    def test_backfill_restores_today_pnl(self):
        """兴森风格：隔夜仓缺 day_start_price → 补入38.11后 today_pnl 恢复"""
        self._make_anchor(code="002436", day_start_prices=None)
        ga, um = self._callbacks()

        quotes = {"002436": {"最新价": 37.69},
                  "_updated": "2026-05-27T11:00:00+08:00"}
        state_before = reduce_account_state(
            db.query_account_baseline("2026-05-27"), [], quotes,
            now="2026-05-27T11:00:00")
        pos_before = state_before["positions"][0]
        self.assertIsNone(pos_before["today_pnl"],
            f"补录前应为None, 实为{pos_before['today_pnl']}")

        result = backfill_day_start_price(
            "2026-05-27", "002436", 38.11,
            "sina_daily_2026-05-26_close",
            "兴森科技隔夜仓缺日初基准，主人确认收盘价38.11补录",
            get_anchor=ga, update_meta=um)
        self.assertEqual(result["action"], "written",
            f"应写入成功: {result}")
        self.assertEqual(result["after_prices"]["002436"], 38.11)
        # 审计字段独立
        self.assertIsNotNone(result.get("repair_entry"))
        self.assertEqual(result["repair_entry"]["code"], "002436")
        self.assertEqual(result["repair_entry"]["price"], 38.11)

        state_after = reduce_account_state(
            db.query_account_baseline("2026-05-27"), [], quotes,
            now="2026-05-27T11:00:01")
        pos_after = state_after["positions"][0]
        self.assertEqual(pos_after["today_pnl"], -630,
            f"补录后应恢复today_pnl=-630, 实为{pos_after['today_pnl']}")
        self.assertAlmostEqual(pos_after["today_pnl_pct"], -1.10, delta=0.05,
            msg=f"today_pnl_pct={pos_after['today_pnl_pct']}")

    def test_day_start_prices_clean_no_audit_inside(self):
        """day_start_prices 只含 code->number，审计在 day_start_price_repairs"""
        self._make_anchor(code="002436", day_start_prices=None)
        ga, um = self._callbacks()
        backfill_day_start_price(
            "2026-05-27", "002436", 38.11,
            "test_source", "test_reason",
            get_anchor=ga, update_meta=um)

        anchor = db.query_account_baseline("2026-05-27")
        meta = anchor.get("_meta") or {}
        prices = meta.get("day_start_prices") or {}
        # day_start_prices 只含数字值
        self.assertNotIn("_backfill", prices)
        for k, v in prices.items():
            self.assertIsInstance(v, (int, float), f"prices[{k}]={v!r} 应为数字")
        # 审计在独立数组
        repairs = meta.get("day_start_price_repairs") or []
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]["code"], "002436")
        self.assertEqual(repairs[0]["source"], "test_source")

    def test_backfill_does_not_change_cash_positions_trades(self):
        """补录不改变 cash/positions/trades/day_start_asset"""
        self._make_anchor(code="002436", day_start_prices=None)
        ga, um = self._callbacks()

        state_before = reduce_account_state(
            db.query_account_baseline("2026-05-27"), [],
            {"002436": {"最新价": 37.69},
             "_updated": "2026-05-27T11:00:00+08:00"},
            now="2026-05-27T11:00:00")

        backfill_day_start_price(
            "2026-05-27", "002436", 38.11,
            "test", "测试不改变核心数据",
            get_anchor=ga, update_meta=um)

        state_after = reduce_account_state(
            db.query_account_baseline("2026-05-27"), [],
            {"002436": {"最新价": 37.69},
             "_updated": "2026-05-27T11:00:01+08:00"},
            now="2026-05-27T11:00:01")

        self.assertEqual(state_before["cash"], state_after["cash"])
        self.assertEqual(state_before["day_start_asset"], state_after["day_start_asset"])
        self.assertEqual(state_before["total_deposit"], state_after["total_deposit"])
        self.assertEqual(state_before["mv"], state_after["mv"])
        self.assertEqual(len(state_before["positions"]), len(state_after["positions"]))
        self.assertEqual(state_before["positions"][0]["数量"],
                         state_after["positions"][0]["数量"])

    def test_dry_run_does_not_write(self):
        self._make_anchor(code="002436", day_start_prices=None)
        ga, um = self._callbacks()
        result = backfill_day_start_price(
            "2026-05-27", "002436", 38.11,
            "test", "dry-run测试", dry_run=True,
            get_anchor=ga, update_meta=um)
        self.assertEqual(result["action"], "would_write")

        anchor = db.query_account_baseline("2026-05-27")
        meta = anchor.get("_meta") or {}
        prices = meta.get("day_start_prices") or {}
        self.assertNotIn("002436", prices, "dry-run不应写入DB")

    def test_repeat_backfill_idempotent(self):
        self._make_anchor(code="002436", day_start_prices=None)
        ga, um = self._callbacks()
        r1 = backfill_day_start_price(
            "2026-05-27", "002436", 38.11,
            "test", "第一次", get_anchor=ga, update_meta=um)
        self.assertEqual(r1["action"], "written")
        r2 = backfill_day_start_price(
            "2026-05-27", "002436", 38.50,
            "test", "第二次应拒绝", get_anchor=ga, update_meta=um)
        self.assertEqual(r2["action"], "idempotent")
        anchor = db.query_account_baseline("2026-05-27")
        prices = (anchor.get("_meta") or {}).get("day_start_prices") or {}
        self.assertEqual(prices["002436"], 38.11)

    def test_injected_callbacks_only_touch_temp_db(self):
        """注入回调只操作临时库，不碰默认 data/pnl.db"""
        import os
        real_mtime_before = os.path.getmtime(self.original_path) if os.path.exists(str(self.original_path)) else None
        self._make_anchor(code="002436", day_start_prices=None)
        ga, um = self._callbacks()
        backfill_day_start_price(
            "2026-05-27", "002436", 38.11,
            "test", "注入回调测试", get_anchor=ga, update_meta=um)
        if real_mtime_before is not None:
            real_mtime_after = os.path.getmtime(str(self.original_path))
            self.assertEqual(real_mtime_before, real_mtime_after,
                "真实 data/pnl.db 不得被注入回调修改")

    # —— R8+R9: CLI 安全边界 ——

    def test_dry_run_static_db_no_sidecar_created(self):
        """无 WAL 的静态库 dry-run：主库 hash/mtime 不变，不新建 -wal/-shm"""
        import hashlib, os

        # 用 DELETE journal mode 自建干净 DB，绕过 db 模块的 WAL 默认
        temp_db = Path(self.tmp.name) / "static.db"
        conn = sqlite3.connect(str(temp_db))
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("CREATE TABLE account_baselines (date TEXT PRIMARY KEY,"
                     " effective_at TEXT, cash REAL, day_start_asset REAL,"
                     " total_deposit REAL, positions_json TEXT, source TEXT,"
                     " _meta_json TEXT, trade_id_cutoff INTEGER)")
        conn.execute("INSERT INTO account_baselines VALUES (?,?,?,?,?,?,?,?,?)",
                     ("2026-05-27", "2026-05-27T09:30:00", 100187, 209786,
                      200000,
                      json.dumps([{"标的": "兴森", "代码": "002436", "数量": 1500,
                                   "成本": 38.28, "状态": "持有"}]),
                      "manual_correction", None, 0))
        conn.commit()
        conn.close()

        # 确认无 sidecar
        for suf in ["-wal", "-shm"]:
            self.assertFalse(Path(str(temp_db) + suf).exists(),
                             f"DELETE模式不应有{suf}")

        hash_before = hashlib.sha256(temp_db.read_bytes()).hexdigest()
        mtime_before = os.path.getmtime(str(temp_db))

        from scripts.repair_day_start_price import _ro_query_anchor
        anchor = _ro_query_anchor(str(temp_db), "2026-05-27")
        self.assertIsNotNone(anchor)
        self.assertEqual(anchor["source"], "manual_correction")
        self.assertEqual(len(anchor.get("positions") or []), 1)

        # hash/mtime 不变
        self.assertEqual(hash_before,
                         hashlib.sha256(temp_db.read_bytes()).hexdigest(),
                         "只读连接不得修改源库 hash")
        self.assertEqual(mtime_before, os.path.getmtime(str(temp_db)),
                         "只读连接不得修改源库 mtime")

        # 不新建 sidecar
        for suf in ["-wal", "-shm"]:
            self.assertFalse(Path(str(temp_db) + suf).exists(),
                             f"只读连接不得创建{suf}")

    def test_ro_query_reads_active_wal_data(self):
        """保持 writer 连接 open，WAL 中有未 checkpoint 记录 → _ro_query 必须读到"""
        import sqlite3

        temp_db = Path(self.tmp.name) / "wal_active.db"
        writer = sqlite3.connect(str(temp_db))
        writer.execute("PRAGMA journal_mode=WAL")
        # 关闭 autocheckpoint
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE account_baselines (date TEXT PRIMARY KEY,"
                       " effective_at TEXT, cash REAL, day_start_asset REAL,"
                       " total_deposit REAL, positions_json TEXT, source TEXT,"
                       " _meta_json TEXT, trade_id_cutoff INTEGER)")
        writer.execute("INSERT INTO account_baselines VALUES (?,?,?,?,?,?,?,?,?)",
                       ("2026-05-27", "2026-05-27T09:30:00", 100187, 209786,
                        200000,
                        json.dumps([{"标的": "兴森", "代码": "002436", "数量": 1500,
                                     "成本": 38.28, "状态": "持有"}]),
                        "previous_close", None, 0))
        writer.commit()

        # 通过 writer 更新 _meta_json（写入 WAL，不 checkpoint）
        new_meta = {"day_start_prices": {"002436": 38.11}}
        writer.execute("UPDATE account_baselines SET _meta_json = ? WHERE date = ?",
                       (json.dumps(new_meta), "2026-05-27"))
        writer.commit()
        # writer 保持 open，WAL 中有未 checkpoint 的 day_start_prices

        # 另一只读连接应读取到 WAL 中的最新数据
        from scripts.repair_day_start_price import _ro_query_anchor
        anchor = _ro_query_anchor(str(temp_db), "2026-05-27")
        self.assertIsNotNone(anchor, "应能读取 account_baselines 表")

        meta = anchor.get("_meta") or {}
        prices = meta.get("day_start_prices") or {}
        self.assertIn("002436", prices,
                      f"应读取到 WAL 中的 day_start_prices: {meta}")
        self.assertEqual(prices["002436"], 38.11,
                         "价格应为 WAL 中最新值")

        writer.close()

    def test_backup_includes_wal_data_and_integrity_ok(self):
        """构造 WAL 中有已提交但未 checkpoint 记录的库，backup 包含这些记录"""
        import sqlite3

        temp_db = Path(self.tmp.name) / "test_wal.db"
        backup_db = Path(self.tmp.name) / "test_backup.db"

        # 创建库，启用 WAL，写入数据
        conn = sqlite3.connect(str(temp_db))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS account_baselines (date TEXT PRIMARY KEY)")
        conn.execute("INSERT OR REPLACE INTO account_baselines VALUES ('test')")
        conn.commit()
        # 不关闭 conn — WAL 中有已提交但未 checkpoint 的记录

        # 用 backup API 创建备份（另一连接）
        from scripts.repair_day_start_price import _sqlite_backup, _integrity_check
        _sqlite_backup(str(temp_db), str(backup_db))

        # 备份库应有数据
        bconn = sqlite3.connect(str(backup_db))
        row = bconn.execute("SELECT date FROM account_baselines").fetchone()
        self.assertIsNotNone(row, "备份应包含 WAL 中已提交记录")
        self.assertEqual(row[0], "test")
        bconn.close()

        # integrity_check
        ok, detail = _integrity_check(str(backup_db))
        self.assertTrue(ok, f"备份 integrity_check 应为 ok: {detail}")

        conn.close()

    def test_apply_only_adds_target_price_and_audit(self):
        """apply 后只新增 day_start_price + repair，不改 cash/positions"""
        self._make_anchor(code="002436", day_start_prices=None)
        ga, um = self._callbacks()

        anchor_before = db.query_account_baseline("2026-05-27")
        cash_before = anchor_before["cash"]
        positions_before = json.dumps(anchor_before.get("positions", []))

        backfill_day_start_price(
            "2026-05-27", "002436", 38.11,
            "test_source", "test_reason",
            get_anchor=ga, update_meta=um)

        anchor_after = db.query_account_baseline("2026-05-27")
        self.assertEqual(anchor_after["cash"], cash_before)
        self.assertEqual(json.dumps(anchor_after.get("positions", [])), positions_before)

        meta = anchor_after.get("_meta") or {}
        prices = meta.get("day_start_prices") or {}
        self.assertIn("002436", prices)
        self.assertEqual(prices["002436"], 38.11)
        self.assertNotIn("_backfill", prices, "prices 不得含审计信息")

        repairs = meta.get("day_start_price_repairs") or []
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]["source"], "test_source")


class PerStockMetricsTest(unittest.TestCase):
    """逐股 today_pnl / total_pnl / closed_positions 回归"""

    def setUp(self):
        import tempfile, threading
        self.tmp = tempfile.TemporaryDirectory()
        self.original_path = db.DB_PATH
        self.original_local = db._local
        db.DB_PATH = Path(self.tmp.name) / "pnl.db"
        db._local = threading.local()
        db.init_db()

    def tearDown(self):
        conn = getattr(db._local, "conn", None)
        if conn is not None: conn.close()
        db._local = self.original_local
        db.DB_PATH = self.original_path
        self.tmp.cleanup()

    def test_ziguang_buy_today_pnl(self):
        """紫光案例：今日买入600@87，现价88.50，today_pnl=900, today_pnl_pct≈1.72%"""
        db.insert_account_baseline({
            "date": "2026-05-27", "effective_at": "2026-05-27T09:30:00",
            "trade_id_cutoff": 0, "cash": 100187, "day_start_asset": 209786,
            "total_deposit": 200000, "positions": [], "source": "manual_correction",
        })
        db.insert_trade({
            "trade_date": "2026-05-27", "trade_time": "10:03",
            "action": "W1追涨", "code": "002049", "name": "紫光国微",
            "price": 87.0, "qty": 600,
        })
        quotes = {"002049": {"最新价": 88.50}, "_updated": "2026-05-27T10:30:00+08:00"}
        state = reduce_account_state(
            db.query_account_baseline("2026-05-27"),
            db.query_trades(date_from="2026-05-27", date_to="2026-05-27", limit=100),
            quotes, now="2026-05-27T10:30:00")
        pos = state["positions"][0]
        self.assertEqual(pos["代码"], "002049")
        self.assertAlmostEqual(pos["today_pnl"], 900, delta=5)
        self.assertAlmostEqual(pos["today_pnl_pct"], 1.72, delta=0.1,
            msg=f"紫光 today_pnl_pct={pos['today_pnl_pct']:.2f}% 不应接近 6.69%")

    # —— R3 逐股盈亏账本测试 ——

    def test_overnight_plus_buy_today_pnl(self):
        """隔夜100@10 + 今日买100@20 + 现价21 => today_pnl=1200, pct=40.00"""
        anchor = {
            "date": "2026-05-27", "effective_at": "2026-05-27T09:30:00",
            "cash": 100000, "day_start_asset": 101000,
            "total_deposit": 100000, "source": "previous_close",
            "positions": [{"标的": "TEST", "代码": "000001", "数量": 100, "成本": 10, "状态": "持有"}],
            "_meta": {"day_start_prices": {"000001": 10}},
        }
        trades = [{"id": 1, "trade_date": "2026-05-27", "trade_time": "10:00",
                    "action": "买入", "code": "000001", "name": "TEST",
                    "price": 20, "qty": 100}]
        quotes = {"000001": {"最新价": 21}, "_updated": "2026-05-27T10:30:00"}
        state = reduce_account_state(anchor, trades, quotes, now="2026-05-27T10:30:00")
        pos = state["positions"][0]
        self.assertEqual(pos["today_pnl"], 1200)
        self.assertEqual(pos["today_pnl_pct"], 40.0)

    def test_overnight_partial_sell_not_closed(self):
        """日初100@10 + 卖50@20 + 剩50现价21 => today_pnl=1050, pct=105.00, 不进closed"""
        anchor = {
            "date": "2026-05-27", "effective_at": "2026-05-27T09:30:00",
            "cash": 100000, "day_start_asset": 101000,
            "total_deposit": 100000, "source": "previous_close",
            "positions": [{"标的": "TEST", "代码": "000001", "数量": 100, "成本": 10, "状态": "持有"}],
            "_meta": {"day_start_prices": {"000001": 10}},
        }
        trades = [{"id": 1, "trade_date": "2026-05-27", "trade_time": "10:00",
                    "action": "卖出", "code": "000001", "name": "TEST",
                    "price": 20, "qty": 50}]
        quotes = {"000001": {"最新价": 21}, "_updated": "2026-05-27T10:30:00"}
        state = reduce_account_state(anchor, trades, quotes, now="2026-05-27T10:30:00")
        pos = state["positions"][0]
        self.assertEqual(pos["today_pnl"], 1050)
        self.assertEqual(pos["today_pnl_pct"], 105.0)
        self.assertEqual(pos["数量"], 50)
        closed_codes = [c["code"] for c in state.get("closed_positions", [])]
        self.assertNotIn("000001", closed_codes, "部分卖出不应进closed_positions")

    def test_overnight_no_day_start_price_returns_none(self):
        """隔夜持仓无day_start_price → today_pnl=None, 不伪算"""
        anchor = {
            "date": "2026-05-27", "effective_at": "2026-05-27T09:30:00",
            "cash": 100000, "day_start_asset": 101000,
            "total_deposit": 100000, "source": "manual_correction",
            "positions": [{"标的": "OLD", "代码": "000002", "数量": 100, "成本": 50, "状态": "持有"}],
            # No _meta / day_start_prices
        }
        trades = []
        quotes = {"000002": {"最新价": 55}, "_updated": "2026-05-27T10:30:00"}
        state = reduce_account_state(anchor, trades, quotes, now="2026-05-27T10:30:00")
        pos = state["positions"][0]
        self.assertIsNone(pos["today_pnl"], f"无day_start_price应返回None, 实为{pos['today_pnl']}")
        self.assertIsNone(pos["today_pnl_pct"])

    def test_new_buy_no_overnight_still_computes(self):
        """纯今日新买（无隔夜）即使无day_start_prices也应计算"""
        anchor = {
            "date": "2026-05-27", "effective_at": "2026-05-27T09:30:00",
            "cash": 100000, "day_start_asset": 100000,
            "total_deposit": 100000, "source": "manual_correction",
            "positions": [],
        }
        trades = [{"id": 1, "trade_date": "2026-05-27", "trade_time": "10:00",
                    "action": "W2买入", "code": "000003", "name": "NEW",
                    "price": 20, "qty": 100}]
        quotes = {"000003": {"最新价": 21}, "_updated": "2026-05-27T10:30:00"}
        state = reduce_account_state(anchor, trades, quotes, now="2026-05-27T10:30:00")
        pos = state["positions"][0]
        self.assertEqual(pos["today_pnl"], 100)
        self.assertEqual(pos["today_pnl_pct"], 5.0)


class ClosedPositionsTest(unittest.TestCase):

    def setUp(self):
        import tempfile, threading
        self.tmp = tempfile.TemporaryDirectory()
        self.original_path = db.DB_PATH
        self.original_local = db._local
        db.DB_PATH = Path(self.tmp.name) / "pnl.db"
        db._local = threading.local()
        db.init_db()

    def tearDown(self):
        conn = getattr(db._local, "conn", None)
        if conn is not None: conn.close()
        db._local = self.original_local
        db.DB_PATH = self.original_path
        self.tmp.cleanup()

    def test_sold_today_appears_in_closed(self):
        db.insert_account_baseline({
            "date": "2026-05-27", "effective_at": "2026-05-27T09:30:00",
            "trade_id_cutoff": 0, "cash": 100187, "day_start_asset": 209786,
            "total_deposit": 200000,
            "positions": [{"标的": "沪电股份", "代码": "002463", "数量": 300, "成本": 122.5, "状态": "持有"}],
            "source": "manual_correction",
        })
        db.insert_trade({
            "trade_date": "2026-05-27", "trade_time": "09:59",
            "action": "卖出", "code": "002463", "name": "沪电股份",
            "price": 131.0, "qty": 300, "reason": "走弱",
        })
        state = reduce_account_state(
            db.query_account_baseline("2026-05-27"),
            db.query_trades(date_from="2026-05-27", date_to="2026-05-27", limit=100),
            {}, now="2026-05-27T10:00:00")
        closed = state.get("closed_positions", [])
        self.assertTrue(any(c["code"] == "002463" for c in closed), f"应有沪电清仓: {closed}")

    def test_partial_sell_not_in_closed(self):
        """部分卖出不进 closed_positions, 仅全部卖清才入"""
        db.insert_account_baseline({
            "date": "2026-05-27", "effective_at": "2026-05-27T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 200000,
            "total_deposit": 100000,
            "positions": [{"标的": "TEST", "代码": "000009", "数量": 100, "成本": 10, "状态": "持有"}],
            "source": "previous_close",
        })
        db.insert_trade({
            "trade_date": "2026-05-27", "trade_time": "10:00",
            "action": "卖出", "code": "000009", "name": "TEST",
            "price": 20, "qty": 50,
        })
        state = reduce_account_state(
            db.query_account_baseline("2026-05-27"),
            db.query_trades(date_from="2026-05-27", date_to="2026-05-27", limit=100),
            {}, now="2026-05-27T10:01:00")
        closed = state.get("closed_positions", [])
        self.assertEqual(len(closed), 0, f"部分卖出不应进closed: {closed}")
        self.assertEqual(state["positions"][0]["数量"], 50)

    def test_overnight_no_day_start_price_fully_sold_realized_none(self):
        """无日初价隔夜仓全部卖出 → closed_positions.realized_today_pnl=None"""
        db.insert_account_baseline({
            "date": "2026-05-27", "effective_at": "2026-05-27T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 200000,
            "total_deposit": 100000,
            "positions": [{"标的": "OLD", "代码": "000010", "数量": 100, "成本": 50, "状态": "持有"}],
            "source": "manual_correction",
            # No _meta → no day_start_prices
        })
        db.insert_trade({
            "trade_date": "2026-05-27", "trade_time": "10:00",
            "action": "卖出", "code": "000010", "name": "OLD",
            "price": 55, "qty": 100,
        })
        state = reduce_account_state(
            db.query_account_baseline("2026-05-27"),
            db.query_trades(date_from="2026-05-27", date_to="2026-05-27", limit=100),
            {}, now="2026-05-27T10:01:00")
        closed = state.get("closed_positions", [])
        self.assertEqual(len(closed), 1)
        self.assertIsNone(closed[0]["realized_today_pnl"],
            f"无日初价清仓收益应为None, 实为{closed[0]['realized_today_pnl']}")

    def test_closed_position_keeps_total_realized_pnl_separate_from_today_pnl(self):
        """清仓展示用总实现盈亏，不得误用相对日初的 today_pnl。"""
        db.insert_account_baseline({
            "date": "2026-05-27", "effective_at": "2026-05-27T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 201200,
            "total_deposit": 100000,
            "positions": [{"标的": "TEST", "代码": "000011", "数量": 100, "成本": 10, "状态": "持有"}],
            "source": "previous_close",
            "_meta": {"day_start_prices": {"000011": 12}},
        })
        db.insert_trade({
            "trade_date": "2026-05-27", "trade_time": "10:00",
            "action": "卖出", "code": "000011", "name": "TEST",
            "price": 11, "qty": 100, "realized_pnl": 100,
        })
        state = reduce_account_state(
            db.query_account_baseline("2026-05-27"),
            db.query_trades(date_from="2026-05-27", date_to="2026-05-27", limit=100),
            {}, now="2026-05-27T10:01:00")
        closed = state.get("closed_positions", [])
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["realized_today_pnl"], -100)
        self.assertEqual(closed[0]["realized_pnl"], 100)

    def test_closed_position_sums_realized_pnl_across_partial_sells(self):
        """分批卖出后清仓时，展示整个持仓周期的累计已实现盈亏。"""
        db.insert_account_baseline({
            "date": "2026-07-22", "effective_at": "2026-07-22T09:25:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 200000,
            "total_deposit": 100000,
            "positions": [{"标的": "紫光股份", "代码": "000938", "数量": 2000,
                           "成本": 38.68, "状态": "持有"}],
            "source": "previous_close",
        })
        for trade_time, price, qty, realized_pnl in [
            ("13:34", 45.61, 500, 3465),
            ("14:38", 45.25, 500, 3285),
            ("14:58", 45.09, 1000, 6410),
        ]:
            db.insert_trade({
                "trade_date": "2026-07-22", "trade_time": trade_time,
                "action": "卖出", "code": "000938", "name": "紫光股份",
                "price": price, "qty": qty, "realized_pnl": realized_pnl,
            })

        state = reduce_account_state(
            db.query_account_baseline("2026-07-22"),
            db.query_trades(date_from="2026-07-22", date_to="2026-07-22", limit=100),
            {}, now="2026-07-22T15:00:00")

        closed = state.get("closed_positions", [])
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["realized_pnl"], 13160)

    def test_closed_position_resets_realized_pnl_after_reopening(self):
        """同日清仓后重新开仓，第二轮清仓不得混入第一轮已实现盈亏。"""
        anchor = {
            "date": "2026-07-22", "effective_at": "2026-07-22T09:25:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 200000,
            "total_deposit": 100000,
            "positions": [{"标的": "TEST", "代码": "000012", "数量": 100,
                           "成本": 10, "状态": "持有"}],
            "source": "previous_close",
        }
        trades = [
            {"id": 1, "trade_date": "2026-07-22", "trade_time": "10:00",
             "action": "卖出", "code": "000012", "name": "TEST",
             "price": 11, "qty": 100, "realized_pnl": 100},
            {"id": 2, "trade_date": "2026-07-22", "trade_time": "10:30",
             "action": "买入", "code": "000012", "name": "TEST",
             "price": 20, "qty": 100},
            {"id": 3, "trade_date": "2026-07-22", "trade_time": "14:00",
             "action": "卖出", "code": "000012", "name": "TEST",
             "price": 20.4, "qty": 50, "realized_pnl": 20},
            {"id": 4, "trade_date": "2026-07-22", "trade_time": "14:30",
             "action": "卖出", "code": "000012", "name": "TEST",
             "price": 21.6, "qty": 50, "realized_pnl": 80},
        ]

        state = reduce_account_state(anchor, trades, {}, now="2026-07-22T15:00:00")

        closed = state.get("closed_positions", [])
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["realized_pnl"], 100)


class SevenDayClosedPositionsTests(unittest.TestCase):
    """YM-W15-02: 7日内清仓来自 SSOT 账本，昨日/6日前可显示，8日前不可"""

    def setUp(self):
        import tempfile, threading
        self.tmp = tempfile.TemporaryDirectory()
        self.original_path = db.DB_PATH
        self.original_local = db._local
        db.DB_PATH = Path(self.tmp.name) / "pnl.db"
        db._local = threading.local()
        db.init_db()

    def tearDown(self):
        conn = getattr(db._local, "conn", None)
        if conn is not None: conn.close()
        db._local = self.original_local
        db.DB_PATH = self.original_path
        self.tmp.cleanup()

    def _make_anchor(self, date_str, positions, source="previous_close"):
        db.insert_account_baseline({
            "date": date_str,
            "effective_at": f"{date_str}T09:30:00",
            "trade_id_cutoff": 0,
            "cash": 100000,
            "day_start_asset": 200000,
            "total_deposit": 100000,
            "positions": positions,
            "source": source,
        })

    def _add_sell(self, date_str, code, name, price, qty):
        db.insert_trade({
            "trade_date": date_str, "trade_time": "10:00",
            "action": "卖出", "code": code, "name": name,
            "price": price, "qty": qty,
        })

    def test_yesterday_close_appears_in_7day(self):
        """昨日清仓出现在7日窗口内"""
        self._make_anchor("2026-05-26",
            [{"标的": "OLD", "代码": "000001", "数量": 100, "成本": 10, "状态": "持有"}])
        self._add_sell("2026-05-26", "000001", "OLD", 20, 100)
        self._make_anchor("2026-05-27", [], source="previous_close")

        from scripts.account_ssot import query_7day_closed_positions
        closed = query_7day_closed_positions("2026-05-27")
        codes = [c["code"] for c in closed]
        self.assertIn("000001", codes, f"昨日清仓应在7日内: {closed}")

    def test_seventh_trading_day_appears_eighth_trading_day_not(self):
        """第7个交易日可显示，第8个交易日不可显示"""
        # 第8个交易日
        self._make_anchor("2026-05-16",
            [{"标的": "OLD8", "代码": "000008", "数量": 100, "成本": 10, "状态": "持有"}])
        self._add_sell("2026-05-16", "000008", "OLD8", 20, 100)
        # 第7个交易日
        self._make_anchor("2026-05-19",
            [{"标的": "OLD7", "代码": "000007", "数量": 100, "成本": 10, "状态": "持有"}])
        self._add_sell("2026-05-19", "000007", "OLD7", 20, 100)
        self._make_anchor("2026-05-27", [], source="previous_close")

        from scripts.account_ssot import query_7day_closed_positions
        closed = query_7day_closed_positions("2026-05-27")
        codes = [c["code"] for c in closed]
        self.assertIn("000007", codes, f"第7个交易日清仓应在窗口内: {closed}")
        self.assertNotIn("000008", codes, f"第8个交易日清仓不应在窗口内: {closed}")

    def test_cross_week_uses_7_trading_days_not_7_calendar_days(self):
        """跨周时周末不占清仓跟踪窗口：6/4 的7个交易日应包含5/27"""
        self._make_anchor("2026-05-27",
            [{"标的": "OLD7", "代码": "000007", "数量": 100, "成本": 10, "状态": "持有"}])
        self._add_sell("2026-05-27", "000007", "OLD7", 20, 100)
        for day in ["2026-05-28", "2026-05-29", "2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]:
            self._make_anchor(day, [], source="previous_close")

        from scripts.account_ssot import query_7day_closed_positions
        closed = query_7day_closed_positions("2026-06-04")
        codes = [c["code"] for c in closed]
        self.assertIn("000007", codes, f"5/27 是第7个交易日，应保留: {closed}")

    def test_partial_sell_not_in_closed(self):
        """部分卖出不出现在清仓跟踪"""
        self._make_anchor("2026-05-26",
            [{"标的": "HALF", "代码": "000010", "数量": 100, "成本": 10, "状态": "持有"}])
        self._add_sell("2026-05-26", "000010", "HALF", 20, 50)  # 只卖一半
        self._make_anchor("2026-05-27", [], source="previous_close")

        from scripts.account_ssot import query_7day_closed_positions
        closed = query_7day_closed_positions("2026-05-27")
        codes = [c["code"] for c in closed]
        self.assertNotIn("000010", codes, f"部分卖出不应在清仓: {closed}")

    def test_correction_chain_not_fake_closed(self):
        """纠错链不伪造成重复清仓"""
        self._make_anchor("2026-05-25",
            [{"标的": "CORR", "代码": "000020", "数量": 100, "成本": 10, "状态": "持有"}])
        # 先卖再纠错买入（net qty 不变）
        db.insert_trade({
            "trade_date": "2026-05-25", "trade_time": "10:00",
            "action": "卖出", "code": "000020", "name": "CORR",
            "price": 20, "qty": 100,
        })
        db.insert_trade({
            "trade_date": "2026-05-25", "trade_time": "10:01",
            "action": "买入", "code": "000020", "name": "CORR",
            "price": 20, "qty": 100, "reason": "纠错：误卖",
        })
        self._make_anchor("2026-05-27", [], source="previous_close")

        from scripts.account_ssot import query_7day_closed_positions
        closed = query_7day_closed_positions("2026-05-27")
        codes = [c["code"] for c in closed]
        self.assertNotIn("000020", codes,
            f"纠错链（卖后买回）不应进清仓: {closed}")

    def test_correction_reversal_excludes_closed(self):
        """昨日误卖，今日 insert_correction_trade 买回 → 不显示清仓"""
        from datetime import datetime as _dt

        class FrozenDatetime(_dt):
            @classmethod
            def now(cls):
                return cls(2026, 5, 27, 10, 0, 0)

        # D-1 (5/26): 持仓100股，误卖全部
        self._make_anchor("2026-05-26",
            [{"标的": "CORRV", "代码": "000031", "数量": 100, "成本": 10, "状态": "持有"}])
        db.insert_trade({
            "trade_date": "2026-05-26", "trade_time": "14:00",
            "action": "卖出", "code": "000031", "name": "CORRV",
            "price": 20, "qty": 100,
        })
        trades_26 = db.query_trades(date_from="2026-05-26", date_to="2026-05-26", limit=10)
        sell_id = trades_26[0]["id"]

        # D日 (5/27): 空仓开盘锚点
        self._make_anchor("2026-05-27", [], source="previous_close")
        # D日调用 insert_correction_trade 买回纠错
        with patch("scripts.db.datetime", FrozenDatetime):
            db.insert_correction_trade(
                original_trade_id=sell_id,
                correction_action="买入",
                correction_price=20, correction_qty=100,
                note="纠错：D-1误卖")

        from scripts.account_ssot import query_7day_closed_positions
        closed = query_7day_closed_positions("2026-05-27")
        codes = [c["code"] for c in closed]
        self.assertNotIn("000031", codes,
            f"is_reversal纠错链应排除清仓: {closed}")

    def test_normal_rebuy_keeps_prior_closed(self):
        """昨日正常卖清，今日普通买入同股 → 仍显示昨日清仓"""
        # D-1 (5/26): 正常卖清
        self._make_anchor("2026-05-26",
            [{"标的": "KEEP", "代码": "000032", "数量": 100, "成本": 10, "状态": "持有"}])
        db.insert_trade({
            "trade_date": "2026-05-26", "trade_time": "14:00",
            "action": "卖出", "code": "000032", "name": "KEEP",
            "price": 20, "qty": 100,
        })
        # D日 (5/27): 空仓开盘，普通买入同股（非纠错，is_reversal=0）
        self._make_anchor("2026-05-27", [], source="previous_close")
        db.insert_trade({
            "trade_date": "2026-05-27", "trade_time": "10:00",
            "action": "W1追涨", "code": "000032", "name": "KEEP",
            "price": 22, "qty": 100,
        })

        from scripts.account_ssot import query_7day_closed_positions
        closed = query_7day_closed_positions("2026-05-27")
        codes = [c["code"] for c in closed]
        self.assertIn("000032", codes,
            f"普通重新买入不得删除此前真实清仓: {closed}")


if __name__ == "__main__":
    unittest.main()
