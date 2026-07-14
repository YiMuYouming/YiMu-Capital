"""涨跌停日报 v1 契约与 live quotes 接入测试。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.bridge as bridge
from scripts.limitboard_report import load_limitboard_report


class LimitboardReportContractTests(unittest.TestCase):
    def test_loads_valid_v1_report_without_rewriting_source_facts(self):
        payload = {
            "schema_version": "limitboard-report.v1",
            "date": "2026-07-14",
            "generated_at": "2026-07-14T21:30:00+08:00",
            "market_phase": "post_close",
            "summary": {"limit_up": 92, "limit_down": 29, "broken": 21},
            "limit_up_stocks": [
                {"code": "600664", "name": "哈药股份", "board_count": 3,
                 "reason": "业绩预增"},
            ],
            "quality": {
                "status": "degraded",
                "warnings": ["涨停总数存在跨源口径差异"],
            },
            "sources": [{"name": "dashboard_api", "as_of": "2026-07-14T15:06:52+08:00"}],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "latest.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            report = load_limitboard_report(path)

        self.assertEqual("limitboard-report.v1", report["schema_version"])
        self.assertEqual(92, report["summary"]["limit_up"])
        self.assertEqual("600664", report["limit_up_stocks"][0]["code"])
        self.assertEqual("degraded", report["quality"]["status"])

    def test_rejects_non_post_close_or_wrong_schema_report(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "latest.json"
            path.write_text(json.dumps({
                "schema_version": "limitboard-report.v0",
                "date": "2026-07-14",
                "market_phase": "intraday",
                "limit_up_stocks": [],
            }), encoding="utf-8")

            self.assertEqual({}, load_limitboard_report(path))

    def test_live_quotes_exposes_report_as_independent_post_close_layer(self):
        report = {
            "schema_version": "limitboard-report.v1",
            "date": "2026-07-14",
            "market_phase": "post_close",
            "limit_up_stocks": [{"code": "600664", "name": "哈药股份"}],
        }
        original = bridge.CACHE
        bridge.CACHE = {
            "hot_list": {"source": "ths_hot", "zt_stocks": []},
            "limit_up_detail": {"_source": "iwencai_limit_up_detail", "stocks": []},
        }
        try:
            with patch("scripts.bridge.load_latest_limitboard_report", return_value=report):
                payload = bridge._build_live_quotes_payload(rule_state={})
        finally:
            bridge.CACHE = original

        self.assertEqual(report, payload["limitboard_report"])
        self.assertEqual("ths_hot", payload["hot_list"]["source"])


if __name__ == "__main__":
    unittest.main()
