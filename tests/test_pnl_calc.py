"""test_pnl_calc.py — P&L 计算模块测试（NAV 链 / 回撤 / 日收益率）"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
try:
    from pnl_calc import calc_nav_chain, calc_max_drawdown, daily_return_from_snapshots
    _HAS = True
except ImportError:
    calc_nav_chain = None
    calc_max_drawdown = None
    daily_return_from_snapshots = None
    _HAS = False


@unittest.skipUnless(_HAS, "pnl_calc not available")
class TestPnlCalc(unittest.TestCase):

    def test_nav_chain_basic(self):
        returns = [1.0, -0.5, 2.0]
        navs = calc_nav_chain(returns, base_nav=1.0)
        self.assertEqual(len(navs), 4)
        self.assertEqual(navs[0], 1.0)
        self.assertAlmostEqual(navs[1], 1.01, places=5)
        self.assertAlmostEqual(navs[2], 1.00495, places=5)
        self.assertAlmostEqual(navs[3], 1.025049, places=5)

    def test_nav_chain_flat(self):
        navs = calc_nav_chain([0, 0, 0], base_nav=2.0)
        self.assertEqual(navs, [2.0, 2.0, 2.0, 2.0])

    def test_nav_chain_empty(self):
        navs = calc_nav_chain([])
        self.assertEqual(navs, [1.0])

    def test_max_drawdown_no_loss(self):
        navs = [1.0, 1.01, 1.02, 1.03]
        dd, start, end = calc_max_drawdown(navs)
        self.assertEqual(dd, 0)

    def test_max_drawdown_with_loss(self):
        navs = [1.0, 1.02, 0.98, 1.01]
        dd, start, end = calc_max_drawdown(navs)
        self.assertGreater(dd, 0)
        self.assertAlmostEqual(dd, 3.9, places=1)

    def test_calc_nav_chain_precision(self):
        returns = [0.05] * 100
        navs = calc_nav_chain(returns, base_nav=100.0)
        expected_final = 100.0 * (1.0005) ** 100
        self.assertLess(abs(navs[-1] - expected_final), 0.01)

    def test_calc_nav_chain_negative_returns(self):
        returns = [-3.0, -5.0, -2.0]
        navs = calc_nav_chain(returns, base_nav=1.0)
        self.assertEqual(navs[1], 0.97)
        self.assertEqual(navs[2], 0.9215)
        self.assertAlmostEqual(navs[3], 0.90307, places=5)
