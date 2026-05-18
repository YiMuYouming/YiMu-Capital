"""test_pnl_calc.py — P&L 计算模块测试（NAV 链 / 回撤 / 日收益率）"""
import sys, pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from pnl_calc import calc_nav_chain, calc_max_drawdown, daily_return_from_snapshots


def test_nav_chain_basic():
    returns = [1.0, -0.5, 2.0]
    navs = calc_nav_chain(returns, base_nav=1.0)
    assert len(navs) == 4  # base + 3 days
    assert navs[0] == 1.0
    assert round(navs[1], 6) == 1.01      # 1.0 * 1.01
    assert round(navs[2], 6) == 1.00495   # 1.01 * 0.995
    assert round(navs[3], 6) == 1.025049  # 1.00495 * 1.02


def test_nav_chain_flat():
    navs = calc_nav_chain([0, 0, 0], base_nav=2.0)
    assert navs == [2.0, 2.0, 2.0, 2.0]


def test_nav_chain_empty():
    navs = calc_nav_chain([])
    assert navs == [1.0]


def test_max_drawdown_no_loss():
    navs = [1.0, 1.01, 1.02, 1.03]
    dd, start, end = calc_max_drawdown(navs)
    assert dd == 0


def test_max_drawdown_with_loss():
    navs = [1.0, 1.02, 0.98, 1.01]
    dd, start, end = calc_max_drawdown(navs)
    assert dd > 0
    # peak=1.02 at index 1, trough=0.98 at index 2, dd=(1.02-0.98)/1.02*100≈3.92
    assert round(dd, 1) == 3.9


def test_calc_nav_chain_precision():
    # 大数测试连乘精度
    returns = [0.05] * 100
    navs = calc_nav_chain(returns, base_nav=100.0)
    expected_final = 100.0 * (1.0005) ** 100
    assert abs(navs[-1] - expected_final) < 0.01


def test_calc_nav_chain_negative_returns():
    returns = [-3.0, -5.0, -2.0]
    navs = calc_nav_chain(returns, base_nav=1.0)
    assert navs[1] == 0.97
    assert navs[2] == 0.9215
    assert round(navs[3], 6) == 0.90307
