import json
import tempfile
import unittest
from pathlib import Path


class ReviewSourcePacketTests(unittest.TestCase):
    def _sample_ai_context(self, quote_status="stale"):
        return {
            "schema_version": "ai_context.v1",
            "generated_at": "2026-06-19T15:10:00+08:00",
            "date": "2026-06-19",
            "mode": "closed",
            "situation": {
                "trade_entry_allowed": False,
                "trade_entry_reason": "quotes stale",
                "pnl": {
                    "total_asset": 714117.47,
                    "pnl_amount": 0,
                    "pnl_pct": 0.0,
                    "valuation_complete": True,
                },
                "position": {
                    "pos_pct": 42.5,
                    "position_count": 1,
                    "sellable_count": 0,
                },
            },
            "freshness": {
                "quotes": {"status": quote_status, "detail": "too old"},
                "account": {"status": "ok", "quote_status": "close_snapshot"},
            },
            "risks": [{"code": "QUOTE_STALE", "title": "行情过期"}],
            "human_required": [{"code": "TRADE_BLOCKED", "title": "交易阻断"}],
            "tickets": {"status": "ok", "total": 2, "completed": 1, "blocked": 1},
            "positions": [{
                "代码": "002409",
                "标的": "雅克科技",
                "数量": 800,
                "成本": 141.41,
                "现价": 150.16,
                "sellable_qty": 0,
                "today_pnl": 7000,
            }],
        }

    def test_build_packet_has_stable_contract_and_preserves_stale_status(self):
        from scripts.ops.generate_review_source_packet import build_review_source_packet

        packet = build_review_source_packet(
            date_str="2026-06-19",
            ai_context=self._sample_ai_context("stale"),
            pnl_summary={"total_asset": 714117.47, "pnl_pct": 0.0},
            trades=[{"id": 1, "code": "002409", "name": "雅克科技", "action": "买入"}],
            tickets={"status": "ok", "total": 2},
            now="2026-06-19T15:30:00+08:00",
        )

        for key in [
            "schema_version", "date", "generated_at", "source_status",
            "ai_context", "account", "positions", "trades", "tickets",
            "pnl", "review_hints", "manual_required",
        ]:
            self.assertIn(key, packet)
        self.assertEqual(packet["schema_version"], "review_source_packet.v1")
        self.assertEqual(packet["source_status"]["ai_context"], "ok")
        self.assertEqual(packet["source_status"]["freshness"]["quotes"], "stale")
        manual_codes = [item["code"] for item in packet["manual_required"]]
        self.assertIn("DATA_FRESHNESS_REVIEW", manual_codes)
        self.assertIn("YIMU_PAN_FEEL_REQUIRED", manual_codes)
        self.assertEqual(packet["account"]["total_asset"], 714117.47)
        self.assertEqual(packet["positions"][0]["代码"], "002409")

    def test_build_packet_records_missing_ai_context_without_inventing_facts(self):
        from scripts.ops.generate_review_source_packet import build_review_source_packet

        packet = build_review_source_packet(
            date_str="2026-06-19",
            ai_context=None,
            pnl_summary={},
            trades=[],
            tickets={"status": "unknown"},
            now="2026-06-19T15:30:00+08:00",
        )

        self.assertEqual(packet["source_status"]["ai_context"], "missing")
        self.assertIsNone(packet["account"]["total_asset"])
        self.assertEqual(packet["positions"], [])
        self.assertIn("AI_CONTEXT_MISSING", [item["code"] for item in packet["manual_required"]])

    def test_build_packet_rejects_wrong_day_ai_context_but_keeps_local_pnl(self):
        from scripts.ops.generate_review_source_packet import build_review_source_packet

        packet = build_review_source_packet(
            date_str="2026-06-20",
            ai_context=self._sample_ai_context("ok"),
            pnl_summary={"total_asset": 700000.0, "pnl_pct": 0.1, "pos_pct": 12.5},
            trades=[],
            tickets={"status": "ok", "total": 0},
            now="2026-06-20T15:30:00+08:00",
        )

        self.assertEqual(packet["source_status"]["ai_context"], "date_mismatch")
        self.assertEqual(packet["account"]["total_asset"], 700000.0)
        self.assertEqual(packet["account"]["pos_pct"], 12.5)
        self.assertEqual(packet["positions"], [])
        self.assertIn("AI_CONTEXT_DATE_MISMATCH", [item["code"] for item in packet["manual_required"]])

    def test_build_packet_rejects_wrong_ai_context_schema(self):
        from scripts.ops.generate_review_source_packet import build_review_source_packet

        ai_context = self._sample_ai_context("ok")
        ai_context["schema_version"] = "ai_context.v0"

        packet = build_review_source_packet(
            date_str="2026-06-19",
            ai_context=ai_context,
            pnl_summary={},
            trades=[],
            tickets={"status": "ok", "total": 0},
            now="2026-06-19T15:30:00+08:00",
        )

        self.assertEqual(packet["source_status"]["ai_context"], "schema_mismatch")
        self.assertIsNone(packet["account"]["total_asset"])
        self.assertEqual(packet["positions"], [])
        self.assertIn("AI_CONTEXT_SCHEMA_MISMATCH", [item["code"] for item in packet["manual_required"]])

    def test_write_packet_dry_run_does_not_write(self):
        from scripts.ops.generate_review_source_packet import write_review_source_packet

        with tempfile.TemporaryDirectory() as tmp:
            packet = {"schema_version": "review_source_packet.v1", "date": "2026-06-19"}
            result = write_review_source_packet(packet, Path(tmp), apply=False)

            self.assertFalse(result["written"])
            self.assertFalse(Path(result["path"]).exists())

    def test_write_packet_apply_writes_dated_json(self):
        from scripts.ops.generate_review_source_packet import write_review_source_packet

        with tempfile.TemporaryDirectory() as tmp:
            packet = {"schema_version": "review_source_packet.v1", "date": "2026-06-19"}
            result = write_review_source_packet(packet, Path(tmp), apply=True)

            out_path = Path(result["path"])
            self.assertTrue(result["written"])
            self.assertEqual(out_path.name, "review_source_packet.json")
            self.assertEqual(out_path.parent.name, "2026-06-19")
            self.assertEqual(json.loads(out_path.read_text(encoding="utf-8")), packet)


if __name__ == "__main__":
    unittest.main()
