import json
import unittest
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import scripts.bridge as bridge
import scripts.db as db
from scripts.collectors import quotes

try:
    from scripts.account_ssot import ensure_today_anchor, load_current_account_state, reduce_account_state
except ImportError:
    ensure_today_anchor = None
    load_current_account_state = None
    reduce_account_state = None


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
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
        db.DB_PATH = self.original_path
        db._local = self.original_local
        self.tmp.cleanup()

    def test_first_anchor_is_locked_and_reused(self):
        self.assertIsNotNone(ensure_today_anchor)
        data = {"pnl": {"可用资金": 125279, "累计入金": 200000}, "positions": self._positions(300)}
        first = ensure_today_anchor(
            data,
            day_start_asset=210477,
            now="2026-05-26T11:37:10",
            get_anchor=db.query_account_baseline,
            insert_anchor=db.insert_account_baseline,
        )
        changed = {"pnl": {"可用资金": 0}, "positions": self._positions(0)}
        second = ensure_today_anchor(
            changed,
            day_start_asset=1,
            now="2026-05-26T12:00:00",
            get_anchor=db.query_account_baseline,
            insert_anchor=db.insert_account_baseline,
        )
        self.assertEqual(first["cash"], 125279)
        self.assertEqual(second["cash"], 125279)
        self.assertEqual(second["positions"][0]["数量"], 300)
        self.assertEqual(second["effective_at"], "2026-05-26T11:37:10")

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
        self.assertEqual(state["cash"], 113029)
        self.assertEqual({p["代码"]: p["数量"] for p in state["positions"]}, {"688981": 300, "002463": 100})
        self.assertEqual([trade["id"] for trade in state["trades"]], [2, 1])
        self.assertEqual(state["_updated"], "2026-05-26T13:02:00")

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
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
        db.DB_PATH = self.original_path
        db._local = self.original_local
        self.tmp.cleanup()

    def test_closing_anchor_generates_next_day_previous_close_anchor(self):
        from scripts.account_ssot import generate_closing_anchor, query_previous_close_anchor

        # 1. 先建今日锚点 + 一笔买入
        dashboard_path = Path(self.tmp.name) / "dashboard_data.json"
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
        result = generate_closing_anchor(
            {"002463": {"最新价": 105.0}, "_updated": "2026-05-26T15:00:00"},
            now="2026-05-26T15:05:00",
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
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
        db.DB_PATH = self.original_path
        db._local = self.original_local
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
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
        db.DB_PATH = self.original_path
        db._local = self.original_local
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
        result = generate_closing_anchor(
            {"000001": {"最新价": 42.5}, "_updated": "2026-05-26T15:00:00"},
            now="2026-05-26T15:05:00",
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


if __name__ == "__main__":
    unittest.main()
