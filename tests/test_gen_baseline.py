"""test_gen_baseline.py — gen_dashboard_data.py 解析逻辑测试"""
import sys, json, pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from gen_dashboard_data import parse_frontmatter, parse_appendix, parse_appendix_a

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_review_note.md"


def test_parse_frontmatter():
    fm = parse_frontmatter(str(FIXTURE))
    assert fm is not None
    assert fm.get("date") == "2026-05-18"
    assert fm.get("weekday") == "周一"
    assert fm.get("盘后持仓") is not None
    assert "北方华创" in str(fm.get("盘后持仓", ""))
    assert fm.get("W1状态") == "开放"
    assert str(fm.get("熔断触发")).lower() in ("false", "0")


def test_parse_frontmatter_numeric():
    fm = parse_frontmatter(str(FIXTURE))
    assert float(fm.get("涨停家数", 0)) == 72
    assert float(fm.get("跌停家数", 0)) == 44


def test_parse_appendix_positions():
    appendix = parse_appendix(str(FIXTURE))
    positions = appendix.get("positions", [])
    assert len(positions) >= 2
    names = [p.get("标的") for p in positions]
    assert "北方华创" in names
    assert "领益智造" in names


def test_parse_appendix_pools():
    appendix = parse_appendix(str(FIXTURE))
    lianban = appendix.get("lianban_pool", [])
    trend = appendix.get("trend_pool", [])
    assert len(lianban) >= 1
    assert lianban[0].get("标的") == "雷赛智能"
    assert len(trend) >= 1
    assert trend[0].get("标的") == "北方华创"


def test_parse_appendix_sectors():
    appendix = parse_appendix(str(FIXTURE))
    sectors = appendix.get("sectors", [])
    assert len(sectors) >= 1
    assert sectors[0].get("板块") == "机器人"


def test_parse_appendix_operations():
    appendix = parse_appendix(str(FIXTURE))
    ops = appendix.get("今日操作", [])
    assert len(ops) >= 1
    assert "清仓" in str(ops[0].get("动作", ""))


def test_parse_appendix_a_excluded():
    pools = parse_appendix_a(str(FIXTURE))
    excluded = pools.get("excluded", [])
    assert "蒙娜丽莎" in excluded
    assert "澜起科技" in excluded
    assert "德明利" in excluded


def test_parse_appendix_a_pools():
    pools = parse_appendix_a(str(FIXTURE))
    lianban = pools.get("lianban_pool", [])
    trend = pools.get("trend_pool", [])
    assert len(lianban) >= 1
    assert lianban[0].get("板块") == "机器人"
    assert len(trend) >= 1
    assert trend[0].get("板块") == "半导体"
