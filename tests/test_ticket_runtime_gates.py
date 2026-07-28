"""Runtime gate tests for the trade ticket upgrade.

These tests pin the P0 semantic changes before ticket automation writes facts.
"""
import unittest
from datetime import datetime

from scripts.rule_engine import evaluate_rule_state


def valid_inputs(**overrides):
    data = {
        "account": {
            "account_day_return_pct": 0.5,
            "pnl_pct": 0.5,
            "valuation_complete": True,
        },
        "risk": {"losing_account_days": 0, "loss_streak": 0},
        "style": {
            "score": 59, "lianban_pct": 54, "trend_pct": 46,
            "market_trend_20d_direction": "向上",
        },
        "sentiment": {
            "emotion_pct": 65,
            "previous_emotion_pct": 45,
            "limit_up_profit_pct": 3.0,
            "broken_board_pct": 20,
            "promotion_pct": 22,
            "promotion_2_to_3_avg_3d": 26.966667,
            "highest_board": 3,
            "limit_up_count_avg_3d": 30,
            "promotion_1_to_2_pct": 19,
            "promotion_2_to_3_pct": 30,
            "promotion_3_to_4_pct": 40,
            "emotion_regime": "强势",
        },
        "freshness": {"quotes": "live", "sentiment": "live"},
        "funds": {},
    }
    for section, values in overrides.items():
        data.setdefault(section, {}).update(values)
    return data


class TicketRuntimeGatesTest(unittest.TestCase):
    def test_account_circuit_breaker_uses_account_metric_only(self):
        state = evaluate_rule_state(
            valid_inputs(account={
                "account_day_return_pct": -1.0,
                "trade_return_pct": -5.8,
                "valuation_complete": True,
            }),
            datetime(2026, 6, 4, 9, 40),
        )

        codes = [block["code"] for block in state["blocks"]]
        self.assertNotIn("DAY_STOP", codes)
        self.assertTrue(state["tradable"])

    def test_ice_point_w1_stays_blocked_even_with_extra_filters(self):
        state = evaluate_rule_state(
            valid_inputs(
                sentiment={
                    "emotion_pct": 28.4,
                    "previous_emotion_pct": 45,
                    "limit_up_profit_pct": 3.0,
                    "broken_board_pct": 20,
                    "promotion_pct": 22,
                },
                funds={"main_inflow": 1000000, "volume_ratio": 1.5},
            ),
            datetime(2026, 6, 4, 9, 40),
        )

        self.assertFalse(state["windows"]["w1"]["buy_allowed"])
        self.assertIn("WIN-ICE-W1-001", state["windows"]["w1"]["blocks"])

    def test_funds_conflict_cannot_authorize_buy(self):
        state = evaluate_rule_state(
            valid_inputs(funds={
                "main_inflow": 1000000,
                "dde_big_order_net": -250000,
                "source": "iwencai",
                "query": "主力净流入 DDE大单净额",
            }),
            datetime(2026, 6, 4, 9, 40),
        )

        codes = [block["code"] for block in state["blocks"]]
        self.assertIn("DATA-FUNDS-001", codes)
        self.assertFalse(state["tradable"])

    def test_style_adjusted_score_requires_audit_fields(self):
        state = evaluate_rule_state(
            valid_inputs(style={
                "score": 52,
                "style_score_raw": 46,
                "style_score_adjusted": 52,
                "adjustment_reason": "量能修正",
                "script_version": "style-v1",
            }),
            datetime(2026, 6, 4, 9, 40),
        )

        audit_blocks = [
            block for block in state["blocks"]
            if block["code"] == "STYLE-SCORE-AUDIT-001"
        ]
        self.assertEqual(len(audit_blocks), 1)
        self.assertIn("approver", audit_blocks[0]["evidence"]["missing"])
        self.assertFalse(state["tradable"])


if __name__ == "__main__":
    unittest.main()
