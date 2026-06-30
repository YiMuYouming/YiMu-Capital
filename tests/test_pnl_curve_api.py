"""test_pnl_curve_api.py — W22 API 零值/时区/回退 回归"""
import json, os, tempfile, threading, unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import scripts.db as db
import scripts.bridge as bridge


class PnlQueryZeroValueTests(unittest.TestCase):
    """query_pnl_summary / query_pnl 对零值的处理"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig_path = db.DB_PATH; self.orig_local = db._local
        db.DB_PATH = Path(self.tmp.name) / "test.db"
        db._local = threading.local()
        db.init_db()

    def tearDown(self):
        conn = getattr(db._local, "conn", None)
        if conn is not None: conn.close()
        db._local = self.orig_local
        db.DB_PATH = self.orig_path
        self.tmp.cleanup()

    def _insert_snapshot(self, ts, total_asset, mv, pnl_pct=0.0):
        db._exec_write(
            "INSERT INTO intraday_snapshots (ts,date,total_asset,mv,pnl_pct,nav,sh_pct,sz_pct,cy_pct,pos_pct) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ts, ts[:10], total_asset, mv, pnl_pct, 1.0, 0.0, 0.0, 0.0, 0.0))

    def _insert_daily(self, date_str, nav=1.0, deposit=100000):
        db._exec_write(
            "INSERT INTO daily_summary (date,nav,pnl_pct,sh_pct,sz_pct,cy_pct,pos_pct,deposit) VALUES (?,?,?,?,?,?,?,?)",
            (date_str, nav, 0.0, 0.0, 0.0, 0.0, 0.0, deposit))

    def test_total_asset_zero_preserved_in_summary(self):
        """total_asset=0 在 query_pnl_summary 中保留为 0，不回退旧值"""
        today = "2026-05-27"
        self._insert_daily("2026-05-26", nav=1.05, deposit=100000)  # last=105000
        self._insert_snapshot(f"{today}T09:30:00", 0, 0, 0.0)
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls):
                return cls(2026, 5, 27, 10, 0, 0)
        original_datetime = db.datetime
        db.datetime = FrozenDatetime
        try:
            summary = db.query_pnl_summary()
        finally:
            db.datetime = original_datetime
        self.assertEqual(summary["total_asset"], 0,
            f"total_asset=0 应保留, 实为 {summary['total_asset']}")
        self.assertEqual(summary["mv"], 0,
            f"mv=0 应保留, 实为 {summary['mv']}")

    def test_query_pnl_today_with_timezone_ts(self):
        """带 +08:00 时区的时间戳正确映射到 HH:MM 槽"""
        today = "2026-05-27"
        self._insert_snapshot(f"{today}T10:00:00+08:00", 200000, 100000, 0.5)
        result = db.query_pnl("today", "sh")
        self.assertIn("10:00", result.get("labels", []),
            f"带时区ts应映射到10:00: {result.get('labels', [])[:5]}")
        idx = result["labels"].index("10:00")
        self.assertEqual(result["portfolio"][idx], 0.5,
            f"10:00槽应有pnl_pct=0.5, 实为{result['portfolio'][idx]}")

    def test_query_pnl_fallback_has_date_and_flag(self):
        """无今日快照回退上一交易日时，返回 data_date 和 is_fallback=true"""
        today = "2026-05-27"
        self._insert_snapshot("2026-05-26T14:55:00", 200000, 100000, 1.0)
        result = db.query_pnl("today", "sh")
        self.assertTrue(result.get("is_fallback"),
            f"无今日数据应标记 is_fallback: {result}")
        self.assertEqual(result.get("data_date"), "2026-05-26",
            f"data_date 应为回退日期: {result}")

    def test_query_pnl_ignores_non_trading_day_intraday_rows(self):
        """非交易日即使误写 intraday，也应回退上一交易日曲线。"""
        self._insert_snapshot("2026-06-05T14:55:00", 720227.67, 136548.0, -0.51)
        self._insert_snapshot("2026-06-06T09:55:27", 999999.0, 999999.0, 9.99)
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls):
                return cls(2026, 6, 6, 10, 0, 0)
        original_datetime = db.datetime
        db.datetime = FrozenDatetime
        try:
            result = db.query_pnl("today", "sh")
        finally:
            db.datetime = original_datetime
        self.assertTrue(result.get("is_fallback"), result)
        self.assertEqual(result.get("data_date"), "2026-06-05", result)
        self.assertNotIn(9.99, result.get("portfolio", []), result)

    def test_summary_non_trading_day_uses_last_intraday_close_snapshot(self):
        """周末/非交易日 summary 停留在上一交易日最后一条 intraday 快照。"""
        self._insert_daily("2026-06-05", nav=1.012894, deposit=711059.2252961266)
        self._insert_snapshot("2026-06-05T16:07:58", 720227.67, 136548.0, -0.51)
        self._insert_snapshot("2026-06-06T09:55:27", 999999.0, 999999.0, 9.99)
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls):
                return cls(2026, 6, 6, 9, 45, 0)
        original_datetime = db.datetime
        db.datetime = FrozenDatetime
        try:
            summary = db.query_pnl_summary()
        finally:
            db.datetime = original_datetime
        self.assertEqual(summary["last_date"], "2026-06-05")
        self.assertEqual(summary["today_snapshots"], 0)
        self.assertEqual(summary["total_asset"], 720227.67)
        self.assertEqual(summary["mv"], 136548.0)
        self.assertEqual(summary["pnl_pct"], -0.51)
        self.assertEqual(summary["_updated"], "2026-06-05T16:07:58")

    def test_query_pnl_future_null_slots(self):
        """未到时间的槽位为 null，不崩溃"""
        today = "2026-05-27"
        self._insert_snapshot(f"{today}T09:30:00", 200000, 100000, 0.0)
        result = db.query_pnl("today", "sh")
        labels = result.get("labels", [])
        # 找到 09:30 的索引，之后到收盘前应该是 null
        idx_0930 = labels.index("09:30") if "09:30" in labels else 0
        # 最后一个数据之后的槽是 null
        last_data_idx = None
        for i in range(len(labels)):
            if result["portfolio"][i] is not None:
                last_data_idx = i
        if last_data_idx is not None and last_data_idx + 1 < len(labels):
            self.assertIsNone(result["portfolio"][last_data_idx + 1],
                "最后一个数据点之后应为 null")

    def test_query_pnl_all_uses_nav_derived_returns(self):
        """累计曲线原始日收益应从 nav 推导，不能被旧 pnl_pct 脏值带偏"""
        db._exec_write(
            "INSERT INTO daily_summary (date,nav,pnl_pct,sh_pct,sz_pct,cy_pct,pos_pct,deposit) VALUES (?,?,?,?,?,?,?,?)",
            ("2026-03-30", 1.0, 10.0, 0.0, 0.0, 0.0, 0.0, 200000))
        db._exec_write(
            "INSERT INTO daily_summary (date,nav,pnl_pct,sh_pct,sz_pct,cy_pct,pos_pct,deposit) VALUES (?,?,?,?,?,?,?,?)",
            ("2026-03-31", 1.05, -99.0, 0.0, 0.0, 0.0, 0.0, 200000))
        result = db.query_pnl("all", "sh")
        self.assertEqual(result["portfolio"][0], 0.0, result)
        self.assertAlmostEqual(result["portfolio"][1], 5.0, places=4)

    def test_query_pnl_week_uses_previous_nav_for_first_window_day(self):
        """week=最近5个交易日收益，第一天也要用窗口前一日 nav 计算"""
        rows = [
            ("2026-06-12", 1.00, 0),
            ("2026-06-15", 1.01, 10),
            ("2026-06-16", 1.03, 20),
            ("2026-06-17", 1.02, 30),
            ("2026-06-18", 1.05, 40),
            ("2026-06-19", 1.14, 50),
        ]
        for date_str, nav, pos in rows:
            db._exec_write(
                "INSERT INTO daily_summary (date,nav,pnl_pct,sh_pct,sz_pct,cy_pct,pos_pct,deposit) VALUES (?,?,?,?,?,?,?,?)",
                (date_str, nav, 0.0, 0.0, 0.0, 0.0, pos, 200000))
        result = db.query_pnl("week", "sh")
        self.assertEqual(result["dates"], [r[0] for r in rows[-5:]], result)
        self.assertEqual(result["position"], [10, 20, 30, 40, 50], result)
        self.assertAlmostEqual(result["portfolio"][-1], 14.0, places=3, msg=result)

    def test_query_pnl_month_returns_window_rebased_twr_not_inception_slice(self):
        """月图展示近一月TWR，应按窗口内日收益复合，不能截取全历史累计曲线"""
        rows = [
            ("2026-05-25", 1.052385, 0.96),
            ("2026-05-26", 1.04893, -0.17),
            ("2026-05-27", 1.033765, 0.0),
        ]
        for date_str, nav, sh_pct in rows:
            db._exec_write(
                "INSERT INTO daily_summary (date,nav,pnl_pct,sh_pct,sz_pct,cy_pct,pos_pct,deposit) VALUES (?,?,?,?,?,?,?,?)",
                (date_str, nav, 0.0, sh_pct, 0.0, 0.0, 30, 200000))

        result = db.query_pnl("month", "sh")

        self.assertEqual(result["dates"][-2:], ["2026-05-26", "2026-05-27"], result)
        self.assertAlmostEqual(result["portfolio"][0], 0.0, places=4, msg=result)
        self.assertAlmostEqual(result["portfolio"][-2], -0.3283, places=3, msg=result)
        self.assertAlmostEqual(result["portfolio"][-1], -1.7694, places=3, msg=result)
        self.assertAlmostEqual(result["benchmark"][-1], 0.7884, places=3, msg=result)

    def test_query_pnl_all_overlays_today_benchmark_from_intraday(self):
        """日结 daily_summary 若今天指数为 0，应以最后一条日内快照补齐"""
        today = datetime.now().strftime("%Y-%m-%d")
        db._exec_write(
            "INSERT INTO daily_summary (date,nav,pnl_pct,sh_pct,sz_pct,cy_pct,pos_pct,deposit) VALUES (?,?,?,?,?,?,?,?)",
            (today, 1.02, 2.0, 0.0, 0.0, 0.0, 30.0, 200000))
        db._exec_write(
            "INSERT INTO intraday_snapshots (ts,date,total_asset,mv,pnl_pct,nav,sh_pct,sz_pct,cy_pct,pos_pct) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"{today}T14:55:00", today, 204000, 60000, 2.0, 1.02, -1.25, -0.8, -0.3, 30.0))
        result = db.query_pnl("all", "sh")
        self.assertEqual(result["dates"][-1], today)
        self.assertEqual(result["benchmark"][-1], -1.25)

    def test_query_pnl_week_overlays_zero_historical_benchmark_from_intraday(self):
        """周线指数参考不能因 daily_summary 历史指数为 0 而画成平线。"""
        rows = [
            ("2026-06-23", 0.9938, 1.00, 2.00),
            ("2026-06-24", 1.029445, -0.50, -1.00),
            ("2026-06-25", 1.049853, 0.20, 0.80),
            ("2026-06-26", 1.035207, -0.30, -0.60),
            ("2026-06-29", 1.055575, 0.19, 0.54),
        ]
        for date_str, nav, sz_pct, cy_pct in rows:
            db._exec_write(
                "INSERT INTO daily_summary (date,nav,pnl_pct,sh_pct,sz_pct,cy_pct,pos_pct,deposit) VALUES (?,?,?,?,?,?,?,?)",
                (date_str, nav, 0.0, 0.0, 0.0, 0.0, 30.0, 200000))
            db._exec_write(
                "INSERT INTO intraday_snapshots (ts,date,total_asset,mv,pnl_pct,nav,sh_pct,sz_pct,cy_pct,pos_pct) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"{date_str}T14:55:00", date_str, nav * 200000, 60000, 0.0, nav, 0.0, sz_pct, cy_pct, 30.0))
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls):
                return cls(2026, 6, 29, 16, 0, 0)
        original_datetime = db.datetime
        db.datetime = FrozenDatetime
        try:
            sz_result = db.query_pnl("week", "sz")
            cy_result = db.query_pnl("week", "cy")
        finally:
            db.datetime = original_datetime

        self.assertEqual(sz_result["dates"], [r[0] for r in rows], sz_result)
        self.assertNotEqual(len(set(sz_result["benchmark"][:-1])), 1, sz_result)
        self.assertNotEqual(len(set(cy_result["benchmark"][:-1])), 1, cy_result)
        self.assertAlmostEqual(sz_result["benchmark"][0], 1.0, places=4, msg=sz_result)
        self.assertAlmostEqual(cy_result["benchmark"][0], 2.0, places=4, msg=cy_result)

    def test_bridge_overlays_live_today_point_when_snapshots_are_missing(self):
        """今日快照缺失但 SSOT 有今日状态时，/api/pnl 可叠加临时实时点。"""
        chart = {
            "type": "intraday",
            "data_date": "2026-06-19",
            "is_fallback": True,
            "labels": ["09:30", "09:35", "09:40", "09:45"],
            "portfolio": [0.0, 0.0, -0.73, None],
            "benchmark": [0.0, 0.0, -0.43, None],
            "position": [42.0, 42.0, 42.0, None],
            "nav": [1.0, 1.0, 0.9927, None],
            "_updated": "2026-06-19T14:55:00",
        }
        summary = {
            "pnl_pct": -0.14,
            "pos_pct": 32.6,
            "total_asset": 713097.47,
            "total_deposit": 711059.2252961266,
            "valuation_complete": False,
            "_updated": "2026-06-22T09:42:37+08:00",
        }
        live_index = {"上证指数涨幅": "+0.11%"}

        result = bridge._overlay_live_today_pnl_point(
            chart, summary, "today", "sh", live_index=live_index,
            now=datetime(2026, 6, 22, 9, 44, 0),
        )

        self.assertFalse(result.get("is_fallback"), result)
        self.assertTrue(result.get("is_live_overlay"), result)
        self.assertEqual(result.get("data_date"), "2026-06-22", result)
        idx = result["labels"].index("09:40")
        self.assertEqual(result["portfolio"][idx], -0.14, result)
        self.assertEqual(result["position"][idx], 32.6, result)
        self.assertEqual(result["benchmark"][idx], 0.11, result)
        self.assertIsNone(result["portfolio"][idx + 1], result)
        self.assertFalse(result.get("valuation_complete"), result)

    def test_bridge_overlays_today_trade_ledger_when_quotes_are_stale(self):
        """行情旧但今日成交已入账时，曲线展示今日账本临时点并保持估值不可信。"""
        chart = {
            "type": "intraday",
            "data_date": "2026-06-19",
            "is_fallback": True,
            "labels": ["09:30", "09:35", "09:40", "09:45"],
            "portfolio": [0.0, 0.0, 0.0, None],
            "benchmark": [0.0, 0.0, -0.43, None],
            "position": [42.0, 42.0, 42.0, None],
            "nav": [1.0, 1.0, 1.0, None],
            "_updated": "2026-06-19T14:55:00",
        }
        summary = {
            "pnl_pct": -0.14,
            "pos_pct": 32.6,
            "total_asset": 713097.47,
            "total_deposit": 711059.2252961266,
            "valuation_complete": False,
            "quote_status": "stale",
            "_updated": "2026-06-21T21:10:55+08:00",
            "trades": [
                {"trade_date": "2026-06-22", "trade_time": "09:41", "created_at": "2026-06-22 09:42:37"}
            ],
        }

        result = bridge._overlay_live_today_pnl_point(
            chart, summary, "today", "sh", now=datetime(2026, 6, 22, 9, 44, 0),
        )

        self.assertEqual(result.get("data_date"), "2026-06-22", result)
        self.assertTrue(result.get("is_live_overlay"), result)
        self.assertEqual(result.get("overlay_source"), "account_trade_ledger", result)
        self.assertEqual(result.get("_updated"), "2026-06-22T09:42:37", result)
        self.assertFalse(result.get("valuation_complete"), result)
        self.assertEqual(result.get("quote_status"), "stale", result)

    def test_bridge_keeps_non_trading_fallback_without_live_overlay(self):
        """非今日 SSOT 更新时间不得把周末/盘前回退伪装成实时今日。"""
        chart = {
            "type": "intraday",
            "data_date": "2026-06-19",
            "is_fallback": True,
            "labels": ["09:30"],
            "portfolio": [-0.73],
            "benchmark": [-0.43],
            "position": [42.0],
            "nav": [0.9927],
            "_updated": "2026-06-19T14:55:00",
        }
        result = bridge._overlay_live_today_pnl_point(
            chart, {"pnl_pct": 0, "_updated": "2026-06-19T15:00:00"},
            "today", "sh", now=datetime(2026, 6, 22, 9, 44, 0),
        )
        self.assertTrue(result.get("is_fallback"), result)
        self.assertEqual(result.get("data_date"), "2026-06-19", result)


class PnlQueryZeroValueFileBasedTests(unittest.TestCase):
    """测试 query_pnl_summary 在没有数据库快照时的回退逻辑零值保护"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig_path = db.DB_PATH; self.orig_local = db._local
        db.DB_PATH = Path(self.tmp.name) / "test.db"
        db._local = threading.local()
        db.init_db()

    def tearDown(self):
        conn = getattr(db._local, "conn", None)
        if conn is not None: conn.close()
        db._local = self.orig_local
        db.DB_PATH = self.orig_path
        self.tmp.cleanup()

    def test_no_intraday_falls_back_to_last_daily(self):
        """无日内快照时回退到 daily_summary 最新记录"""
        db._exec_write(
            "INSERT INTO daily_summary (date,nav,pnl_pct,sh_pct,sz_pct,cy_pct,pos_pct,deposit) VALUES (?,?,?,?,?,?,?,?)",
            ("2026-05-26", 1.05, 5.0, 0.0, 0.0, 0.0, 80.0, 200000))
        summary = db.query_pnl_summary()
        # last nav=1.05, deposit=200000 → total_asset=210000
        self.assertIsNotNone(summary["total_asset"])
        self.assertEqual(summary["today_snapshots"], 0)


if __name__ == "__main__":
    unittest.main()
