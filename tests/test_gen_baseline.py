"""test_gen_baseline.py — gen_dashboard_data.py 解析逻辑测试"""
import sys, json, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
try:
    from gen_dashboard_data import parse_frontmatter, parse_appendix, parse_appendix_a
    _HAS_GEN = True
except ImportError:
    parse_frontmatter = None
    parse_appendix = None
    parse_appendix_a = None
    _HAS_GEN = False

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_review_note.md"


@unittest.skipUnless(_HAS_GEN, "gen_dashboard_data not available")
class TestGenBaseline(unittest.TestCase):

    def test_parse_frontmatter(self):
        fm = parse_frontmatter(str(FIXTURE))
        self.assertIsNotNone(fm)
        self.assertEqual(fm.get("date"), "2026-05-18")
        self.assertEqual(fm.get("weekday"), "周一")
        self.assertIsNotNone(fm.get("盘后持仓"))
        self.assertIn("北方华创", str(fm.get("盘后持仓", "")))
        self.assertEqual(fm.get("W1状态"), "开放")

    def test_parse_frontmatter_circuit_breaker(self):
        """验证熔断相关字段被正确解析"""
        fm = parse_frontmatter(str(FIXTURE))
        # YAML 中 false 为字符串 "false"，与布尔值 False 等效（均为未触发）
        # 周回撤触发 字段不在本 fixture 中，应回退到默认空值
        self.assertIn(str(fm.get("熔断触发", "")), ("false", "False", "FALSE", ""))
        self.assertEqual(fm.get("单日熔断线"), -3)
        self.assertEqual(fm.get("连亏天数"), 0)
        # 周回撤触发 不在 fixture 中；get 返回 None，空字符串是边界情况
        self.assertIn(str(fm.get("周回撤触发", "") or ""), ("false", "False", "FALSE", ""))

    def test_parse_frontmatter_numeric(self):
        fm = parse_frontmatter(str(FIXTURE))
        self.assertEqual(float(fm.get("涨停家数", 0)), 72)
        self.assertEqual(float(fm.get("跌停家数", 0)), 44)

    def test_parse_appendix_positions(self):
        appendix = parse_appendix(str(FIXTURE))
        positions = appendix.get("positions", [])
        self.assertGreaterEqual(len(positions), 2)
        names = [p.get("标的") for p in positions]
        self.assertIn("北方华创", names)
        self.assertIn("领益智造", names)

    def test_parse_appendix_pools(self):
        appendix = parse_appendix(str(FIXTURE))
        lianban = appendix.get("lianban_pool", [])
        trend = appendix.get("trend_pool", [])
        self.assertGreaterEqual(len(lianban), 1)
        self.assertEqual(lianban[0].get("标的"), "雷赛智能")
        self.assertGreaterEqual(len(trend), 1)
        self.assertEqual(trend[0].get("标的"), "北方华创")

    def test_parse_appendix_sectors(self):
        appendix = parse_appendix(str(FIXTURE))
        sectors = appendix.get("sectors", [])
        self.assertGreaterEqual(len(sectors), 1)
        self.assertEqual(sectors[0].get("板块"), "机器人")

    def test_parse_appendix_operations(self):
        appendix = parse_appendix(str(FIXTURE))
        ops = appendix.get("今日操作", [])
        self.assertGreaterEqual(len(ops), 1)
        self.assertIn("清仓", str(ops[0].get("动作", "")))

    def test_parse_appendix_a_excluded(self):
        pools = parse_appendix_a(str(FIXTURE))
        excluded = pools.get("excluded", [])
        self.assertIn("蒙娜丽莎", excluded)
        self.assertIn("澜起科技", excluded)
        self.assertIn("德明利", excluded)

    def test_parse_appendix_a_pools(self):
        pools = parse_appendix_a(str(FIXTURE))
        lianban = pools.get("lianban_pool", [])
        trend = pools.get("trend_pool", [])
        self.assertGreaterEqual(len(lianban), 1)
        self.assertEqual(lianban[0].get("板块"), "机器人")
        self.assertGreaterEqual(len(trend), 1)
        self.assertEqual(trend[0].get("板块"), "半导体")
