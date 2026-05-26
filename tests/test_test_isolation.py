"""test_test_isolation.py — 验证测试不污染真实 data/ 目录

HM-G0A 要求：测试运行前后，data/ 无 tracked 变化。

本测试通过两种策略验证隔离：
1. ClosingAnchorIsolationTest：在临时 DB/临时文件上执行写路径，断言使用注入路径。
2. DBPathIsolationTest：断言 scripts.db 的 thread-local 在正常测试运行中，
   若 DB_PATH 被临时替换，后续 db 操作不应意外切回真实 data/pnl.db。
"""
import json
import tempfile
import threading
import unittest
from pathlib import Path

import scripts.db as db


class ClosingAnchorIsolationTest(unittest.TestCase):
    """验证 generate_closing_anchor 使用 injectable pnl_history_path"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_db = Path(self.tmp.name) / "test.db"
        self.tmp_history = Path(self.tmp.name) / "pnl_history.json"
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        db.DB_PATH = self.tmp_db
        db._local = threading.local()
        db.init_db()

    def tearDown(self):
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        self.tmp.cleanup()

    def test_closing_anchor_writes_to_injected_path(self):
        """generate_closing_anchor 接受 pnl_history_path 参数并写入指定位置"""
        from scripts.account_ssot import generate_closing_anchor

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
            "trade_date": "2026-05-26", "trade_time": "09:32",
            "action": "买入", "code": "000001", "name": "测试股",
            "price": 10.0, "qty": 1000,
        })

        self.assertFalse(self.tmp_history.exists(), "tmp_history should not exist before close")

        generate_closing_anchor(
            {"000001": {"最新价": 11.0}},
            now="2026-05-26T15:05:00",
            pnl_history_path=self.tmp_history,
        )

        self.assertTrue(self.tmp_history.exists(), "pnl_history should be written to injected path")
        data = json.loads(self.tmp_history.read_text(encoding="utf-8"))
        self.assertIn("meta", data)
        self.assertIn("closed_date", data["meta"])
        self.assertEqual(data["meta"]["closed_date"], "2026-05-26")


class DBPathIsolationTest(unittest.TestCase):
    """验证 db 模块在正常测试中不会意外操作真实 data/pnl.db"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_db = Path(self.tmp.name) / "isolated.db"
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        db.DB_PATH = self.tmp_db
        db._local = threading.local()
        db.init_db()

    def tearDown(self):
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        self.tmp.cleanup()

    def test_get_conn_returns_temp_db_path(self):
        """get_conn() 返回的连接应指向注入的临时 DB，而非真实 data/pnl.db"""
        conn = db.get_conn()
        rows = conn.execute("PRAGMA database_list").fetchall()
        db_paths = [r[2] for r in rows]
        tmp_path_str = str(self.tmp_db.resolve())
        self.assertTrue(
            any(tmp_path_str in p or p == str(self.tmp_db) for p in db_paths),
            f"get_conn() 应返回临时 DB ({self.tmp_db})，实际: {db_paths}"
        )
        self.assertFalse(
            any("live-dashboard/data/pnl.db" in p for p in db_paths),
            f"get_conn() 不应返回真实 data/pnl.db，实际: {db_paths}"
        )

    def test_query_trades_uses_temp_db(self):
        """query_trades() 在注入临时 DB 时，不操作真实 data/pnl.db"""
        db.insert_trade({
            "trade_date": "2026-05-26",
            "trade_time": "09:32",
            "action": "买入",
            "code": "000001",
            "name": "测试股",
            "price": 10.0,
            "qty": 1000,
        })
        rows = db.query_trades(date_from="2026-05-26")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "000001")

    def test_insert_snapshot_uses_temp_db(self):
        """insert_snapshot() 在注入临时 DB 时，不操作真实 data/pnl.db"""
        db.insert_snapshot({
            "ts": "2026-05-26T10:00:00",
            "date": "2026-05-26",
            "pnl_pct": 1.5,
            "nav": 1.015,
            "sh_pct": 0.5,
            "sz_pct": 0.3,
            "cy_pct": 0.2,
            "pos_pct": 50.0,
            "mv": 50000.0,
            "total_asset": 101500.0,
        })
        rows = db._exec(
            "SELECT ts, pnl_pct, total_asset FROM intraday_snapshots WHERE date = '2026-05-26'",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pnl_pct"], 1.5)

    def test_close_conn_clears_thread_local(self):
        """close_conn() 关闭连接后，get_conn() 应重新创建连接"""
        conn1 = db.get_conn()
        db.close_conn()
        self.assertIsNone(getattr(db._local, "conn", None))
        conn2 = db.get_conn()
        self.assertIsNotNone(getattr(db._local, "conn", None))
        self.assertNotEqual(id(conn1), id(conn2))


if __name__ == "__main__":
    unittest.main()
