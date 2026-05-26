import subprocess
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import scripts.bridge as bridge
from scripts.db import query_pnl, query_pnl_summary
from scripts.collectors import quotes


class QuoteCacheGuardTests(unittest.TestCase):
    def setUp(self):
        self.original_cache = quotes.CACHE
        quotes.CACHE = {
            "_stock_codes": ["688981"],
            "live_quotes": {
                "688981": {"最新价": 148.0},
                "_updated": "2026-05-26T10:00:00+08:00",
            },
        }

    def tearDown(self):
        quotes.CACHE = self.original_cache

    def test_empty_pipeline_payload_preserves_last_quotes(self):
        with patch.object(quotes, "_pipeline_fetch", return_value={"_meta": {"source": "pytdx"}}):
            quotes.collect_quotes(force=True)

        self.assertEqual(quotes.CACHE["live_quotes"]["688981"]["最新价"], 148.0)
        self.assertEqual(quotes.CACHE["live_quotes"]["_updated"], "2026-05-26T10:00:00+08:00")

    def test_settled_cash_is_not_reduced_by_existing_buy_again(self):
        self.assertEqual(
            quotes._authoritative_available_cash({"可用资金": 95725}, {"last_total_asset": 210477, "last_mv": 114752}, 83376),
            95725,
        )


class BridgeGuardTests(unittest.TestCase):
    def test_cash_effect_books_only_trade_direction(self):
        self.assertEqual(bridge._trade_cash_effect({"动作": "W1追涨", "价格": 122.5, "数量": 300}), -36750)
        self.assertEqual(bridge._trade_cash_effect({"动作": "卖出", "价格": 147.77, "数量": 200}), 29554)

    def test_missing_timestamp_is_not_reported_live(self):
        result = bridge._add_freshness({}, "live_quote")
        self.assertNotEqual(result["_freshness"]["level"], "live")

    def test_stale_baseline_is_reported_dead(self):
        old = (datetime.now() - timedelta(days=7)).isoformat()
        result = bridge._add_freshness({}, "baseline", old)
        self.assertEqual(result["_freshness"]["level"], "dead")

    def test_position_codes_are_in_live_subscription(self):
        data = {
            "lianban_pool": [],
            "trend_pool": [],
            "decision": {"锚定股状态": []},
            "positions": [{"代码": "688981", "状态": "持有"}],
        }
        self.assertIn("688981", bridge._collect_stock_codes(data))

    def test_generator_script_is_directly_executable(self):
        result = subprocess.run(
            [sys.executable, "scripts/gen_dashboard_data.py", "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_intraday_pnl_summary_exposes_snapshot_timestamp(self):
        result = query_pnl_summary()
        if result["today_snapshots"] > 0:
            self.assertTrue(result.get("_updated"))
            self.assertIn("pnl_amount", result)
            self.assertIn("pnl_pct", result)

    def test_intraday_pnl_chart_exposes_snapshot_timestamp(self):
        if query_pnl_summary()["today_snapshots"] > 0:
            self.assertTrue(query_pnl("today", "sh").get("_updated"))

    def test_intraday_chart_includes_latest_lunch_correction(self):
        summary = query_pnl_summary()
        chart = query_pnl("today", "sh")
        latest = next((v for v in reversed(chart["portfolio"]) if v is not None), None)
        if summary["_updated"] and "T11:" in summary["_updated"]:
            self.assertEqual(latest, summary["pnl_pct"])


if __name__ == "__main__":
    unittest.main()
