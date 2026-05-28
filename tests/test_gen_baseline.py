"""test_gen_baseline.py — gen_dashboard_data.py 解析逻辑测试"""
import sys, json, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
try:
    import gen_dashboard_data as _gen
    parse_frontmatter = _gen.parse_frontmatter
    parse_appendix = _gen.parse_appendix
    parse_appendix_a = _gen.parse_appendix_a
    _build_pools_payload = getattr(_gen, "_build_pools_payload", None)
    _build_pools_payload_for_trading_day = getattr(_gen, "_build_pools_payload_for_trading_day", None)
    build_dashboard_data = getattr(_gen, "build_dashboard_data", None)
    _select_machine_pool = getattr(_gen, "_select_machine_pool", None)
    _HAS_GEN = True
except ImportError:
    parse_frontmatter = None
    parse_appendix = None
    parse_appendix_a = None
    _build_pools_payload = None
    _build_pools_payload_for_trading_day = None
    build_dashboard_data = None
    _select_machine_pool = None
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

    def test_machine_pools_prefer_data_appendix_stock_rows(self):
        self.assertIsNotNone(_build_pools_payload)
        pools = _build_pools_payload(str(FIXTURE))
        self.assertEqual(pools["lianban_pool"][0].get("标的"), "雷赛智能")
        self.assertEqual(pools["lianban_pool"][0].get("代码"), "002979")
        self.assertEqual(pools["trend_pool"][0].get("标的"), "北方华创")
        self.assertEqual(pools["trend_pool"][0].get("代码"), "002371")
        self.assertNotIn("观察标的", pools["trend_pool"][0])

    def test_explicit_empty_lianban_pool_does_not_fallback(self):
        self.assertIsNotNone(_select_machine_pool)
        note = """---
date: 2026-05-27
---
# 复盘

## 附录A：次日盘前速查

### 趋势板块→操作映射
| 板块 | 观察标的（只盯） | 操作标的 | 触发条件 |
|------|---------------|---------|---------|
| 半导体 | 紫光 | 三安 | 回踩 |

### 操作指南
**不碰**：连板追涨

## 数据附录（机器解析用）

### 连板自选池
| 标的 | 代码 | 板块 | 窗口 | 角色 | 操作 | 涨幅 | 收盘价 | MA5 | 量比 | 换手 | 备注 |
|------|------|------|------|------|------|------|--------|-----|------|------|------|
|  |  |  | W1/W2 |  |  |  |  |  |  |  |  |

### 趋势自选池
| 标的 | 代码 | 板块 | 窗口 | 角色 | 操作 | 涨幅 | 收盘价 | MA5 | MA20 | 量比 | 换手 | 备注 |
|------|------|------|------|------|------|------|--------|-----|------|------|------|------|
| 三安光电 | 600703 | 半导体 | W2 | 主趋势股 | W2回踩买入 | +4.79% | 16.61 | — | — | — | 8.71% | 中军 |
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "note.md"
            path.write_text(note)
            appendix = parse_appendix(str(path))
            appendix_a = parse_appendix_a(str(path))
            lb = _select_machine_pool(str(path), appendix, appendix_a, "lianban_pool")
            tr = _select_machine_pool(str(path), appendix, appendix_a, "trend_pool")
        self.assertEqual(lb, [])
        self.assertEqual(tr[0].get("标的"), "三安光电")
        self.assertEqual(tr[0].get("代码"), "600703")

    def test_trading_day_pools_use_previous_review_note(self):
        self.assertIsNotNone(_build_pools_payload_for_trading_day)
        current_note = """---
date: 2026-05-28
---
# 今日盘中笔记

## 数据附录（机器解析用）

### 趋势自选池
| 标的 | 代码 | 板块 | 窗口 | 角色 | 操作 | 涨幅 | 收盘价 | MA5 | MA20 | 量比 | 换手 | 备注 |
|------|------|------|------|------|------|------|--------|-----|------|------|------|------|
"""
        previous_note = """---
date: 2026-05-27
---
# 昨日复盘

## 数据附录（机器解析用）

### 连板自选池
| 标的 | 代码 | 板块 | 窗口 | 角色 | 操作 | 涨幅 | 收盘价 | MA5 | 量比 | 换手 | 备注 |
|------|------|------|------|------|------|------|--------|-----|------|------|------|
|  |  |  | W1/W2 |  |  |  |  |  |  |  |  |

### 趋势自选池
| 标的 | 代码 | 板块 | 窗口 | 角色 | 操作 | 涨幅 | 收盘价 | MA5 | MA20 | 量比 | 换手 | 备注 |
|------|------|------|------|------|------|------|--------|-----|------|------|------|------|
| 紫光国微 | 002049 | 半导体 | — | 主趋势股 | 持有 | +2.54% | 85.06 | 82.13 | 79.36 | 1.45 | 9.74% | 持仓 |
| 三安光电 | 600703 | 半导体 | W2 | 主趋势股 | W2回踩买入 | +4.79% | 16.61 | — | — | — | 8.71% | 中军 |
"""
        with tempfile.TemporaryDirectory() as td:
            review_root = Path(td) / "复盘笔记" / "W22_第22周"
            review_root.mkdir(parents=True)
            current = review_root / "2026_5_28_Thursday_ReviewNote.md"
            previous = review_root / "2026_5_27_Wednesday_ReviewNote.md"
            current.write_text(current_note)
            previous.write_text(previous_note)

            pools = _build_pools_payload_for_trading_day(str(current), "2026-05-28")

        selfEqual = self.assertEqual
        selfEqual(pools.get("source_note"), "2026_5_27_Wednesday_ReviewNote.md")
        selfEqual(pools["lianban_pool"], [])
        selfEqual([s.get("标的") for s in pools["trend_pool"]], ["紫光国微", "三安光电"])

    def test_dashboard_adds_yesterday_baseline_from_previous_review(self):
        self.assertIsNotNone(build_dashboard_data)
        current_note = """---
date: 2026-05-28
weekday: 周四
---
# 今日盘中笔记

## 数据附录（机器解析用）

### 持仓明细
| 标的 | 代码 | 方向 | 数量 | 成本 | 现价 | 浮盈% | 止损 | 状态 |
|------|------|------|------|------|------|------|------|------|
"""
        previous_note = """---
date: 2026-05-27
weekday: 周三
上证指数: 4093.73
上证涨幅: -1.25
市场量能: 3.24
涨跌比: 1260 / 3890
---
# 昨日复盘

## 数据附录（机器解析用）

### 连板自选池
| 标的 | 代码 | 板块 | 窗口 | 角色 | 操作 | 涨幅 | 收盘价 | MA5 | 量比 | 换手 | 备注 |
|------|------|------|------|------|------|------|--------|-----|------|------|------|
|  |  |  | W1/W2 |  |  |  |  |  |  |  |  |
"""
        with tempfile.TemporaryDirectory() as td:
            review_root = Path(td) / "复盘笔记" / "W22_第22周"
            review_root.mkdir(parents=True)
            current = review_root / "2026_5_28_Thursday_ReviewNote.md"
            previous = review_root / "2026_5_27_Wednesday_ReviewNote.md"
            current.write_text(current_note)
            previous.write_text(previous_note)

            data = build_dashboard_data(str(current))

        yb = data.get("yesterday_baseline") or {}
        self.assertEqual(yb.get("上证昨涨幅"), "-1.25%")
        self.assertEqual(yb.get("上证昨成交额"), "3.24万亿")
        self.assertEqual(yb.get("上证昨上涨"), 1260)
        self.assertEqual(yb.get("上证昨下跌"), 3890)
