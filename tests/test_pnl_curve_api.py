"""test_pnl_curve_api.py — W22 API 零值/时区/回退 回归"""
import json, os, tempfile, threading, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import scripts.db as db


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
        summary = db.query_pnl_summary()
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
