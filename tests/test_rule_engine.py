"""test_rule_engine.py — 规则引擎核心逻辑测试
覆盖 gen_dashboard_data.py 的 compute_style_execution 和 _compute_total_cap
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from gen_dashboard_data import compute_style_execution, _compute_total_cap


def test_meltdown_zeros_position():
    """规则1: 熔断触发 → 仓位归零"""
    fm = {"熔断触发": True, "连亏天数": 0, "晋级率": "50", "weekday": "周三"}
    style = {"连板占比": 75, "趋势占比": 25, "总仓位上限": 30}
    result = compute_style_execution(fm, style)
    assert result["连板实际"] == 0
    assert result["趋势实际"] == 0
    assert result["总仓位上限"] == 0
    assert result["首笔上限"] == 0
    assert "熔断" in result["原因"]


def test_meltdown_string_true():
    """熔断字段为字符串 'true' 也触发"""
    fm = {"熔断触发": "true", "连亏天数": 0, "晋级率": "50", "weekday": "周三"}
    style = {"连板占比": 75, "趋势占比": 25, "总仓位上限": 30}
    result = compute_style_execution(fm, style)
    assert result["总仓位上限"] == 0


def test_consecutive_loss_force_empty():
    """规则2: 连亏≥2天 → 强制空仓"""
    fm = {"熔断触发": False, "连亏天数": 2, "晋级率": "50", "weekday": "周三"}
    style = {"连板占比": 75, "趋势占比": 25, "总仓位上限": 30}
    result = compute_style_execution(fm, style)
    assert result["连板实际"] == 0
    assert result["趋势实际"] == 0
    assert result["总仓位上限"] == 0
    assert "连亏" in result["原因"]


def test_consecutive_loss_3_days():
    """连亏3天同样触发"""
    fm = {"熔断触发": False, "连亏天数": 3, "晋级率": "50", "weekday": "周三"}
    style = {"连板占比": 75, "趋势占比": 25, "总仓位上限": 30}
    result = compute_style_execution(fm, style)
    assert result["总仓位上限"] == 0


def test_single_loss_no_trigger():
    """连亏1天不触发空仓"""
    fm = {"熔断触发": False, "连亏天数": 1, "晋级率": "50", "weekday": "周三"}
    style = {"连板占比": 75, "趋势占比": 25, "总仓位上限": 30}
    result = compute_style_execution(fm, style)
    assert result["连板实际"] == 75
    assert result["总仓位上限"] == 30


def test_friday_trend_cap():
    """规则3: 周五趋势占比上限15%"""
    fm = {"熔断触发": False, "连亏天数": 0, "晋级率": "50", "weekday": "周五"}
    style = {"连板占比": 75, "趋势占比": 25, "总仓位上限": 30}
    result = compute_style_execution(fm, style)
    assert result["趋势实际"] == 15
    assert "周五" in result["原因2"]


def test_friday_trend_below_cap():
    """周五但趋势占比已低于15%，不调整"""
    fm = {"熔断触发": False, "连亏天数": 0, "晋级率": "50", "weekday": "周五"}
    style = {"连板占比": 85, "趋势占比": 10, "总仓位上限": 30}
    result = compute_style_execution(fm, style)
    assert result["趋势实际"] == 10


def test_no_strong_branch_cap():
    """规则4: 无强支线 → 仓位上限≤20%"""
    fm = {"熔断触发": False, "连亏天数": 0, "晋级率": "50", "weekday": "周三",
          "无强支线": "CPO/算力"}
    style = {"连板占比": 75, "趋势占比": 25, "总仓位上限": 60}
    result = compute_style_execution(fm, style)
    assert result["总仓位上限"] == 20
    assert "无强支线" in result["原因2"]


def test_meltdown_overrides_all():
    """熔断优先级最高：即使其他条件正常也归零"""
    fm = {"熔断触发": True, "连亏天数": 0, "晋级率": "80", "weekday": "周三"}
    style = {"连板占比": 75, "趋势占比": 25, "总仓位上限": 60}
    result = compute_style_execution(fm, style)
    assert result["总仓位上限"] == 0


def test_total_cap_80():
    assert _compute_total_cap({"total": 80}) == 60


def test_total_cap_60():
    assert _compute_total_cap({"total": 60}) == 50


def test_total_cap_40():
    assert _compute_total_cap({"total": 40}) == 40


def test_total_cap_20():
    assert _compute_total_cap({"total": 20}) == 20


def test_total_cap_10():
    assert _compute_total_cap({"total": 10}) == 10


def test_total_cap_default():
    # default total=50 → falls into >=40 branch → returns 40
    assert _compute_total_cap({}) == 40
