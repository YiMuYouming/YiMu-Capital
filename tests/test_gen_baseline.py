"""test_gen_baseline.py — gen_dashboard_data.py 解析逻辑测试"""
import sys, json, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
try:
    import gen_dashboard_data as _gen
    parse_frontmatter = _gen.parse_frontmatter
    parse_appendix = _gen.parse_appendix
    parse_appendix_a = _gen.parse_appendix_a
    _build_pools_payload = getattr(_gen, "_build_pools_payload", None)
    _build_pools_payload_for_trading_day = getattr(_gen, "_build_pools_payload_for_trading_day", None)
    build_dashboard_data = getattr(_gen, "build_dashboard_data", None)
    find_latest_review = getattr(_gen, "find_latest_review", None)
    _parse_premarket_plan = getattr(_gen, "_parse_premarket_plan", None)
    _select_machine_pool = getattr(_gen, "_select_machine_pool", None)
    _preserve_active_price = getattr(_gen, "_preserve_active_price", None)
    _compute_earned_cap = getattr(_gen, "_compute_earned_cap", None)
    _translate_canonical_style = getattr(_gen, "_translate_canonical_style", None)
    _apply_buy_window_precedence = getattr(_gen, "_apply_buy_window_precedence", None)
    _HAS_GEN = True
except ImportError:
    parse_frontmatter = None
    parse_appendix = None
    parse_appendix_a = None
    _build_pools_payload = None
    _build_pools_payload_for_trading_day = None
    build_dashboard_data = None
    find_latest_review = None
    _parse_premarket_plan = None
    _select_machine_pool = None
    _preserve_active_price = None
    _compute_earned_cap = None
    _translate_canonical_style = None
    _apply_buy_window_precedence = None
    _HAS_GEN = False

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_review_note.md"


@unittest.skipUnless(_HAS_GEN, "gen_dashboard_data not available")
class TestGenBaseline(unittest.TestCase):

    def test_canonical_score_30_preserves_zero_allocation(self):
        self.assertIsNotNone(_translate_canonical_style)
        translated = _translate_canonical_style({
            "schema_version": "review-style-detect.v1",
            "status": "ready",
            "formula_version": "piecewise_linear_v1",
            "dimension_weights": {"量能": 30, "连板生态": 40, "趋势赚钱效应": 30},
            "total_score": 30,
            "style": "趋势",
            "scores": {
                "维度一：量能": {"score": 9},
                "维度二：连板生态": {"score": 12},
                "维度三：趋势赚钱效应": {"score": 9},
            },
            "allocation": {"连板资金占比": 0.0, "趋势资金占比": 100.0},
            "market_trend_20d_direction": "走平",
            "highest_board": 3,
            "limit_up_count_avg_3d": 30,
            "promotion_1_to_2_pct": 18.001,
            "promotion_2_to_3_pct": 25.001,
            "promotion_3_to_4_pct": 35.001,
            "emotion_regime": "主升",
            "source_gaps": [],
        }, source="finalized_market_watch")

        self.assertEqual(translated["连板占比"], 0.0)
        self.assertEqual(translated["趋势占比"], 100.0)
        self.assertEqual(translated["连板占比"] + translated["趋势占比"], 100.0)
        self.assertEqual(translated["market_trend_20d_direction"], "走平")
        self.assertEqual(translated["highest_board"], 3)
        self.assertEqual(translated["limit_up_count_avg_3d"], 30)
        self.assertEqual(translated["promotion_1_to_2_pct"], 18.001)
        self.assertEqual(translated["promotion_2_to_3_pct"], 25.001)
        self.assertEqual(translated["promotion_3_to_4_pct"], 35.001)
        self.assertEqual(translated["emotion_regime"], "主升")

    def test_missing_canonical_facts_fail_closed_without_tradable_defaults(self):
        self.assertIsNotNone(_translate_canonical_style)
        translated = _translate_canonical_style({
            "schema_version": "review-style-detect.v1",
            "status": "blocked",
            "formula_version": "piecewise_linear_v1",
            "dimension_weights": {"量能": 30, "连板生态": 40, "趋势赚钱效应": 30},
            "total_score": None,
            "style": "blocked",
            "scores": {},
            "allocation": None,
            "source_gaps": ["缺少字段: 市场量能", "缺少字段: 上证20日线"],
        }, source="finalized_market_watch")

        self.assertIsNone(translated["总分"])
        self.assertIsNone(translated["连板占比"])
        self.assertIsNone(translated["趋势占比"])
        self.assertIsNone(translated["opportunity_cap_pct"])
        self.assertEqual(translated["source_gaps"], ["缺少字段: 市场量能", "缺少字段: 上证20日线"])
        windows = _apply_buy_window_precedence(
            {"W1状态": "开放", "W2状态": "开放"},
            style=translated,
        )
        self.assertEqual(windows["W1状态"], "关闭")
        self.assertEqual(windows["W2状态"], "关闭")

    def test_no_buy_plan_has_precedence_over_template_windows(self):
        self.assertIsNotNone(_apply_buy_window_precedence)
        for instruction in ("只卖不买", "今日不新增", "不加仓"):
            with self.subTest(instruction=instruction):
                windows = _apply_buy_window_precedence(
                    {"W1状态": "开放", "W2状态": "开放"},
                    style={"_status": "ready", "source_gaps": []},
                    execution_card={"headline": instruction},
                )
                self.assertEqual(windows["W1状态"], "关闭")
                self.assertEqual(windows["W2状态"], "关闭")
                self.assertIn("plan_no_buy", windows["close_reasons"])

    def test_local_style_script_only_translates_canonical_report(self):
        canonical = {
            "schema_version": "review-style-detect.v1",
            "status": "ready",
            "formula_version": "piecewise_linear_v1",
            "dimension_weights": {"量能": 30, "连板生态": 40, "趋势赚钱效应": 30},
            "total_score": 30,
            "style": "趋势",
            "scores": {},
            "allocation": {"连板资金占比": 0.0, "趋势资金占比": 100.0},
            "source_gaps": [],
        }
        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "style.json"
            report.write_text(json.dumps(canonical, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(_gen.STYLE_DETECT), "--canonical-report", str(report), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        translated = json.loads(result.stdout)
        self.assertEqual(translated["allocation"], canonical["allocation"])
        self.assertEqual(translated["total_score"], 30)
        source = _gen.STYLE_DETECT.read_text(encoding="utf-8")
        self.assertNotIn("def score_dim", source)

    def test_earned_cap_counts_only_profitable_mainline_positions(self):
        self.assertIsNotNone(_compute_earned_cap)
        positions = [
            {"代码": "000001", "标的": "主线A", "现价": 12, "成本": 10},
            {"代码": "000002", "标的": "主线B", "现价": 9.8, "成本": 10},
            {"代码": "000003", "标的": "非主线盈利", "现价": 20, "成本": 10},
        ]
        self.assertEqual(
            _compute_earned_cap(
                positions,
                mainline_ids={"000001", "主线A", "000002", "主线B"},
                mainline_confirmed=True,
            ),
            40,
        )

    def test_three_profitable_mainline_positions_need_protection_for_eighty(self):
        self.assertIsNotNone(_compute_earned_cap)
        positions = [
            {"代码": "000001", "现价": 12, "成本": 10},
            {"代码": "000002", "现价": 11, "成本": 10},
            {"代码": "000003", "现价": 10.5, "成本": 10},
        ]
        mainline_ids = {"000001", "000002", "000003"}
        self.assertEqual(
            _compute_earned_cap(positions, mainline_ids=mainline_ids, mainline_confirmed=True),
            60,
        )
        self.assertEqual(
            _compute_earned_cap(
                positions,
                mainline_ids=mainline_ids,
                mainline_confirmed=True,
                protection_raised=True,
            ),
            80,
        )

    def test_preserve_active_price_accepts_markdown_bold_quantity(self):
        self.assertIsNotNone(_preserve_active_price)
        old_root = _gen.ROOT_DIR
        old_output = _gen.OUTPUT_FILE
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data_dir = root / "data"
            data_dir.mkdir()
            (data_dir / "pnl_history.json").write_text(
                json.dumps({"meta": {"last_mv": 100000}}),
                encoding="utf-8",
            )
            _gen.ROOT_DIR = root
            _gen.OUTPUT_FILE = data_dir / "dashboard_data.json"
            new_data = {
                "positions": [
                    {"标的": "立讯精密", "代码": "002475", "数量": "**2000**股", "成本": 75.31, "状态": "持有"}
                ]
            }
            try:
                _preserve_active_price(new_data)
            finally:
                _gen.ROOT_DIR = old_root
                _gen.OUTPUT_FILE = old_output

        self.assertEqual(new_data["positions"][0]["现价"], 50.0)

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

    def test_parse_appendix_pools_keeps_today_action_fields(self):
        note = """---
date: 2026-06-21
---
# test

## 数据附录（机器解析用）

### 连板自选池
| 标的 | 代码 | 板块 | 今日定位 | 窗口 | 今日检查 | 触发/失效 | 涨幅 | 收盘价 | MA5 | 量比 | 换手 | 备注 |
|------|------|------|----------|------|----------|-----------|------|--------|-----|------|------|------|
| 雷赛智能 | 002979 | 机器人 | W1标的 | W1 | 封板强度 | 触发：高开3-7%；失效：炸板率>30% | +2.1% | 12.34 | 12.00 | 1.2 | 8% | 今日看封板延续 |

### 趋势自选池
| 标的 | 代码 | 板块 | 今日定位 | 窗口 | 今日检查 | 触发/失效 | 涨幅 | 收盘价 | MA5 | MA20 | 量比 | 换手 | 备注 |
|------|------|------|----------|------|----------|-----------|------|--------|-----|------|------|------|------|
| 北方华创 | 002371 | 半导体 | W2标的 | W2 | 回踩5日线 | 触发：缩量企稳；失效：放量破位 | -1.0% | 300.00 | 298.00 | 280.00 | 0.7 | 3% | 今日只看回踩确认 |
"""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(note)
            path = f.name
        try:
            appendix = parse_appendix(path)
        finally:
            Path(path).unlink(missing_ok=True)

        lianban = appendix.get("lianban_pool", [])
        trend = appendix.get("trend_pool", [])
        self.assertEqual(lianban[0].get("今日定位"), "W1标的")
        self.assertEqual(lianban[0].get("今日检查"), "封板强度")
        self.assertIn("失效", lianban[0].get("触发/失效", ""))
        self.assertEqual(trend[0].get("今日定位"), "W2标的")
        self.assertEqual(trend[0].get("今日检查"), "回踩5日线")
        self.assertIn("缩量企稳", trend[0].get("触发/失效", ""))

    def test_parse_appendix_repairs_shifted_pool_name_and_code_columns(self):
        note = """---
date: 2026-06-21
---
# test

## 数据附录（机器解析用）

### 趋势自选池
| 标的 | 代码 | 板块 | 今日定位 | 窗口 | 今日检查 | 触发/失效 | 涨幅 | 收盘价 | MA5 | MA20 | 量比 | 换手 | 备注 |
|------|------|------|----------|------|----------|-----------|------|--------|-----|------|------|------|------|
| 🟢温度标 | 国瓷材料 | 300285 | 🔬电子化学品 | **温度标** | 观察 | 主线延续信号 | +14.05% | 101.00 | 89.53 | 71.02 | 1.0 | 5% | 温度标 |
| 🟡趋势参考 | 中际旭创 | 300308 | 💻AI算力/CPO | **参考** | 走强 | 触发：走强；失效：放量破位 | +2.00% | 200.00 | 190.00 | 170.00 | 1.2 | 4% | CPO龙头 |
"""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(note)
            path = f.name
        try:
            appendix = parse_appendix(path)
        finally:
            Path(path).unlink(missing_ok=True)

        trend = appendix.get("trend_pool", [])
        self.assertEqual(trend[0].get("标的"), "国瓷材料")
        self.assertEqual(trend[0].get("代码"), "300285")
        self.assertEqual(trend[0].get("板块"), "🔬电子化学品")
        self.assertEqual(trend[0].get("池内角色"), "🟢温度标")
        self.assertEqual(trend[0].get("今日定位"), "**温度标**")
        self.assertEqual(trend[1].get("标的"), "中际旭创")
        self.assertEqual(trend[1].get("代码"), "300308")

    def test_parse_appendix_legacy_pool_rows_are_observation_only(self):
        note = """---
date: 2026-06-21
---
# test

## 数据附录

### 连板自选池
| 标的 | 代码 | 板块 | 角色 | 操作 | 涨幅 | 收盘价 | MA5 | 量比 | 换手 | 备注 |
|------|------|------|------|------|------|--------|-----|------|------|------|
| 雷赛智能 | 002979 | 机器人 | 1进2 | 追涨 | +2.1% | 12.34 | 12.00 | 1.2 | 8% | 旧表 |

### 趋势自选池
| 标的 | 代码 | 板块 | 角色 | 操作 | 涨幅 | 收盘价 | MA5 | MA20 | 量比 | 换手 | 备注 |
|------|------|------|------|------|------|--------|-----|------|------|------|------|
| 北方华创 | 002371 | 半导体 | 趋势 | W2买入 | -1.0% | 300.00 | 298.00 | 280.00 | 0.7 | 3% | 旧表 |
"""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(note)
            path = f.name
        try:
            appendix = parse_appendix(path)
        finally:
            Path(path).unlink(missing_ok=True)

        lianban = appendix.get("lianban_pool", [])[0]
        trend = appendix.get("trend_pool", [])[0]
        self.assertTrue(lianban.get("derived_from_legacy_fields"))
        self.assertEqual(lianban.get("今日定位"), "观察标")
        self.assertIn("旧字段兼容", lianban.get("今日检查", ""))
        self.assertIn("只观察", lianban.get("触发/失效", ""))
        self.assertTrue(trend.get("derived_from_legacy_fields"))
        self.assertEqual(trend.get("今日定位"), "观察标")
        self.assertIn("旧字段兼容", trend.get("今日检查", ""))
        self.assertIn("只观察", trend.get("触发/失效", ""))

    def test_parse_appendix_sectors(self):
        appendix = parse_appendix(str(FIXTURE))
        sectors = appendix.get("sectors", [])
        self.assertGreaterEqual(len(sectors), 1)
        self.assertEqual(sectors[0].get("板块"), "机器人")

    def test_parse_appendix_sector_ssot_columns(self):
        note = """---
date: 2026-05-29
---
# test

## 数据附录

### 板块状态
| 板块 | 类型 | 涨停数 | 梯队 | 龙头 | 板块涨跌幅 | 主力净流入 | 5日线位置 | 状态 |
|------|------|--------|------|------|------------|------------|-----------|------|
| 半导体 | 趋势主线 | ~10 | 2板+首板 | 中京电子 | +2.24% | +111.0亿 | 站上 | 趋势确认 |
"""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(note)
            path = f.name
        sectors = parse_appendix(path).get("sectors", [])
        self.assertEqual(sectors[0].get("板块涨跌幅"), 2.24)
        self.assertEqual(sectors[0].get("主力净流入"), "+111.0亿")
        self.assertEqual(sectors[0].get("5日线位置"), "站上")

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

    def test_current_day_operations_never_fallback_to_historical_note(self):
        self.assertIsNotNone(build_dashboard_data)
        current_note = """---
date: 2026-07-10
weekday: 周五
---
# 今日开工版

## 数据附录（机器解析用）

### 今日操作
| 时间 | 动作 | 标的 | 价格 | 盈亏 | 原因 |
|------|------|------|------|------|------|
| — | — | — | — | — | — |
"""
        previous_note = """---
date: 2026-07-09
weekday: 周四
情绪值: 60
---
# 昨日复盘

## 数据附录（机器解析用）

### 今日操作
| 时间 | 动作 | 标的 | 价格 | 盈亏 | 原因 |
|------|------|------|------|------|------|
| 14:50 | 买入5000 | 徐工机械 | 8.51 | — | 昨日成交 |
"""
        with tempfile.TemporaryDirectory() as td:
            review_root = Path(td) / "复盘笔记" / "W28_第28周"
            review_root.mkdir(parents=True)
            current = review_root / "2026_7_10_Friday_ReviewNote.md"
            previous = review_root / "2026_7_9_Thursday_ReviewNote.md"
            current.write_text(current_note, encoding="utf-8")
            previous.write_text(previous_note, encoding="utf-8")

            data = build_dashboard_data(str(current))

        self.assertEqual([], data["decision"]["今日操作"])
        self.assertEqual(
            {"source_note": current.name, "source_date": "2026-07-10", "fallback": False},
            data["meta"]["field_sources"]["今日操作"],
        )

    def test_current_market_fields_never_masquerade_as_historical_fallback(self):
        current_note = """---
date: 2026-07-10
weekday: 周五
---
# 今日开工版
"""
        previous_note = """---
date: 2026-07-09
weekday: 周四
上证指数: 4050.12
上证涨幅: 1.25
市场量能: 3.10
涨停家数: 88
跌停家数: 2
情绪值: 66
---
# 昨日复盘
"""
        with tempfile.TemporaryDirectory() as td:
            review_root = Path(td) / "复盘笔记" / "W28_第28周"
            review_root.mkdir(parents=True)
            current = review_root / "2026_7_10_Friday_ReviewNote.md"
            previous = review_root / "2026_7_9_Thursday_ReviewNote.md"
            current.write_text(current_note, encoding="utf-8")
            previous.write_text(previous_note, encoding="utf-8")

            data = build_dashboard_data(str(current))

        self.assertIsNone(data["market"]["上证指数"])
        self.assertIsNone(data["market"]["上证涨幅"])
        self.assertIsNone(data["market"]["市场量能"])
        self.assertIsNone(data["market"]["涨停家数"])
        self.assertEqual("2026-07-10", data["meta"]["field_sources"]["market"]["source_date"])
        self.assertFalse(data["meta"]["field_sources"]["market"]["fallback"])

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
深证涨幅: -0.65
深证成交额: 1.12
市场量能: 3.24
涨跌比: 1260 / 3890
---
# 昨日复盘

**午盘**
- 说明：上午总成交1.78万亿，创业板+0.21%。

**收盘**
- 说明：上证-1.25%，创业板**+1.96%**领涨。全日量能3.24万亿。

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
        self.assertEqual(yb.get("上证昨成交额"), "2.12万亿")
        self.assertEqual(yb.get("深证昨涨幅"), "-0.65%")
        self.assertEqual(yb.get("深证昨成交额"), "1.12万亿")
        self.assertEqual(yb.get("创业昨涨幅"), "+1.96%")
        self.assertEqual(yb.get("昨日午间成交额"), "1.78万亿")
        self.assertEqual(yb.get("上证昨上涨"), 1260)
        self.assertEqual(yb.get("上证昨下跌"), 3890)

    def test_dashboard_normalizes_yuan_turnover_frontmatter(self):
        self.assertIsNotNone(build_dashboard_data)
        current_note = """---
date: 2026-06-09
weekday: 周二
---
# 今日盘中笔记
"""
        previous_note = """---
date: 2026-06-08
weekday: 周一
上证涨幅: -1.70
深证涨幅: -3.22
深证成交额: 1525460900000
创业涨幅: -3.69
创业成交额: 727291600000
市场量能: 2792757000000
涨跌比: 1200 / 4100
---
# 昨日复盘
"""
        with tempfile.TemporaryDirectory() as td:
            review_root = Path(td) / "复盘笔记" / "W24_第24周"
            review_root.mkdir(parents=True)
            current = review_root / "2026_6_9_Tuesday_ReviewNote.md"
            previous = review_root / "2026_6_8_Monday_ReviewNote.md"
            current.write_text(current_note)
            previous.write_text(previous_note)

            data = build_dashboard_data(str(current))

        yb = data.get("yesterday_baseline") or {}
        self.assertEqual(yb.get("深证昨成交额"), "1.53万亿")
        self.assertEqual(yb.get("创业昨成交额"), "7273亿")
        self.assertEqual(yb.get("昨日全天成交额"), "2.79万亿")

    def test_find_latest_review_accepts_premarket_plan_note(self):
        self.assertIsNotNone(find_latest_review)
        current_note = """---
date: 2026-05-29
weekday: 周五
情绪值:
---
# 2026-05-29 周五 复盘笔记

## 第〇部分：昨日预案（5/28 附录A）

> 风格：57分 | 连板57% / 趋势43%（连板硬卡释放）
> 总仓位上限：60%（情绪54.5%主升区）
"""
        previous_note = """---
date: 2026-05-28
weekday: 周四
情绪值: 54.5
---
# 2026-05-28 周四 复盘笔记

## 数据附录（机器解析用）

### 趋势自选池
| 标的 | 代码 | 板块 | 窗口 | 角色 | 操作 | 涨幅 | 收盘价 | MA5 | MA20 | 量比 | 换手 | 备注 |
|------|------|------|------|------|------|------|--------|-----|------|------|------|------|
| 紫光国微 | 002049 | 半导体 | — | 主趋势股 | 持有 | +1.46% | 86.30 | — | — | — | — | 持仓 |
"""
        with tempfile.TemporaryDirectory() as td:
            review_root = Path(td) / "复盘笔记" / "W22_第22周"
            review_root.mkdir(parents=True)
            current = review_root / "2026_5_29_Friday_ReviewNote.md"
            previous = review_root / "2026_5_28_Thursday_ReviewNote.md"
            current.write_text(current_note)
            previous.write_text(previous_note)

            with mock.patch.object(_gen, "REVIEW_DIR", Path(td) / "复盘笔记"):
                selected = find_latest_review()

        self.assertEqual(Path(selected).name, "2026_5_29_Friday_ReviewNote.md")

    def test_find_latest_review_orders_non_zero_padded_days_by_date(self):
        note = """---
date: {date}
---
# review

## 数据附录（机器解析用）

### 趋势自选池
| 标的 | 代码 | 板块 | 今日定位 | 窗口 | 今日检查 | 触发/失效 |
|------|------|------|----------|------|----------|-----------|
| 测试股 | 000001 | 测试 | 观察标 | 观察 | 强弱 | 转弱即失效 |
"""
        with tempfile.TemporaryDirectory() as td:
            review_root = Path(td) / "复盘笔记" / "W28_第28周"
            review_root.mkdir(parents=True)
            day_9 = review_root / "2026_7_9_Thursday_ReviewNote.md"
            day_10 = review_root / "2026_7_10_Friday_ReviewNote.md"
            day_9.write_text(note.format(date="2026-07-09"))
            day_10.write_text(note.format(date="2026-07-10"))

            with mock.patch.object(_gen, "REVIEW_DIR", Path(td) / "复盘笔记"):
                selected = find_latest_review()

        self.assertEqual(Path(selected).name, "2026_7_10_Friday_ReviewNote.md")

    def test_dashboard_does_not_backfill_close_emotion_from_previous_or_auction(self):
        self.assertIsNotNone(build_dashboard_data)
        current_note = """---
date: 2026-06-10
weekday: 周三
情绪值:
竞价情绪值:
---
# 2026-06-10 周三 盘前笔记

## 情绪节点

### 表1 大盘全景
| 节点 | 情绪 | 上证(%) | 涨/跌停 | 量能 | 涨跌比 | 总竞价涨幅 | 关键异动 |
|------|------|---------|---------|------|--------|------------|----------|
| 竞价 | 12.2% | -0.4 | — | — | 600/4400 | — | 地缘冲击 |
"""
        previous_note = """---
date: 2026-06-09
weekday: 周二
情绪值: 64
---
# 2026-06-09 周二 复盘笔记
"""
        with tempfile.TemporaryDirectory() as td:
            review_root = Path(td) / "复盘笔记" / "W24_第24周"
            review_root.mkdir(parents=True)
            current = review_root / "2026_6_10_Wednesday_ReviewNote.md"
            previous = review_root / "2026_6_9_Tuesday_ReviewNote.md"
            current.write_text(current_note)
            previous.write_text(previous_note)

            with mock.patch.object(_gen, "get_style_data", return_value={}):
                data = build_dashboard_data(str(current))

        sentiment = data.get("sentiment") or {}
        self.assertIsNone(sentiment.get("情绪值"))
        self.assertEqual(sentiment.get("竞价情绪值"), 12.2)

    def test_dashboard_style_uses_premarket_plan_when_today_fm_empty(self):
        self.assertIsNotNone(build_dashboard_data)
        self.assertIsNotNone(_parse_premarket_plan)
        current_note = """---
date: 2026-05-29
weekday: 周五
情绪值:
连亏天数: 0
---
# 2026-05-29 周五 复盘笔记

## 第〇部分：昨日预案（5/28 附录A）

> 风格：57分 | 连板57% / 趋势43%（连板硬卡释放 → 实际趋势≈60%）
> 总仓位上限：60%（情绪54.5%主升区）
"""
        previous_note = """---
date: 2026-05-28
weekday: 周四
情绪值: 54.5
昨日涨停收益: 0.84
炸板率: 76.19
整体晋级率: 19.15
连板风险值: 0.3低
市场量能: 2.97
上证涨幅: +0.12
涨跌比: 2800/2335
---
# 2026-05-28 周四 复盘笔记
"""
        with tempfile.TemporaryDirectory() as td:
            review_root = Path(td) / "复盘笔记" / "W22_第22周"
            review_root.mkdir(parents=True)
            current = review_root / "2026_5_29_Friday_ReviewNote.md"
            previous = review_root / "2026_5_28_Thursday_ReviewNote.md"
            current.write_text(current_note)
            previous.write_text(previous_note)

            old_style = {
                "总分": 42, "风格": "混合（均衡）", "置信度": 55,
                "连板占比": 12, "趋势占比": 88, "总仓位上限": 20,
                "dim1_量能": 17, "dim2_连板生态": 9,
                "dim3_趋势": 9, "dim4_情绪广度": 7,
            }
            with mock.patch.object(_gen, "get_style_data", return_value=old_style):
                data = build_dashboard_data(str(current))

        style = data.get("style") or {}
        self.assertEqual(data.get("meta", {}).get("date"), "2026-05-29")
        self.assertEqual(style.get("总分"), 57)
        self.assertEqual(style.get("连板占比"), 57)
        self.assertEqual(style.get("趋势占比"), 43)
        self.assertEqual(style.get("总仓位上限"), 60)

    def test_dashboard_style_uses_appendix_a_final_plan_even_when_frontmatter_has_close_data(self):
        """盘后最终附录A是 D+1 盘前口径，应覆盖当日收盘 frontmatter 风格推导。"""
        self.assertIsNotNone(build_dashboard_data)
        current_note = """---
date: 2026-06-02
weekday: 周二
情绪值: 27.5
涨停家数: 67
炸板率: 71.43
整体晋级率: 13.33
风格分数验证: 趋势行情(76%置信)
---
# 2026-06-02 周二 复盘笔记

## 第〇部分：昨日预案

> 风格：49分 | 连板50% / 趋势50% | 总仓位上限60%

## 附录A：次日盘前速查

**状态**：终稿

### 操作指南

**总基调**：被动趋势日，连板全关，趋势池9只（含持仓2）。情绪27.5%低迷→W1不开新仓
**W2**：若趋势回踩确认+板块未破位+情绪回升→弱回踩买入候选标的
**仓位**：当前~39.8%，新开趋势W2上限~10-14%（V反检测通过时），总上限60%
"""
        with tempfile.TemporaryDirectory() as td:
            review_root = Path(td) / "复盘笔记" / "W23_第23周"
            review_root.mkdir(parents=True)
            current = review_root / "2026_6_2_Tuesday_ReviewNote.md"
            current.write_text(current_note)

            old_style = {
                "总分": 49, "风格": "混合（偏趋势）", "置信度": 53,
                "连板占比": 46, "趋势占比": 54, "总仓位上限": 40,
                "dim1_量能": 17, "dim2_连板生态": 11,
                "dim3_趋势": 14, "dim4_情绪广度": 7,
            }
            with mock.patch.object(_gen, "get_style_data", return_value=old_style):
                data = build_dashboard_data(str(current))

        style = data.get("style") or {}
        self.assertEqual(style.get("风格"), "被动趋势日")
        self.assertEqual(style.get("连板占比"), 0)
        self.assertEqual(style.get("趋势占比"), 100)
        self.assertEqual(style.get("总仓位上限"), 60)
        self.assertEqual(style.get("_source"), "appendix_a_plan")
