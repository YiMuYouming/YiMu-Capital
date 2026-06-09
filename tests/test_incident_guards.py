import subprocess
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import scripts.bridge as bridge
import scripts.style_detect as style_detect
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
            with patch.object(bridge, "query_trades", return_value=[
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

    def test_style_dim1_uses_review_market_volume_when_iwencai_empty(self):
        with patch.object(style_detect, "q", return_value={"fields": [], "datas": []}):
            result = style_detect.score_dim1({"市场量能": 3.24})

        self.assertEqual(result["details"]["全市场成交额"], "32400亿")
        self.assertEqual(result["details"]["成交额评分"], "8/8")
        self.assertEqual(result["score"], 17)

    def test_style_review_score_validation_overrides_algorithm_scores(self):
        s1 = {"score": 17, "details": {}, "max": 25}
        s2 = {"score": 9, "details": {}, "max": 35}
        s3 = {"score": 12, "details": {}, "max": 25}
        s4 = {"score": 7, "details": {}, "max": 15}

        style_detect.apply_review_score_validation({
            "风格分数验证": "42分(维度一17+维度二9+维度三9+维度四7)"
        }, s1, s2, s3, s4)

        self.assertEqual([s1["score"], s2["score"], s3["score"], s4["score"]], [17, 9, 9, 7])
        self.assertEqual(s3["details"]["复盘校验"], "12→9")

    def test_style_allocation_uses_vault_interpolation_table(self):
        self.assertEqual(
            style_detect.compute_allocation(42),
            {"连板资金占比": 12, "趋势资金占比": 88},
        )

    def test_style_dim2_parses_risk_value_with_text_suffix(self):
        with patch.object(style_detect, "q", return_value={"fields": [], "datas": []}):
            result = style_detect.score_dim2({
                "最高板": 3,
                "昨日涨停收益": 1.03,
                "昨日炸板收益": -2.73,
                "连板风险值": "0.5高",
                "整体晋级率": 17.39,
            })

        self.assertEqual(result["details"]["连板风险值"], "0.5")

    def test_style_regime_days_deduplicates_same_date(self):
        state = {
            "current_regime": "混合（偏趋势）",
            "days_in_regime": 11,
            "history": [
                {"date": "2026-05-18", "style": "混合（偏连板）", "total": 48},
                {"date": "2026-05-19", "style": "混合（均衡）", "total": 54},
                {"date": "2026-05-19", "style": "混合（均衡）", "total": 55},
                {"date": "2026-05-26", "style": "混合（均衡）", "total": 59},
                {"date": "2026-05-27", "style": "混合（偏趋势）", "total": 43},
                {"date": "2026-05-27", "style": "混合（偏趋势）", "total": 45},
            ],
        }
        saved = {}
        dims = (
            {"score": 17, "max": 25},
            {"score": 9, "max": 35},
            {"score": 9, "max": 25},
            {"score": 7, "max": 15},
        )

        with patch.object(style_detect, "_load_regime_state", return_value=state), \
             patch.object(style_detect, "_save_regime_state", side_effect=lambda s: saved.update(s)):
            result = style_detect.determine_style(*dims, date_str="2026-05-27")

        dates = [item["date"] for item in saved["history"]]
        self.assertEqual(dates.count("2026-05-27"), 1)
        self.assertEqual(result["days_in_regime"], 4)

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
