"""test_evidence_summary.py — EvidenceSummary.build() pure-function unit tests

Verifies S0/E/A/R taxonomy, stable IDs, trade-block risk mapping,
close-snapshot non-fatal rendering, and graceful degradation.
"""
import json
import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_summary(data, runtime=None):
    runtime = runtime or {}
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const src = fs.readFileSync('{(ROOT / "evidence-summary.js").as_posix()}', 'utf8');
        const ctx = {{ console, window: {{}}, globalThis: {{}} }};
        vm.createContext(ctx);
        vm.runInContext(src, ctx);
        const mod = ctx.EvidenceSummary || ctx.window.EvidenceSummary || ctx.globalThis.EvidenceSummary;
        if (!mod || typeof mod.build !== 'function') {{
          console.log(JSON.stringify({{error: 'EvidenceSummary.build missing'}}));
          process.exit(0);
        }}
        const result = mod.build({json.dumps(data, ensure_ascii=False)}, {json.dumps(runtime, ensure_ascii=False)});
        console.log(JSON.stringify(result));
        """
    )
    result = subprocess.run(["node", "-e", script], cwd=str(ROOT), capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    if payload.get("error"):
        raise AssertionError(payload["error"])
    return payload


class EvidenceSummaryTest(unittest.TestCase):
    def test_builds_stable_situation_and_evidence(self):
        data = {
            "pnl_live": {
                "total_asset": 720227.67,
                "cash": 583679.67,
                "mv": 136548,
                "pos_pct": 18.96,
                "pnl_amount": -3672,
                "pnl_pct": -0.51,
                "quote_status": "close_snapshot",
                "valuation_complete": True,
                "positions": [
                    {"标的": "光讯科技", "代码": "002281", "市值": 136548, "现价": 227.58, "成本": 219.49, "today_pnl": 8188, "today_pnl_pct": 4.12, "total_pnl": 4854, "total_pnl_pct": 3.69}
                ],
            },
            "trade_tickets": [
                {"ticket_id": "T1", "status": "filled", "action_type": "clear", "name": "立讯精密"},
                {"ticket_id": "T2", "status": "closed", "action_type": "clear", "name": "立讯精密"},
            ],
            "sentiment": {"情绪值": 59},
            "iwencai": {"涨停家数": 46, "跌停家数": 2, "_freshness": {"level": "delayed"}},
            "rule_state": {"tradable": True, "caps": {"total_pct": 40}, "blocks": []},
        }
        snapshot = run_summary(data, {"healthLabel": "降级", "healthConfirmed": True, "tradeEntryAllowed": True, "connectionStatus": "close_snapshot"})
        self.assertEqual(snapshot["situation"]["id"], "S0")
        self.assertEqual(snapshot["situation"]["health"]["label"], "降级")
        self.assertEqual(snapshot["evidence"][0]["id"], "E1")
        self.assertIn("光讯科技", snapshot["evidence"][0]["title"])
        self.assertTrue(any(item["id"] == "E2" and "票据" in item["title"] for item in snapshot["evidence"]))
        self.assertTrue(any(item["id"] == "A1" and "降级" in item["title"] for item in snapshot["alerts"]))
        self.assertTrue(any("收盘快照" in item["title"] for item in snapshot["alerts"]))

    def test_trade_block_becomes_risk(self):
        data = {
            "pnl_live": {"total_asset": 100000, "cash": 60000, "mv": 40000, "pnl_pct": -4.2, "pos_pct": 40},
            "rule_state": {
                "tradable": False,
                "blocks": [{"code": "DAY_STOP", "message": "单日熔断触发"}],
                "caps": {"total_pct": 0},
            },
            "trade_tickets": [],
            "sentiment": {"情绪值": 18},
        }
        snapshot = run_summary(data, {"healthLabel": "阻断", "healthConfirmed": True, "healthCritical": True, "tradeEntryAllowed": False, "connectionStatus": "live"})
        self.assertEqual(snapshot["situation"]["trade"]["allowed"], False)
        self.assertTrue(any(item["id"] == "R1" and item["tone"] == "danger" for item in snapshot["risks"]))
        self.assertTrue(any("单日熔断" in item["detail"] for item in snapshot["risks"]))

    def test_missing_data_does_not_crash(self):
        snapshot = run_summary({}, {})
        self.assertEqual(snapshot["situation"]["id"], "S0")
        self.assertEqual(snapshot["situation"]["pnl"]["pnl_pct_text"], "—")
        self.assertGreaterEqual(len(snapshot["alerts"]), 1)
        market = next(item for item in snapshot["evidence"] if item["id"] == "E3")
        self.assertEqual(market["tone"], "neutral")

    def test_ticket_counts_match_w24_closed_bucket(self):
        snapshot = run_summary({
            "trade_tickets": [
                {"ticket_id": "T1", "status": "filled"},
                {"ticket_id": "T2", "status": "partially_filled"},
                {"ticket_id": "T3", "status": "cancelled"},
                {"ticket_id": "T4", "status": "executable"},
            ],
            "sentiment": {"情绪值": 45},
        }, {"healthConfirmed": True})
        ticket = next(item for item in snapshot["evidence"] if item["id"] == "E2")
        self.assertEqual(ticket["value"], "3/4")
        self.assertIn("可执行 1", ticket["detail"])


if __name__ == "__main__":
    unittest.main()
