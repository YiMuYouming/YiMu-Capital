"""test_live_rule_engine.py — 纯函数规则引擎契约测试 (Gate 1A)

验证 evaluate_rule_state() 的所有硬规则阈值、输出契约和边界行为。
"""
import unittest
from datetime import datetime
from scripts.rule_engine import (
    build_recommendation_state,
    classify_source_gap,
    evaluate_decision_gate,
    evaluate_recommendation_candidate,
    evaluate_position_evidence,
    evaluate_rule_state,
    base_total_cap,
    build_sell_action,
)


def valid_inputs(**overrides):
    data = {
        "account": {"pnl_pct": 0.5, "valuation_complete": True},
        "risk": {"loss_streak": 0},
        "style": {
            "score": 59, "lianban_pct": 54, "trend_pct": 46,
            "market_trend_20d_direction": "向上",
        },
        "sentiment": {
            "emotion_pct": 65, "previous_emotion_pct": 45,
            "limit_up_profit_pct": 3.0, "broken_board_pct": 20,
            "promotion_pct": 22,
            "promotion_2_to_3_avg_3d": 26.966667,
            "highest_board": 3,
            "limit_up_count_avg_3d": 30,
            "promotion_1_to_2_pct": 19,
            "promotion_2_to_3_pct": 30,
            "promotion_3_to_4_pct": 40,
            "emotion_regime": "强势",
            "auction_emotion_pct": 65,
        },
        "freshness": {"quotes": "live", "sentiment": "live"},
    }
    for section, values in overrides.items():
        data.setdefault(section, {}).update(values)
    return data


class LiveRuleEngineTest(unittest.TestCase):
    """硬规则阈值矩阵测试"""

    def test_recommendation_source_gaps_are_scoped_without_erasing_other_candidates(self):
        candidate_gap = "candidate_hard:688111:sector_inflow_missing"
        side_gap = "side_hard:trend:market_trend_20d_direction"
        global_gap = "global_hard:RULE_SNAPSHOT_STALE"

        parsed_candidate = classify_source_gap(candidate_gap)
        self.assertEqual(parsed_candidate["scope"], "candidate")
        self.assertEqual(parsed_candidate["affected_candidate"], "688111")
        self.assertEqual(parsed_candidate["severity"], "hard")

        candidate_688111 = evaluate_recommendation_candidate(
            {"code": "688111", "side": "trend"},
            {"trade_entry_allowed": True},
            {"source_gaps": [candidate_gap]},
        )
        recommendation_for_other_candidate = evaluate_recommendation_candidate(
            {"code": "688112", "side": "trend"},
            {"trade_entry_allowed": True},
            {"source_gaps": [candidate_gap]},
        )
        self.assertFalse(candidate_688111["eligible"])
        self.assertTrue(recommendation_for_other_candidate["eligible"])
        entry_only_block = evaluate_recommendation_candidate(
            {"code": "688112", "side": "trend"},
            {"trade_entry_allowed": False},
            {"source_gaps": [], "blocks": [{"code": "SOURCE_GAP", "scope": "entry"}]},
        )
        self.assertTrue(entry_only_block["eligible"])
        self.assertEqual(entry_only_block["disposition"], "paper_only")

        trend_recommendation = evaluate_recommendation_candidate(
            {"code": "688112", "side": "trend"},
            {"trade_entry_allowed": True},
            {"source_gaps": [side_gap]},
        )
        lianban_recommendation = evaluate_recommendation_candidate(
            {"code": "000001", "side": "lianban"},
            {"trade_entry_allowed": True},
            {"source_gaps": [side_gap]},
        )
        self.assertFalse(trend_recommendation["eligible"])
        self.assertTrue(lianban_recommendation["eligible"])

        global_recommendation = evaluate_recommendation_candidate(
            {"code": "688112", "side": "trend"},
            {"trade_entry_allowed": True},
            {"source_gaps": [global_gap]},
        )
        self.assertFalse(global_recommendation["eligible"])

    def test_recommendation_state_keeps_paper_candidates_when_execution_gate_is_closed(self):
        state = build_recommendation_state(
            [{"code": "688112", "name": "paper", "side": "trend"}],
            {"trade_entry_allowed": False},
            {"source_gaps": []},
        )

        self.assertEqual(state["schema_version"], "recommendation_state.v1")
        self.assertEqual(state["status"], "ranked")
        self.assertFalse(state["execution_allowed"])
        self.assertTrue(state["candidates"][0]["eligible"])

    def test_sell_action_mapping_survives_buy_side_gaps_and_respects_t1(self):
        reduction = build_sell_action(
            {
                "code": "688111",
                "quantity": 900,
                "sellable_qty": 900,
                "risk_action": "reduce_half",
                "trigger": "stop_loss",
                "evidence": {"floating_pnl_pct": -5.2},
                "rule_ids": ["SELL-STOP-001"],
            },
            buy_side_source_gaps=["global_hard:RULE_SNAPSHOT_STALE"],
        )
        self.assertEqual(reduction["action"], "reduce_half")
        self.assertEqual(reduction["sellable_qty_status"], "sellable")
        self.assertIn("trigger", reduction)
        self.assertIn("evidence", reduction)
        self.assertIn("rule_ids", reduction)
        self.assertIn("global_hard:RULE_SNAPSHOT_STALE", reduction["buy_side_source_gaps"])

        locked = build_sell_action(
            {
                "code": "688112",
                "quantity": 100,
                "sellable_qty": 0,
                "risk_action": "clear",
                "trigger": "account_stop",
                "evidence": {"account_day_return_pct": -3.1},
                "rule_ids": ["ACCT-RISK-002"],
            },
            buy_side_source_gaps=["candidate_hard:688112:sector_inflow_missing"],
        )
        self.assertEqual(locked["action"], "t1_locked_next_open_review")
        self.assertEqual(locked["sellable_qty_status"], "t1_locked")
        self.assertEqual(locked["executable_qty"], 0)
        self.assertEqual(locked["requested_action"], "clear")

        for action in ("hold", "reduce_one_third", "reduce_half", "clear"):
            with self.subTest(action=action):
                mapped = build_sell_action({
                    "quantity": 100,
                    "sellable_qty": 100,
                    "risk_action": action,
                    "trigger": "explicit_risk_signal",
                    "evidence": {"observed": True},
                    "rule_ids": ["SELL-TEST-001"],
                })
                self.assertEqual(mapped["action"], action)
                if action != "hold":
                    self.assertIn("trigger", mapped)
                    self.assertIn("evidence", mapped)
                    self.assertIn("rule_ids", mapped)
                    self.assertIn("sellable_qty_status", mapped)

    # ── 全局阻断 ──

    def test_overall_promotion_never_closes_lianban_environment(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={"promotion_pct": 1, "promotion_2_to_3_avg_3d": 26.966667}),
            datetime(2026, 7, 28, 9, 40),
        )
        self.assertNotIn("LIANBAN_ENV_CLOSED", [b["code"] for b in state["blocks"]])

    def test_three_day_two_to_three_average_controls_environment(self):
        closed = evaluate_rule_state(
            valid_inputs(sentiment={"promotion_pct": 99, "promotion_2_to_3_avg_3d": 19.999}),
            datetime(2026, 7, 28, 9, 40),
        )
        boundary = evaluate_rule_state(
            valid_inputs(sentiment={"promotion_2_to_3_avg_3d": 20, "promotion_2_to_3_pct": 20}),
            datetime(2026, 7, 28, 9, 40),
        )
        self.assertIn("LIANBAN_ENV_CLOSED", [b["code"] for b in closed["blocks"]])
        self.assertNotIn("LIANBAN_ENV_CLOSED", [b["code"] for b in boundary["blocks"]])
        self.assertIn("LIANBAN_2_TO_3_STRATEGY", [b["code"] for b in boundary["blocks"]])

    def test_parent_probe_closes_lianban_but_not_trend(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={
                "emotion_pct": 45,
                "emotion_regime": "主升",
                "promotion_2_to_3_avg_3d": 26.966667,
                "promotion_1_to_2_pct": 10,
                "promotion_2_to_3_pct": 14.3,
                "promotion_3_to_4_pct": 20,
                "highest_board": 2,
                "limit_up_count_avg_3d": 20,
            }),
            datetime(2026, 7, 28, 9, 40),
        )
        codes = [block["code"] for block in state["blocks"]]
        self.assertIn("LIANBAN_ENV_CLOSED", codes)
        self.assertIn("LIANBAN_1_TO_2_STRATEGY", codes)
        self.assertIn("LIANBAN_2_TO_3_STRATEGY", codes)
        self.assertIn("LIANBAN_3_TO_4_STRATEGY", codes)
        self.assertFalse(state["windows"]["w1"]["side_buy_allowed"]["lianban"])
        self.assertTrue(state["windows"]["w1"]["side_buy_allowed"]["trend"])

    def test_lianban_environment_exact_boundaries(self):
        cases = (
            ({"highest_board": 2}, True),
            ({"highest_board": 3}, False),
            ({"limit_up_count_avg_3d": 29.999}, True),
            ({"limit_up_count_avg_3d": 30}, False),
        )
        for values, expected_closed in cases:
            with self.subTest(values=values):
                state = evaluate_rule_state(
                    valid_inputs(sentiment=values), datetime(2026, 7, 28, 9, 40))
                codes = [block["code"] for block in state["blocks"]]
                self.assertEqual("LIANBAN_ENV_CLOSED" in codes, expected_closed)

    def test_lianban_strategy_exact_boundaries(self):
        cases = (
            ("promotion_2_to_3_pct", 25, "LIANBAN_2_TO_3_STRATEGY", True),
            ("promotion_2_to_3_pct", 25.001, "LIANBAN_2_TO_3_STRATEGY", False),
            ("promotion_3_to_4_pct", 35, "LIANBAN_3_TO_4_STRATEGY", True),
            ("promotion_3_to_4_pct", 35.001, "LIANBAN_3_TO_4_STRATEGY", False),
        )
        for field, value, code, expected_blocked in cases:
            with self.subTest(field=field, value=value):
                state = evaluate_rule_state(
                    valid_inputs(sentiment={field: value}), datetime(2026, 7, 28, 9, 40))
                codes = [block["code"] for block in state["blocks"]]
                self.assertEqual(code in codes, expected_blocked)
                layer = "2_to_3" if field == "promotion_2_to_3_pct" else "3_to_4"
                self.assertEqual(
                    state["windows"]["w1"]["lianban_layer_buy_allowed"][layer],
                    not expected_blocked,
                )

    def test_one_failed_strategy_layer_does_not_close_other_lianban_layers(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={"promotion_2_to_3_pct": 25}),
            datetime(2026, 7, 28, 9, 40),
        )
        window = state["windows"]["w1"]
        self.assertFalse(window["lianban_layer_buy_allowed"]["2_to_3"])
        self.assertTrue(window["lianban_layer_buy_allowed"]["3_to_4"])
        self.assertTrue(window["side_buy_allowed"]["lianban"])
        gate = evaluate_decision_gate(
            "buy", "w1", "lianban_2_to_3", 1,
            {"trade_entry_allowed": True}, state,
        )
        self.assertFalse(gate["allowed"])
        self.assertIn("LIANBAN_2_TO_3_STRATEGY", gate["blocking_codes"])

    def test_one_to_two_threshold_depends_on_explicit_emotion_regime(self):
        cases = (
            ("低迷", 15, True), ("低迷", 15.001, False),
            ("主升", 18, True), ("主升", 18.001, False),
        )
        for regime, value, expected_blocked in cases:
            with self.subTest(regime=regime, value=value):
                state = evaluate_rule_state(
                    valid_inputs(sentiment={
                        "emotion_regime": regime,
                        "promotion_1_to_2_pct": value,
                    }),
                    datetime(2026, 7, 28, 14, 10),
                )
                codes = [block["code"] for block in state["blocks"]]
                self.assertEqual("LIANBAN_1_TO_2_STRATEGY" in codes, expected_blocked)
                self.assertEqual(
                    state["windows"]["w2"]["lianban_layer_buy_allowed"]["1_to_2"],
                    not expected_blocked,
                )

    def test_missing_lianban_gate_inputs_fail_close_only_lianban_side(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={
                "highest_board": None,
                "promotion_3_to_4_pct": None,
            }),
            datetime(2026, 7, 28, 9, 40),
        )
        self.assertFalse(state["windows"]["w1"]["side_buy_allowed"]["lianban"])
        self.assertTrue(state["windows"]["w1"]["side_buy_allowed"]["trend"])
        self.assertIn("LIANBAN_GATE_SOURCE_GAP", [b["code"] for b in state["blocks"]])
        self.assertIn("missing_rule_input:highest_board", state["source_gaps"])

    def test_market_trend_direction_matrix_is_side_scoped(self):
        for direction in ("向上", "走平"):
            with self.subTest(direction=direction):
                state = evaluate_rule_state(
                    valid_inputs(style={"market_trend_20d_direction": direction}),
                    datetime(2026, 7, 28, 9, 40),
                )
                self.assertGreater(state["caps"]["trend_side_cap_pct"], 0)
                self.assertTrue(state["windows"]["w1"]["side_buy_allowed"]["trend"])

        down = evaluate_rule_state(
            valid_inputs(style={"market_trend_20d_direction": "向下"}),
            datetime(2026, 7, 28, 9, 40),
        )
        self.assertEqual(down["caps"]["trend_side_cap_pct"], 0)
        self.assertFalse(down["windows"]["w1"]["side_buy_allowed"]["trend"])
        self.assertTrue(down["windows"]["w1"]["side_buy_allowed"]["lianban"])
        self.assertIn("TREND_DIRECTION_DOWN", [b["code"] for b in down["blocks"]])

        missing = evaluate_rule_state(
            valid_inputs(style={"market_trend_20d_direction": None}),
            datetime(2026, 7, 28, 9, 40),
        )
        self.assertEqual(missing["caps"]["trend_side_cap_pct"], 0)
        self.assertFalse(missing["windows"]["w1"]["side_buy_allowed"]["trend"])
        self.assertTrue(missing["windows"]["w1"]["side_buy_allowed"]["lianban"])
        self.assertIn("missing_rule_input:market_trend_20d_direction", missing["source_gaps"])

    def test_trend_direction_never_blocks_exit_actions(self):
        for direction in ("向下", None):
            state = evaluate_rule_state(
                valid_inputs(style={"market_trend_20d_direction": direction}),
                datetime(2026, 7, 28, 9, 40),
            )
            for action in ("sell", "reduce", "close"):
                gate = evaluate_decision_gate(
                    action, "w1", "trend_core", 1,
                    {"trade_entry_allowed": True}, state,
                )
                self.assertTrue(gate["allowed"])

    def test_emotion_35_to_60_does_not_close_trend_w1(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={"emotion_pct": 45}),
            datetime(2026, 7, 28, 9, 40),
        )
        self.assertTrue(state["windows"]["w1"]["side_buy_allowed"]["trend"])
        self.assertNotIn("W1_EMOTION", [b["code"] for b in state["blocks"]])

    def test_auction_climax_80_85_90_uses_side_window_table(self):
        at_80 = evaluate_rule_state(
            valid_inputs(sentiment={"auction_emotion_pct": 80}), datetime(2026, 7, 28, 14, 10))
        at_85 = evaluate_rule_state(
            valid_inputs(sentiment={"auction_emotion_pct": 85}), datetime(2026, 7, 28, 14, 10))
        at_90 = evaluate_rule_state(
            valid_inputs(sentiment={"auction_emotion_pct": 90}), datetime(2026, 7, 28, 14, 10))
        self.assertEqual(at_80["windows"]["w1"]["side_cap_factor"]["lianban"], 0.5)
        self.assertTrue(at_80["windows"]["w2"]["side_buy_allowed"]["trend"])
        self.assertFalse(at_85["windows"]["w1"]["side_buy_allowed"]["lianban"])
        self.assertEqual(at_85["windows"]["w2"]["side_cap_factor"]["trend"], 0.5)
        self.assertFalse(at_90["windows"]["w1"]["side_buy_allowed"]["lianban"])
        self.assertFalse(at_90["windows"]["w2"]["side_buy_allowed"]["trend"])

    def test_style_change_over_30pp_uses_midpoint_and_blocks_entries(self):
        state = evaluate_rule_state(
            valid_inputs(style={"lianban_pct": 30, "trend_pct": 70, "previous_lianban_pct": 80}),
            datetime(2026, 7, 28, 9, 40),
        )
        self.assertEqual(state["caps"]["lianban_pct"], 55)
        self.assertEqual(state["caps"]["trend_pct"], 45)
        self.assertTrue(state["style_shift_buffer"]["active"])
        self.assertIn("STYLE_SHIFT_BUFFER", [b["code"] for b in state["blocks"]])

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
        self.assertIn("CLIMAX_STOP", [b["code"] for b in state["blocks"]])
        gate = evaluate_decision_gate(
            "buy", "w2", "trend_core", 1, {"trade_entry_allowed": True}, state)
        self.assertFalse(gate["allowed"])

    def test_current_emotion_above_80_is_no_buy_not_half_cap_authorization(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={"emotion_pct": 82}),
            datetime(2026, 5, 27, 14, 10))
        self.assertEqual(state["caps"]["base_total_pct"], 20)
        self.assertEqual(state["caps"]["total_pct"], 20)
        self.assertIn("CLIMAX_STOP", [b["code"] for b in state["blocks"]])

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

    def test_friday_itself_does_not_block_w1_or_cap_trend(self):
        state = evaluate_rule_state(valid_inputs(),
                                    datetime(2026, 5, 29, 14, 10))
        self.assertNotIn("FRIDAY_W1", [b["code"] for b in state["blocks"]])
        self.assertNotIn("FRIDAY_TREND_CAP", [b["code"] for b in state["blocks"]])
        self.assertEqual(state["caps"]["trend_pct"], 46)
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

    def test_w1_emotion_45_does_not_create_old_global_block(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={"emotion_pct": 45}),
            datetime(2026, 5, 27, 9, 40))
        self.assertNotIn("W1_EMOTION", [b["code"] for b in state["blocks"]])
        self.assertTrue(state["windows"]["w1"]["side_buy_allowed"]["trend"])

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

    def test_overall_promotion_is_auxiliary_in_low_emotion(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={"emotion_pct": 25, "promotion_pct": 10}),
            datetime(2026, 5, 27, 9, 40))
        self.assertNotIn("W1_PROMOTION", [b["code"] for b in state["blocks"]])
        self.assertNotIn("LIANBAN_ENV_CLOSED", [b["code"] for b in state["blocks"]])

    def test_overall_promotion_is_auxiliary_in_main_rise(self):
        state = evaluate_rule_state(
            valid_inputs(sentiment={"emotion_pct": 45, "promotion_pct": 16}),
            datetime(2026, 5, 27, 9, 40))
        self.assertNotIn("W1_PROMOTION", [b["code"] for b in state["blocks"]])

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

    def test_score_table_is_not_final_position_authority(self):
        common = {
            "enabled": True,
            "account_cap_pct": 35,
            "opportunity_cap_pct": 30,
            "earned_cap_pct": 25,
            "mainline_confirmed": True,
        }
        low = evaluate_rule_state(valid_inputs(style={"score": 10}, position_control=common), datetime(2026, 7, 28, 14, 10))
        high = evaluate_rule_state(valid_inputs(style={"score": 95}, position_control=common), datetime(2026, 7, 28, 14, 10))
        self.assertEqual(low["caps"]["total_pct"], 25)
        self.assertEqual(high["caps"]["total_pct"], 25)

    # ── 时段边界 ──

    def test_w1_in_session_at_0930(self):
        state = evaluate_rule_state(valid_inputs(),
                                    datetime(2026, 5, 27, 9, 30))
        self.assertTrue(state["windows"]["w1"]["in_session"])

    def test_w1_not_in_session_at_1001(self):
        state = evaluate_rule_state(valid_inputs(),
                                    datetime(2026, 5, 27, 10, 1))
        self.assertFalse(state["windows"]["w1"]["in_session"])

    def test_w1_exact_second_boundary(self):
        self.assertTrue(evaluate_rule_state(valid_inputs(), datetime(2026, 7, 28, 10, 0, 59))["windows"]["w1"]["in_session"])
        self.assertFalse(evaluate_rule_state(valid_inputs(), datetime(2026, 7, 28, 10, 1, 0))["windows"]["w1"]["in_session"])

    def test_w2_in_session_at_1400(self):
        state = evaluate_rule_state(valid_inputs(),
                                    datetime(2026, 5, 27, 14, 0))
        self.assertTrue(state["windows"]["w2"]["in_session"])

    def test_w2_not_in_session_at_1451(self):
        state = evaluate_rule_state(valid_inputs(),
                                    datetime(2026, 5, 27, 14, 51))
        self.assertFalse(state["windows"]["w2"]["in_session"])

    def test_w2_exact_second_boundary(self):
        self.assertTrue(evaluate_rule_state(valid_inputs(), datetime(2026, 7, 28, 14, 50, 59))["windows"]["w2"]["in_session"])
        self.assertFalse(evaluate_rule_state(valid_inputs(), datetime(2026, 7, 28, 14, 51, 0))["windows"]["w2"]["in_session"])

    def test_pos_size_008_missing_evidence_blocks_buy_and_add(self):
        for action in ("buy", "add"):
            with self.subTest(action=action):
                result = evaluate_position_evidence(action, {"entry_leg": 2})
                self.assertFalse(result["allowed"])
                self.assertEqual(result["code"], "POS-SIZE-008")
                self.assertIn("first_entry_trade_date", result["missing_fields"])
                self.assertIn("sector_inflow_query_time", result["missing_fields"])

    def test_pos_size_008_accepts_complete_leg2_evidence(self):
        result = evaluate_position_evidence("add", {
            "entry_leg": 2,
            "first_entry_trade_date": "2026-07-27",
            "trading_days_since_first_entry": 1,
            "leg1_or_leg2_floating_pnl": -0.3,
            "leg2_already_used": False,
            "volume_ratio": 0.7,
            "pullback_ma_status": "ma5_supported",
            "sector_inflow_status": "not_large_outflow",
            "sector_inflow_query_time": "2026-07-28T09:35:00+08:00",
            "planned_single_stock_cap_pct": 25,
            "current_single_stock_pct": 10,
            "acceleration_segment_confirmed": False,
        })
        self.assertTrue(result["allowed"], result)

    def test_action_specific_gate_blocks_entry_but_allows_risk_reduction(self):
        rule_state = {
            "tradable": True,
            "blocks": [],
            "source_gaps": [],
            "windows": {
                "w1": {"in_session": True, "buy_allowed": False, "blocks": ["W1_LIMIT_UP_PROFIT"]},
            },
            "caps": {"add_allowed": True},
        }
        health = {"trade_entry_allowed": True}
        for action in ("buy", "add", "do_t"):
            with self.subTest(action=action):
                gate = evaluate_decision_gate(action, "w1", "trend_core", 1, health, rule_state)
                self.assertFalse(gate["allowed"])
                self.assertIn("W1_LIMIT_UP_PROFIT", gate["blocking_codes"])
        for action in ("sell", "reduce", "close"):
            with self.subTest(action=action):
                self.assertTrue(evaluate_decision_gate(action, "w1", "trend_core", None, health, rule_state)["allowed"])

    def test_rule_snapshot_stale_blocks_entry_gate(self):
        gate = evaluate_decision_gate(
            "buy", "w1", "trend_core", 1,
            {"trade_entry_allowed": True},
            {"tradable": True, "blocks": [], "source_gaps": ["RULE_SNAPSHOT_STALE"],
             "windows": {"w1": {"in_session": True, "buy_allowed": True, "blocks": []}},
             "caps": {"add_allowed": True}},
        )
        self.assertFalse(gate["allowed"])
        self.assertIn("RULE_SNAPSHOT_STALE", gate["blocking_codes"])

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
