import subprocess
import sys
import sqlite3
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import scripts.bridge as bridge
import scripts.style_detect as style_detect
from scripts.db import query_pnl, query_pnl_summary
from scripts.collectors import quotes


def _query_pnl_summary_or_skip():
    try:
        return query_pnl_summary()
    except sqlite3.OperationalError as exc:
        raise unittest.SkipTest(f"local pnl.db unavailable: {exc}") from exc


def _query_pnl_or_skip(*args):
    try:
        return query_pnl(*args)
    except sqlite3.OperationalError as exc:
        raise unittest.SkipTest(f"local pnl.db unavailable: {exc}") from exc


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

    def test_today_trade_codes_are_in_runtime_live_subscription(self):
        data = {
            "lianban_pool": [],
            "trend_pool": [],
            "decision": {"锚定股状态": []},
            "positions": [{"代码": "002281", "状态": "持有"}],
        }
        with patch.object(bridge, "query_trades", return_value=[
            {"trade_date": "2026-06-09", "code": "688017", "name": "绿的谐波"},
        ]):
            codes = bridge._collect_runtime_stock_codes(data, today="2026-06-09")

        self.assertIn("002281", codes)
        self.assertIn("688017", codes)

    def test_runtime_live_subscription_filters_non_stock_codes(self):
        data = {
            "lianban_pool": [{"代码": "中芯国际"}, {"代码": "002049"}],
            "trend_pool": [{"代码": "~~300037~~"}],
            "decision": {"锚定股状态": [{"代码": "寒武纪"}]},
            "positions": [{"代码": "002409", "状态": "持有"}],
        }
        with patch("scripts.db.query_account_baseline", return_value={
            "positions": [{"代码": "603011", "数量": 100}, {"代码": "合锻智能", "数量": 100}],
        }), patch.object(bridge, "query_trades", return_value=[
            {"trade_date": "2026-06-22", "code": "002056", "name": "横店东磁"},
            {"trade_date": "2026-06-22", "code": "manual_backfill", "name": "坏值"},
        ]), patch.object(bridge, "query_7day_closed_positions", return_value=[
            {"code": "002261"}, {"code": "拓维信息"},
        ]):
            codes = bridge._collect_runtime_stock_codes(data, today="2026-06-22")

        self.assertEqual(codes, ["002049", "002056", "002261", "002409", "603011"])

    def test_runtime_live_subscription_repairs_shifted_pool_columns(self):
        data = {
            "lianban_pool": [],
            "trend_pool": [
                {"标的": "🟢温度标", "代码": "国瓷材料", "板块": "300285", "今日定位": "电子化学品", "窗口": "温度标"},
                {"标的": "🟡趋势参考", "代码": "中际旭创", "板块": "300308", "今日定位": "CPO", "窗口": "参考"},
            ],
            "decision": {"锚定股状态": []},
            "positions": [],
        }
        with patch("scripts.db.query_account_baseline", return_value=None), \
             patch.object(bridge, "query_trades", return_value=[]), \
             patch.object(bridge, "query_7day_closed_positions", return_value=[]):
            codes = bridge._collect_runtime_stock_codes(data, today="2026-06-22")

        self.assertEqual(codes, ["300285", "300308"])

    def test_baseline_payload_repairs_shifted_pool_columns(self):
        orig_data = bridge.DATA_FILE
        orig_cache = dict(bridge.CACHE)
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            try:
                bridge.DATA_FILE = Path(tmp) / "dashboard_data.json"
                bridge.DATA_FILE.write_text(json.dumps({
                    "meta": {"date": "2026-06-22", "updated": "2026-06-22T09:00:00+08:00"},
                    "lianban_pool": [],
                    "trend_pool": [
                        {"标的": "🟢温度标", "代码": "国瓷材料", "板块": "300285", "今日定位": "电子化学品", "窗口": "温度标"}
                    ],
                    "positions": [],
                    "risk": {},
                }, ensure_ascii=False))
                bridge.CACHE.clear()
                bridge.CACHE["live_quotes"] = {
                    "300285": {"最新价": 101.0, "涨幅": "+1.23%", "量比": "1.1"},
                    "_updated": "2026-06-22T09:30:00+08:00",
                }
                with patch("scripts.db.query_account_baseline", return_value=None), \
                     patch.object(bridge, "query_trades", return_value=[]), \
                     patch.object(bridge, "query_7day_closed_positions", return_value=[]), \
                     patch.object(bridge, "_build_rule_inputs", return_value={"risk": {}}):
                    result = bridge._baseline_payload(now=datetime(2026, 6, 22, 9, 35))
            finally:
                bridge.DATA_FILE = orig_data
                bridge.CACHE.clear()
                bridge.CACHE.update(orig_cache)

        row = result["trend_pool"][0]
        self.assertEqual(row.get("标的"), "国瓷材料")
        self.assertEqual(row.get("代码"), "300285")
        self.assertEqual(row.get("板块"), "电子化学品")

    def test_quote_coverage_counts_runtime_trade_codes(self):
        orig_data = bridge.DATA_FILE
        orig_cache = dict(bridge.CACHE)
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            bridge.DATA_FILE = Path(tmp) / "dashboard_data.json"
            bridge.DATA_FILE.write_text(json.dumps({
                "lianban_pool": [],
                "trend_pool": [],
                "decision": {"锚定股状态": []},
                "positions": [{"代码": "002281", "标的": "光迅科技"}],
            }))
            bridge.CACHE.clear()
            bridge.CACHE["live_quotes"] = {
                "002281": {"最新价": 203.2},
                "688017": {"最新价": 422.0},
                "_updated": "2026-06-09T10:30:00+08:00",
            }
            with patch("scripts.db.query_account_baseline", return_value=None), \
                 patch.object(bridge, "query_7day_closed_positions", return_value=[]), \
                 patch.object(bridge, "query_trades", return_value=[
                {"trade_date": "2026-06-09", "code": "688017", "name": "绿的谐波"},
            ]):
                covered, total, missing = bridge._quotes_coverage(today="2026-06-09")
        bridge.DATA_FILE = orig_data
        bridge.CACHE.clear()
        bridge.CACHE.update(orig_cache)

        self.assertEqual((covered, total, missing), (2, 2, []))

    def test_generator_script_is_directly_executable(self):
        result = subprocess.run(
            [sys.executable, "scripts/gen_dashboard_data.py", "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_style_adapter_accepts_only_canonical_three_dimension_contract(self):
        report = {
            "schema_version": "review-style-detect.v1",
            "status": "ready",
            "formula_version": "piecewise_linear_v1",
            "dimension_weights": {"量能": 30, "连板生态": 40, "趋势赚钱效应": 30},
            "total_score": 73,
            "allocation": {"连板资金占比": 77.333333, "趋势资金占比": 22.666667},
            "source_gaps": [],
        }
        self.assertEqual(style_detect.validate_canonical(report), [])

    def test_style_adapter_rejects_legacy_four_dimension_contract(self):
        report = {
            "schema_version": "review-style-detect.v1",
            "status": "ready",
            "formula_version": "piecewise_linear_v1",
            "dimension_weights": {"量能": 25, "连板生态": 35, "趋势赚钱效应": 25, "情绪广度": 15},
            "total_score": 73,
            "allocation": {"连板资金占比": 52, "趋势资金占比": 48},
            "source_gaps": [],
        }
        self.assertIn("dimension_weights must be 30/40/30", style_detect.validate_canonical(report))

    def test_intraday_pnl_summary_exposes_snapshot_timestamp(self):
        result = _query_pnl_summary_or_skip()
        if result["today_snapshots"] > 0:
            self.assertTrue(result.get("_updated"))
            self.assertIn("pnl_amount", result)
            self.assertIn("pnl_pct", result)

    def test_intraday_pnl_chart_exposes_snapshot_timestamp(self):
        if _query_pnl_summary_or_skip()["today_snapshots"] > 0:
            self.assertTrue(_query_pnl_or_skip("today", "sh").get("_updated"))

    def test_intraday_chart_includes_latest_lunch_correction(self):
        summary = _query_pnl_summary_or_skip()
        chart = _query_pnl_or_skip("today", "sh")
        latest = next((v for v in reversed(chart["portfolio"]) if v is not None), None)
        if summary["_updated"] and "T11:" in summary["_updated"]:
            self.assertEqual(latest, summary["pnl_pct"])


if __name__ == "__main__":
    unittest.main()
