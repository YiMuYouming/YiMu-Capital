"""test_rule_engine.py — 规则引擎核心逻辑测试
覆盖 gen_dashboard_data.py 的 compute_style_execution 和 _compute_total_cap
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

try:
    from gen_dashboard_data import compute_style_execution, _compute_total_cap
    _HAS = True
except ImportError:
    compute_style_execution = None
    _compute_total_cap = None
    _HAS = False


@unittest.skipUnless(_HAS, "gen_dashboard_data not available")
class TestRuleEngine(unittest.TestCase):

    def test_meltdown_zeros_position(self):
        fm = {"熔断触发": True, "连亏天数": 0, "晋级率": "50", "weekday": "周三"}
        style = {"连板占比": 75, "趋势占比": 25, "总仓位上限": 30}
        result = compute_style_execution(fm, style)
        self.assertEqual(result["连板实际"], 0)
        self.assertEqual(result["趋势实际"], 0)
        self.assertEqual(result["总仓位上限"], 0)
        self.assertEqual(result["首笔上限"], 0)
        self.assertIn("熔断", result["原因"])

    def test_meltdown_string_true(self):
        fm = {"熔断触发": "true", "连亏天数": 0, "晋级率": "50", "weekday": "周三"}
        style = {"连板占比": 75, "趋势占比": 25, "总仓位上限": 30}
        result = compute_style_execution(fm, style)
        self.assertEqual(result["总仓位上限"], 0)

    def test_consecutive_loss_force_empty(self):
        fm = {"熔断触发": False, "连亏天数": 2, "晋级率": "50", "weekday": "周三"}
        style = {"连板占比": 75, "趋势占比": 25, "总仓位上限": 30}
        result = compute_style_execution(fm, style)
        self.assertEqual(result["连板实际"], 0)
        self.assertEqual(result["趋势实际"], 0)
        self.assertEqual(result["总仓位上限"], 0)
        self.assertIn("连亏", result["原因"])

    def test_consecutive_loss_3_days(self):
        fm = {"熔断触发": False, "连亏天数": 3, "晋级率": "50", "weekday": "周三"}
        style = {"连板占比": 75, "趋势占比": 25, "总仓位上限": 30}
        result = compute_style_execution(fm, style)
        self.assertEqual(result["总仓位上限"], 0)

    def test_single_loss_no_trigger(self):
        fm = {"熔断触发": False, "连亏天数": 1, "晋级率": "50", "weekday": "周三"}
        style = {"连板占比": 75, "趋势占比": 25, "总仓位上限": 30}
        result = compute_style_execution(fm, style)
        self.assertEqual(result["连板实际"], 75)
        self.assertEqual(result["总仓位上限"], 30)

    def test_friday_does_not_cap_trend_by_itself(self):
        fm = {"熔断触发": False, "连亏天数": 0, "晋级率": "50", "weekday": "周五"}
        style = {"连板占比": 75, "趋势占比": 25, "总仓位上限": 30}
        result = compute_style_execution(fm, style)
        self.assertEqual(result["趋势实际"], 25)
        self.assertNotIn("周五", result.get("原因2", ""))

    def test_friday_trend_below_cap(self):
        fm = {"熔断触发": False, "连亏天数": 0, "晋级率": "50", "weekday": "周五"}
        style = {"连板占比": 85, "趋势占比": 10, "总仓位上限": 30}
        result = compute_style_execution(fm, style)
        self.assertEqual(result["趋势实际"], 10)

    def test_no_strong_branch_cap(self):
        fm = {"熔断触发": False, "连亏天数": 0, "晋级率": "50", "weekday": "周三",
              "无强支线": "CPO/算力"}
        style = {"连板占比": 75, "趋势占比": 25, "总仓位上限": 60}
        result = compute_style_execution(fm, style)
        self.assertEqual(result["总仓位上限"], 20)
        self.assertIn("无强支线", result.get("原因2", ""))

    def test_meltdown_overrides_all(self):
        fm = {"熔断触发": True, "连亏天数": 0, "晋级率": "80", "weekday": "周三"}
        style = {"连板占比": 75, "趋势占比": 25, "总仓位上限": 60}
        result = compute_style_execution(fm, style)
        self.assertEqual(result["总仓位上限"], 0)

    def test_total_cap_strong_lianban_side(self):
        self.assertEqual(_compute_total_cap({"dim4": {"details": {"情绪值": 65}}}), 60)

    def test_total_cap_medium_lianban_side(self):
        self.assertEqual(_compute_total_cap({"dim4": {"details": {"情绪值": 25}}}), 40)

    def test_total_cap_ice_weak_trend_side(self):
        self.assertEqual(_compute_total_cap({"dim4": {"details": {"情绪值": 10}}, "dim3": {"score": 9}}), 20)

    def test_total_cap_strong_trend_side(self):
        self.assertEqual(_compute_total_cap({"dim4": {"details": {"情绪值": 85}}, "dim3": {"score": 18}}), 60)

    def test_total_cap_medium_trend_side(self):
        self.assertEqual(_compute_total_cap({"dim4": {"details": {"情绪值": 85}}, "dim3": {"score": 10}}), 40)

    def test_total_cap_default(self):
        self.assertEqual(_compute_total_cap({}), 20)
