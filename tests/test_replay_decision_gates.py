"""Regression tests for the immutable, scope-preserving gate replay."""

import unittest

from scripts.replay_decision_gates import (
    classify_replay_gaps,
    evaluate_replay_vector,
    replay_complete_trend_w1_setup,
    replay_fixture,
)


class ReplayDecisionGateTests(unittest.TestCase):

    def test_every_false_has_scoped_reason(self):
        report = replay_fixture()
        for decision in report["decisions"]:
            if decision["allowed"]:
                continue
            self.assertIn(
                decision["scope"], {"global", "side", "candidate", "window"}
            )
            self.assertNotEqual([], decision["blocking_codes"])

    def test_workflow_gap_does_not_clear_candidates(self):
        report = replay_fixture(
            workflow_gap="canonical_style_not_finalized:2026-08-04"
        )
        self.assertGreater(len(report["recommendation_state"]["candidates"]), 0)

    def test_complete_setup_without_global_hard_gate_can_allow_action(self):
        decision = replay_complete_trend_w1_setup()
        self.assertTrue(decision["allowed"])

    def test_untyped_missing_rule_input_is_not_global_hard(self):
        classified = classify_replay_gaps(
            ["missing_rule_input:limit_up_count_avg_3d"]
        )
        self.assertEqual([], classified["global_hard"])
        self.assertIn(
            "missing_rule_input:limit_up_count_avg_3d",
            classified["unverifiable"],
        )

    def test_explicit_global_hard_still_blocks_replay(self):
        decision = evaluate_replay_vector(
            side="trend",
            global_hard=["SYSTEM_RISK"],
            window_open=True,
            setup_complete=True,
        )
        self.assertFalse(decision["allowed"])
        self.assertEqual("global", decision["scope"])
        self.assertEqual(["SYSTEM_RISK"], decision["blocking_codes"])


if __name__ == "__main__":
    unittest.main()
