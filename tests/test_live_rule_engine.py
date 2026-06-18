"""test_live_rule_engine.py — 纯函数规则引擎契约测试 (Gate 1A)

验证 evaluate_rule_state() 的所有硬规则阈值、输出契约和边界行为。
"""
import unittest
from datetime import datetime
from scripts.rule_engine import evaluate_rule_state, base_total_cap


def valid_inputs(**overrides):
    data = {
        "account": {"pnl_pct": 0.5, "valuation_complete": True},
        "risk": {"loss_streak": 0},
        "style": {"score": 59, "lianban_pct": 54, "trend_pct": 46},
        "sentiment": {
            "emotion_pct": 65, "previous_emotion_pct": 45,
            "limit_up_profit_pct": 3.0, "broken_board_pct": 20,
            "promotion_pct": 22,
        },
        "freshness": {"quotes": "live", "sentiment": "live"},
    }
    for section, values in overrides.items():
        data.setdefault(section, {}).update(values)
    return data


class LiveRuleEngineTest(unittest.TestCase):
    """硬规则阈值矩阵测试"""

    # ── 全局阻断 ──

    def test_day_stop_blocks_all_new_buy(self):
        state = evaluate_rule_state(valid_inputs(account={"pnl_pct": -3.0}),
                                    datetime(2026, 5, 27, 9, 40))
        self.assertFalse(state["tradable"])
        self.assertEqual(state["caps"]["total_pct"], 0)
        self.assertIn("DAY_STOP", [b["code"] for b in state["blocks"]])

    def test_untrusted_valuation_blocks_all_buy(self):
        state = evaluate_rule_state(valid_inputs(account={"valuation_complete": False}),
                                    datetime(2026, 5, 27, 9, 40))
        self.assertIn("DATA_UNTRUSTED", [b["code"] for b in state["blocks"]])

    def test_stale_quotes_with_complete_valuation_warns_not_blocks(self):
        state = evaluate_rule_state(
            valid_inputs(freshness={"quotes": "stale", "sentiment": "live"}),
            datetime(2026, 5, 27, 9, 40))
        self.assertTrue(state["tradable"])
        self.assertNotIn("DATA_UNTRUSTED", [b["code"] for b in state["blocks"]])
        self.assertIn("QUOTE_STALE", [w["code"] for w in state["warnings"]])

    def test_loss_streak_blocks_all(self):
        state = evaluate_rule_state(valid_inputs(risk={"loss_streak": 2}),
                                    datetime(2026, 5, 27, 14, 10))
        self.assertFalse(state["tradable"])
        self.assertIn("LOSS_STREAK", [b["code"] for b in state["blocks"]])

    def test_loss_streak_can_be_advisory_when_plan_overrides(self):
        state = evaluate_rule_state(
            valid_inputs(risk={"loss_streak": 2, "loss_streak_hard_stop": False}),
            datetime(2026, 5, 27, 14, 10))
        self.assertTrue(state["tradable"])
        self.assertNotIn("LOSS_STREAK", [b["code"] for b in state["blocks"]])
        self.assertIn("LOSS_STREAK", [w["code"] for w in state["warnings"]])

    def test_loss_streak_one_does_not_trigger(self):
        state = evaluate_rule_state(valid_inputs(risk={"loss_streak": 1}),
                                    datetime(2026, 5, 27, 14, 10))
        self.assertTrue(state["tradable"])

    def test_double_ice_blocks_all(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={"emotion_pct": 15, "previous_emotion_pct": 10}),
            datetime(2026, 5, 27, 14, 10))
        self.assertFalse(state["tradable"])
        self.assertIn("DOUBLE_ICE", [b["code"] for b in state["blocks"]])

    def test_single_ice_not_double(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={"emotion_pct": 15, "previous_emotion_pct": 25}),
            datetime(2026, 5, 27, 14, 10))
        self.assertTrue(state["tradable"])

    def test_climax_stop_blocks_all(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={"emotion_pct": 85}),
            datetime(2026, 5, 27, 14, 10))
        self.assertFalse(state["tradable"])
        self.assertIn("CLIMAX_STOP", [b["code"] for b in state["blocks"]])

    def test_climax_reduce_halves_cap_without_full_stop(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={"emotion_pct": 82}),
            datetime(2026, 5, 27, 14, 10))
        self.assertTrue(state["tradable"])
        self.assertEqual(state["caps"]["base_total_pct"], 20)
        self.assertEqual(state["caps"]["total_pct"], 10)

    def test_sentiment_stale_with_complete_fields_warns_not_blocks(self):
        state = evaluate_rule_state(
            valid_inputs(freshness={"quotes": "live", "sentiment": "stale"}),
            datetime(2026, 5, 27, 9, 40))
        self.assertTrue(state["tradable"])
        self.assertNotIn("SENTIMENT_STALE", [b["code"] for b in state["blocks"]])
        self.assertIn("SENTIMENT_STALE", [w["code"] for w in state["warnings"]])

    def test_sentiment_dead_with_complete_fields_warns_not_blocks(self):
        state = evaluate_rule_state(
            valid_inputs(freshness={"quotes": "live", "sentiment": "dead"}),
            datetime(2026, 5, 27, 9, 40))
        self.assertTrue(state["tradable"])
        self.assertNotIn("SENTIMENT_STALE", [b["code"] for b in state["blocks"]])
        self.assertIn("SENTIMENT_STALE", [w["code"] for w in state["warnings"]])

    def test_missing_sentiment_fields_blocks_all(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={"emotion_pct": None, "limit_up_profit_pct": None,
                                    "broken_board_pct": None, "promotion_pct": None}),
            datetime(2026, 5, 27, 9, 40))
        self.assertIn("SENTIMENT_STALE", [b["code"] for b in state["blocks"]])

    # ── 周五规则 ──

    def test_friday_blocks_only_w1_and_caps_trend(self):
        state = evaluate_rule_state(valid_inputs(),
                                    datetime(2026, 5, 29, 14, 10))
        self.assertIn("FRIDAY_W1", [b["code"] for b in state["blocks"]])
        self.assertEqual(state["caps"]["trend_pct"], 15)
        self.assertTrue(state["windows"]["w2"]["buy_allowed"])

    def test_premarket_window_plan_can_open_friday_w1(self):
        state = evaluate_rule_state(
            valid_inputs(time_window={"w1_status": "开放", "w2_status": "开放"}),
            datetime(2026, 5, 29, 9, 40))
        self.assertNotIn("FRIDAY_W1", [b["code"] for b in state["blocks"]])

    def test_friday_not_auto_close_w2(self):
        state = evaluate_rule_state(valid_inputs(),
                                    datetime(2026, 5, 29, 14, 10))
        self.assertTrue(state["windows"]["w2"]["in_session"])
        # W2 不应有 FRIDAY_W2 阻断
        w2_blocks = [b for b in state["blocks"] if b["scope"] == "w2"]
        self.assertEqual(len(w2_blocks), 0)

    # ── W1 窗口规则 ──

    def test_w1_emotion_below_60_blocks(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={"emotion_pct": 45}),
            datetime(2026, 5, 27, 9, 40))
        self.assertIn("W1_EMOTION", [b["code"] for b in state["blocks"]])

    def test_w1_limit_up_profit_blocks(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={"limit_up_profit_pct": 1.5}),
            datetime(2026, 5, 27, 9, 40))
        self.assertIn("W1_LIMIT_UP_PROFIT", [b["code"] for b in state["blocks"]])

    def test_w1_broken_board_blocks(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={"broken_board_pct": 35}),
            datetime(2026, 5, 27, 9, 40))
        self.assertIn("W1_BROKEN_BOARD", [b["code"] for b in state["blocks"]])

    def test_w1_promotion_strict_threshold(self):
        # emotion < 40 → promotion must be >= 15
        state = evaluate_rule_state(
            valid_inputs(sentiment={"emotion_pct": 25, "promotion_pct": 10}),
            datetime(2026, 5, 27, 9, 40))
        self.assertIn("W1_PROMOTION", [b["code"] for b in state["blocks"]])

    def test_w1_promotion_relaxed_threshold(self):
        # emotion >= 40 → promotion must be >= 18
        state = evaluate_rule_state(
            valid_inputs(sentiment={"emotion_pct": 45, "promotion_pct": 16}),
            datetime(2026, 5, 27, 9, 40))
        self.assertIn("W1_PROMOTION", [b["code"] for b in state["blocks"]])

    # ── W2 窗口规则 ──

    def test_w2_ice_blocks(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={"emotion_pct": 15}),
            datetime(2026, 5, 27, 14, 10))
        self.assertIn("W2_ICE_RISK", [b["code"] for b in state["blocks"]])

    def test_w2_broken_board_blocks(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={"broken_board_pct": 50}),
            datetime(2026, 5, 27, 14, 10))
        self.assertIn("W2_BROKEN_BOARD", [b["code"] for b in state["blocks"]])

    # ── 窗口阈值差异 ──

    def test_broken_board_thresholds_differ_by_window(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={"broken_board_pct": 35}),
            datetime(2026, 5, 27, 9, 40))
        self.assertFalse(state["windows"]["w1"]["buy_allowed"])
        self.assertNotIn("W2_BROKEN_BOARD", [b["code"] for b in state["blocks"]])

    # ── Vault 三层基础仓位 ──

    def test_ice_with_weak_trend_is_twenty_percent(self):
        state = evaluate_rule_state(
            valid_inputs(
                style={"score": 10},
                sentiment={"emotion_pct": 15, "previous_emotion_pct": 25, "lianban_risk": 0.3},
            ),
            datetime(2026, 5, 27, 14, 10))
        self.assertEqual(state["caps"]["base_total_pct"], 20)

    def test_default_emotion_keeps_lianban_side_sixty_percent(self):
        state = evaluate_rule_state(
            valid_inputs(style={"score": 40}),
            datetime(2026, 5, 27, 14, 10))
        self.assertEqual(state["caps"]["base_total_pct"], 60)

    def test_score_80_is_sixty_percent(self):
        state = evaluate_rule_state(
            valid_inputs(style={"score": 80}),
            datetime(2026, 5, 27, 14, 10))
        self.assertEqual(state["caps"]["base_total_pct"], 60)

    # ── 主线盈利解锁仓位 ──

    def test_position_control_legacy_mode_preserves_existing_total_cap(self):
        state = evaluate_rule_state(valid_inputs(),
                                    datetime(2026, 5, 27, 14, 10))
        self.assertEqual(state["caps"]["total_pct"], 60)
        self.assertEqual(state["caps"]["position_control_mode"], "legacy")
        self.assertEqual(state["caps"]["single_stock_cap_pct"], 0)

    def test_mainline_without_profit_is_trial_cap_only(self):
        state = evaluate_rule_state(
            valid_inputs(
                style={"trend_score": 18, "lianban_pct": 0, "trend_pct": 100},
                sentiment={"emotion_pct": 32, "previous_emotion_pct": 45},
                position_control={
                    "enabled": True,
                    "account_cap_pct": 80,
                    "mainline_confirmed": True,
                    "current_position_pct": 0,
                },
            ),
            datetime(2026, 5, 27, 14, 10))
        self.assertEqual(state["caps"]["base_total_pct"], 60)
        self.assertEqual(state["caps"]["opportunity_cap_pct"], 60)
        self.assertEqual(state["caps"]["earned_cap_pct"], 20)
        self.assertEqual(state["caps"]["total_pct"], 20)
        self.assertEqual(state["caps"]["available_add_pct"], 20)
        self.assertEqual(state["caps"]["position_control_mode"], "earned_mainline")

    def test_polarized_market_without_mainline_limits_opportunity(self):
        state = evaluate_rule_state(
            valid_inputs(position_control={
                "enabled": True,
                "account_cap_pct": 80,
                "mainline_confirmed": False,
                "market_breadth_polarization": True,
            }),
            datetime(2026, 5, 27, 14, 10))
        self.assertEqual(state["caps"]["opportunity_cap_pct"], 10)
        self.assertEqual(state["caps"]["earned_cap_pct"], 10)
        self.assertEqual(state["caps"]["total_pct"], 10)

    def test_one_profitable_mainline_position_unlocks_forty_percent(self):
        state = evaluate_rule_state(
            valid_inputs(position_control={
                "enabled": True,
                "account_cap_pct": 80,
                "mainline_confirmed": True,
                "current_position_pct": 30,
                "positions": [
                    {"code": "000001", "floating_pnl_pct": 2.4, "is_mainline": True},
                    {"code": "000002", "floating_pnl_pct": -1.0, "is_mainline": True},
                ],
            }),
            datetime(2026, 5, 27, 14, 10))
        self.assertEqual(state["caps"]["profitable_mainline_positions"], 1)
        self.assertEqual(state["caps"]["earned_cap_pct"], 40)
        self.assertEqual(state["caps"]["total_pct"], 40)
        self.assertEqual(state["caps"]["available_add_pct"], 10)

    def test_floating_loss_position_blocks_available_add_until_profit(self):
        state = evaluate_rule_state(
            valid_inputs(position_control={
                "enabled": True,
                "account_cap_pct": 80,
                "mainline_confirmed": True,
                "current_position_pct": 10,
                "positions": [
                    {"code": "000001", "floating_pnl_pct": -1.2, "is_mainline": True},
                ],
            }),
            datetime(2026, 5, 27, 14, 10))
        self.assertEqual(state["caps"]["earned_cap_pct"], 20)
        self.assertEqual(state["caps"]["total_pct"], 20)
        self.assertEqual(state["caps"]["available_add_pct"], 0)
        self.assertFalse(state["caps"]["add_allowed"])
        self.assertEqual(state["caps"]["add_block_reason"], "floating_loss")

    def test_two_profitable_mainline_positions_unlock_sixty_percent(self):
        state = evaluate_rule_state(
            valid_inputs(position_control={
                "enabled": True,
                "account_cap_pct": 80,
                "mainline_confirmed": True,
                "current_position_pct": 45,
                "positions": [
                    {"code": "000001", "floating_pnl_pct": 2.4, "is_mainline": True},
                    {"code": "000002", "floating_pnl_pct": 0.8, "is_mainline": True},
                ],
            }),
            datetime(2026, 5, 27, 14, 10))
        self.assertEqual(state["caps"]["profitable_mainline_positions"], 2)
        self.assertEqual(state["caps"]["earned_cap_pct"], 60)
        self.assertEqual(state["caps"]["total_pct"], 60)
        self.assertEqual(state["caps"]["available_add_pct"], 15)

    def test_account_cap_still_limits_earned_position(self):
        state = evaluate_rule_state(
            valid_inputs(position_control={
                "enabled": True,
                "account_cap_pct": 40,
                "mainline_confirmed": True,
                "positions": [
                    {"code": "000001", "floating_pnl_pct": 2.4, "is_mainline": True},
                    {"code": "000002", "floating_pnl_pct": 0.8, "is_mainline": True},
                ],
            }),
            datetime(2026, 5, 27, 14, 10))
        self.assertEqual(state["caps"]["account_cap_pct"], 40)
        self.assertEqual(state["caps"]["earned_cap_pct"], 60)
        self.assertEqual(state["caps"]["total_pct"], 40)

    def test_target_role_sets_single_stock_cap_and_add_step(self):
        state = evaluate_rule_state(
            valid_inputs(position_control={
                "enabled": True,
                "account_cap_pct": 80,
                "mainline_confirmed": True,
                "target_role": "capacity_core",
                "target_is_mainline": True,
                "positions": [{"code": "000001", "floating_pnl_pct": 2.4, "is_mainline": True}],
            }),
            datetime(2026, 5, 27, 14, 10))
        self.assertEqual(state["caps"]["single_stock_cap_pct"], 25)
        self.assertEqual(state["caps"]["add_step_pct"], 10)
        self.assertEqual(state["caps"]["max_positions"], 3)

    # ── base_total_cap 分档 ──

    def test_base_total_cap_brackets(self):
        self.assertEqual(base_total_cap(95), 60)
        self.assertEqual(base_total_cap(80), 60)
        self.assertEqual(base_total_cap(79), 50)
        self.assertEqual(base_total_cap(60), 50)
        self.assertEqual(base_total_cap(59), 40)
        self.assertEqual(base_total_cap(40), 40)
        self.assertEqual(base_total_cap(39), 20)
        self.assertEqual(base_total_cap(0), 20)
        self.assertEqual(base_total_cap(None), 20)

    # ── 时段边界 ──

    def test_w1_in_session_at_0930(self):
        state = evaluate_rule_state(valid_inputs(),
                                    datetime(2026, 5, 27, 9, 30))
        self.assertTrue(state["windows"]["w1"]["in_session"])

    def test_w1_not_in_session_at_1001(self):
        state = evaluate_rule_state(valid_inputs(),
                                    datetime(2026, 5, 27, 10, 1))
        self.assertFalse(state["windows"]["w1"]["in_session"])

    def test_w2_in_session_at_1400(self):
        state = evaluate_rule_state(valid_inputs(),
                                    datetime(2026, 5, 27, 14, 0))
        self.assertTrue(state["windows"]["w2"]["in_session"])

    def test_w2_not_in_session_at_1451(self):
        state = evaluate_rule_state(valid_inputs(),
                                    datetime(2026, 5, 27, 14, 51))
        self.assertFalse(state["windows"]["w2"]["in_session"])

    # ── 输出契约 ──

    def test_output_contains_all_required_fields(self):
        state = evaluate_rule_state(valid_inputs(),
                                    datetime(2026, 5, 27, 9, 40))
        self.assertEqual(state["version"], "g1a-v1")
        self.assertIn("evaluated_at", state)
        self.assertIn("tradable", state)
        self.assertIn("market_regime", state)
        self.assertIn("caps", state)
        for key in ("base_total_pct", "total_pct", "lianban_pct",
                     "trend_pct", "first_entry_pct"):
            self.assertIn(key, state["caps"])
        self.assertIn("windows", state)
        for w in ("w1", "w2"):
            self.assertIn(w, state["windows"])
            for f in ("in_session", "buy_allowed", "blocks"):
                self.assertIn(f, state["windows"][w])
        self.assertIsInstance(state["blocks"], list)
        self.assertIsInstance(state["warnings"], list)

    def test_blocks_have_evidence_not_just_message(self):
        state = evaluate_rule_state(
            valid_inputs(account={"pnl_pct": -5.0}),
            datetime(2026, 5, 27, 9, 40))
        for b in state["blocks"]:
            self.assertIn("code", b)
            self.assertIn("scope", b)
            self.assertIn("message", b)
            self.assertIn("evidence", b)
            self.assertGreater(len(b["evidence"]), 0,
                               f"{b['code']} must have evidence")

    def test_first_entry_pct_is_ten_when_tradable(self):
        state = evaluate_rule_state(valid_inputs(),
                                    datetime(2026, 5, 27, 10, 5))
        self.assertTrue(state["tradable"])
        self.assertEqual(state["caps"]["first_entry_pct"], 10)


if __name__ == "__main__":
    unittest.main()
