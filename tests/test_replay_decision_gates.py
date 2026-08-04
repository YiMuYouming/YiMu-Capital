"""Regression tests for the immutable, scope-preserving gate replay."""

import unittest

from scripts.replay_decision_gates import (
    build_day_report,
    classify_replay_gaps,
    evaluate_replay_vector,
    replay_complete_trend_w1_setup,
    replay_fixture,
)


class ReplayDecisionGateTests(unittest.TestCase):

    ATTRIBUTION_CLASSES = {
        "data_source_unavailable",
        "artifact_missing",
        "candidate_evidence_missing",
        "recorded_no_setup",
        "strategy_block",
        "paper_only",
        "executable",
    }

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

    def test_daily_and_candidate_attribution_is_explicit_and_traceable(self):
        day = build_day_report("2026-08-04")
        self.assertIn(day["day_attribution"]["classification"], self.ATTRIBUTION_CLASSES)
        self.assertEqual(
            len(day["candidate_decisions"]),
            sum(day["attribution_counts"].values()),
        )
        candidate = next(
            item for item in day["candidate_decisions"] if item["code"] == "000815"
        )
        self.assertIn(candidate["classification"], self.ATTRIBUTION_CLASSES)
        self.assertEqual("recorded_no_setup", candidate["classification"])
        self.assertIn("setup", candidate["evidence_gaps"])
        self.assertIn("trigger", candidate["evidence_gaps"])
        self.assertTrue(candidate["source_trace"])

    def test_missing_closure_is_artifact_missing_not_synthetic_no_setup(self):
        day = build_day_report("2026-07-24")
        self.assertEqual("artifact_missing", day["day_attribution"]["classification"])
        self.assertEqual(0, day["attribution_counts"]["artifact_missing"])
        self.assertEqual([], day["candidate_decisions"])

    def test_summary_attributions_partition_candidates_and_days(self):
        summary = replay_fixture()["summary"]
        self.assertEqual(
            summary["decision_count"],
            sum(summary["attribution_counts"].values()),
        )
        self.assertEqual(
            summary["trading_days"],
            sum(summary["day_attribution_counts"].values()),
        )


if __name__ == "__main__":
    unittest.main()
