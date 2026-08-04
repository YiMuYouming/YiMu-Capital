"""test_rule_state_api.py — bridge rule_state 契约测试 (Gate 1A)

验证：/api/live/quotes 含 rule_state、SSE 含 rule_state、
_build_full_snapshot 含 rule_state、小数百分数转换、
新增 SSOT 读取的连接释放。
全量隔离：tempfile + mock CACHE，不读/写真实 data/。
"""
import io
import hashlib
import json
import threading
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import scripts.db as db
import scripts.bridge as bridge


class RuleStateBridgeContractTest(unittest.TestCase):
    """bridge 输出契约回归"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        self.orig_inited = bridge._db_inited
        self.orig_root = bridge.ROOT
        self.orig_data = bridge.DATA_FILE
        self.orig_llm = bridge.LLM_INSIGHTS_FILE
        db.DB_PATH = self.tmp_dir / "test.db"
        db._local = threading.local()
        bridge._db_inited = False
        bridge.ROOT = self.tmp_dir
        # 隔离所有真实文件路径
        self.tmp_dashboard = self.tmp_dir / "dashboard_data.json"
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-27"},"market":{},"sentiment":{"二进三晋级率近3日均值":26.966667},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{},"pnl":{},"style":{"总分":59,"连板占比":54,"趋势占比":46}}'
        )
        bridge.DATA_FILE = self.tmp_dashboard
        bridge.LLM_INSIGHTS_FILE = self.tmp_dir / "llm_insights.json"
        db.init_db()

        today = datetime.now().strftime("%Y-%m-%d")
        db.insert_account_baseline({
            "date": today, "effective_at": f"{today}T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 100000,
            "total_deposit": 100000, "positions": [], "source": "recovery",
        })

        bridge.CACHE["iwencai"] = {
            "情绪值": 65,
            "昨日涨停收益": 3.0,
            "晋级率": 0.198,
            "炸板率": 0.758,
            "_updated": "2026-05-27T09:40:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {
            "_updated": "2026-05-27T09:39:00+08:00",
        }
        bridge.CACHE["live_index"] = {}
        bridge.CACHE["breadth"] = {}
        bridge.CACHE["hot_list"] = {}

    def tearDown(self):
        bridge.CACHE.clear()
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        bridge._db_inited = self.orig_inited
        bridge.ROOT = self.orig_root
        bridge.DATA_FILE = self.orig_data
        bridge.LLM_INSIGHTS_FILE = self.orig_llm
        self.tmp.cleanup()

    def test_rule_state_function_exists(self):
        """_build_rule_state 可调用且返回契约字段"""
        state = bridge._build_rule_state(now=datetime(2026, 5, 27, 9, 40))
        self.assertEqual(state["version"], "g1a-v1")
        self.assertIn("tradable", state)
        self.assertIn("windows", state)

    def test_cache_decimal_rates_are_converted_to_percent(self):
        """CACHE 中晋级率 0.198、炸板率 0.758 转为百分数 19.8/75.8"""
        state = bridge._build_rule_state(now=datetime(2026, 5, 27, 9, 40))
        codes = [b["code"] for b in state["blocks"]]
        # 75.8% > 30% → W1_BROKEN_BOARD 应触发
        self.assertIn("W1_BROKEN_BOARD", codes,
                      "炸板率 0.758 应转为 75.8% 并触发 W1_BROKEN_BOARD")
        # 晋级率 19.8%，emotion=65 >=40 → min=18，通过
        self.assertNotIn("W1_PROMOTION", codes,
                         "晋级率 0.198 → 19.8% 应通过 ≥18 阈值")

    def test_cache_string_rates_are_normalized_before_comparison(self):
        """CACHE 中晋级率/炸板率可能是字符串，比较前必须先转数值"""
        bridge.CACHE["iwencai"].update({
            "晋级率": "0.198",
            "炸板率": "75.8%",
        })

        state = bridge._build_rule_state(now=datetime(2026, 5, 27, 9, 40))
        codes = [b["code"] for b in state["blocks"]]

        self.assertIn("W1_BROKEN_BOARD", codes)
        self.assertNotIn("W1_PROMOTION", codes)

    def test_zero_style_values_are_preserved(self):
        """总分=0、连板占比=0、趋势占比=0 不因 or 回退成 50"""
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-27"},"market":{},"sentiment":{"二进三晋级率近3日均值":26.966667},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{},"pnl":{},"style":{"总分":0,"连板占比":0,"趋势占比":0}}'
        )
        state = bridge._build_rule_state(now=datetime(2026, 5, 27, 9, 40))
        # Vault 三层后，基础仓位由连板/趋势侧上限取 max，不再由总分直接映射。
        self.assertEqual(state["caps"]["base_total_pct"], 60)
        self.assertEqual(state["caps"]["lianban_pct"], 0)
        self.assertEqual(state["caps"]["trend_pct"], 0)

    def test_vault_three_layer_caps_release_ice_lianban_to_trend(self):
        """Vault 三层：冰点连板侧关闭，趋势侧弱趋势 20%，连板资金释放给趋势"""
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-27"},"market":{},"sentiment":{"二进三晋级率近3日均值":26.966667},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{"连亏天数":0},"pnl":{},'
            '"style":{"总分":42,"连板占比":12,"趋势占比":88,"dim3_趋势":9,'
            '"market_trend_20d_direction":"走平"}}'
        )
        bridge.CACHE["iwencai"] = {
            "情绪值": 17.1, "昨日涨停收益": 1.03,
            "晋级率": 0.1739, "炸板率": 0.20,
            "_updated": "2026-05-27T09:40:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {"_updated": "2026-05-27T09:40:00+08:00"}

        state = bridge._build_rule_state(now=datetime(2026, 5, 27, 9, 40))

        self.assertEqual(state["caps"]["base_total_pct"], 20)
        self.assertEqual(state["caps"]["total_pct"], 20)
        self.assertEqual(state["caps"]["lianban_pct"], 0)
        self.assertEqual(state["caps"]["trend_pct"], 100)

    def test_rule_state_builds_earned_cap_from_account_positions(self):
        """_build_rule_state 应从账户 SSOT 持仓浮盈推导盈利解锁仓位"""
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-27"},"market":{},"sentiment":{"二进三晋级率近3日均值":26.966667},'
            '"lianban_pool":[],"trend_pool":[{"代码":"000001","标的":"主线A"}],"positions":[],"decision":{},'
            '"sectors":[],"risk":{"连亏天数":0},"pnl":{},'
            '"style":{"总分":62,"连板占比":0,"趋势占比":100,"dim3_趋势":18}}'
        )
        bridge.CACHE["breadth"] = {
            "上涨家数": 1500,
            "下跌家数": 3500,
            "_source": "iwencai",
            "_updated": "2026-05-27T09:40:00+08:00",
        }
        account_state = {
            "pnl_pct": 0.5,
            "valuation_complete": True,
            "mv": 30000,
            "total_asset": 100000,
            "positions": [
                {
                    "代码": "000001", "标的": "主线A", "数量": 1000,
                    "成本": 10, "现价": 12, "市值": 12000,
                    "total_pnl_pct": 20.0,
                },
                {
                    "代码": "000002", "标的": "主线B", "数量": 1000,
                    "成本": 10, "现价": 9.8, "市值": 9800,
                    "total_pnl_pct": -2.0,
                },
            ],
        }

        state = bridge._build_rule_state(
            now=datetime(2026, 5, 27, 9, 40),
            account_state=account_state,
        )

        caps = state["caps"]
        self.assertEqual(caps["position_control_mode"], "earned_mainline")
        self.assertEqual(caps["current_position_pct"], 30)
        self.assertEqual(caps["profitable_mainline_positions"], 1)
        self.assertEqual(caps["earned_cap_pct"], 40)
        self.assertEqual(caps["opportunity_cap_pct"], 60)
        self.assertEqual(caps["total_pct"], 40)
        self.assertEqual(caps["available_add_pct"], 10)
        self.assertTrue(caps["market_breadth_polarization"])
        self.assertEqual(
            caps["profitable_mainline_position_details"],
            [{"code": "000001", "name": "主线A", "pnl_pct": 20}],
        )

    def test_rule_state_does_not_count_unmatched_profit_as_mainline_profit(self):
        """强主线环境下，未匹配主线池/锚定股的盈利持仓不得解锁主线仓位"""
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-27"},"market":{},"sentiment":{"二进三晋级率近3日均值":26.966667},'
            '"lianban_pool":[],"trend_pool":[{"代码":"000777","标的":"真正主线"}],"positions":[],"decision":{},'
            '"sectors":[],"risk":{"连亏天数":0},"pnl":{},'
            '"style":{"总分":62,"连板占比":0,"趋势占比":100,"dim3_趋势":18}}'
        )
        account_state = {
            "pnl_pct": 0.5,
            "valuation_complete": True,
            "mv": 12000,
            "total_asset": 100000,
            "positions": [
                {
                    "代码": "000001", "标的": "非主线盈利", "数量": 1000,
                    "成本": 10, "现价": 12, "市值": 12000,
                    "total_pnl_pct": 20.0, "is_mainline": "false",
                },
            ],
        }

        state = bridge._build_rule_state(
            now=datetime(2026, 5, 27, 9, 40),
            account_state=account_state,
        )

        caps = state["caps"]
        self.assertEqual(caps["position_control_mode"], "earned_mainline")
        self.assertTrue(caps["mainline_confirmed"])
        self.assertEqual(caps["profitable_mainline_positions"], 0)
        self.assertEqual(caps["earned_cap_pct"], 20)
        self.assertEqual(caps["total_pct"], 20)
        self.assertEqual(
            caps["profitable_non_mainline_position_details"],
            [{"code": "000001", "name": "非主线盈利", "pnl_pct": 20}],
        )

    def test_vault_loss_streak_overrides_base_cap_to_zero(self):
        """Vault 第一层：连亏 >=2 天最终总仓位归零"""
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-27"},"market":{},"sentiment":{"二进三晋级率近3日均值":26.966667},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{"连亏天数":2},"pnl":{},'
            '"style":{"总分":42,"连板占比":12,"趋势占比":88,"dim3_趋势":9,'
            '"market_trend_20d_direction":"走平"}}'
        )
        bridge.CACHE["iwencai"] = {
            "情绪值": 17.1, "昨日涨停收益": 1.03,
            "晋级率": 0.1739, "炸板率": 0.20,
            "_updated": "2026-05-27T09:40:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {"_updated": "2026-05-27T09:40:00+08:00"}

        state = bridge._build_rule_state(now=datetime(2026, 5, 27, 9, 40))

        self.assertEqual(state["caps"]["base_total_pct"], 20)
        self.assertEqual(state["caps"]["total_pct"], 0)
        self.assertIn("LOSS_STREAK", [b["code"] for b in state["blocks"]])

    def test_ice_w1_polarized_mainline_only_enters_manual_review(self):
        """情绪<35 的极化主线强回踩只给 W1 黄灯，不放开 buy_allowed"""
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-06-24"},"market":{},"sentiment":{"二进三晋级率近3日均值":26.966667},'
            '"lianban_pool":[],"trend_pool":[{"代码":"688041","标的":"海光信息"}],'
            '"positions":[],"decision":{},"sectors":[],"risk":{"连亏天数":0},"pnl":{},'
            '"style":{"总分":62,"连板占比":0,"趋势占比":100,"dim3_趋势":18}}'
        )
        bridge.CACHE["iwencai"] = {
            "情绪值": 25.6,
            "昨日涨停收益": 3.0,
            "晋级率": 0.20,
            "炸板率": 0.20,
            "_updated": "2026-06-24T09:58:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {"_updated": "2026-06-24T09:58:00+08:00"}

        state = bridge._build_rule_state(
            now=datetime(2026, 6, 24, 9, 58),
            account_state={"pnl_pct": 0.8, "valuation_complete": True, "mv": 30000, "total_asset": 100000},
            manual_review_context={
                "market_breadth_polarization": True,
                "mainline_confirmed": True,
                "mainline_strength": "strong",
                "sector_fund_flow": 31300000000,
                "core_stock_confirmation": True,
                "profitable_mainline_positions": 1,
                "pullback_confirmed": True,
                "intraday_stabilization": True,
                "current_price_distance_pct": 1.2,
            },
        )

        w1 = state["windows"]["w1"]
        self.assertIn("WIN-ICE-W1-001", w1["blocks"])
        self.assertFalse(w1["buy_allowed"])
        self.assertTrue(w1["manual_review_allowed"])
        self.assertIn("WIN-ICE-POLAR-MAINLINE-001", w1["manual_review_rules"])
        self.assertIn("WIN-ICE-POLAR-MAINLINE-001", [w["code"] for w in state["warnings"]])

    def test_ice_w1_without_pullback_stays_blocked_without_manual_review(self):
        """极化主线缺少回踩确认时，不进入 W1 黄灯"""
        bridge.CACHE["iwencai"] = {
            "情绪值": 25.6,
            "昨日涨停收益": 3.0,
            "晋级率": 0.20,
            "炸板率": 0.20,
            "_updated": "2026-06-24T09:58:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {"_updated": "2026-06-24T09:58:00+08:00"}

        state = bridge._build_rule_state(
            now=datetime(2026, 6, 24, 9, 58),
            account_state={"pnl_pct": 0.8, "valuation_complete": True, "mv": 30000, "total_asset": 100000},
            manual_review_context={
                "market_breadth_polarization": True,
                "mainline_confirmed": True,
                "core_stock_confirmation": True,
                "pullback_confirmed": False,
                "intraday_stabilization": True,
                "current_price_distance_pct": 1.2,
            },
        )

        w1 = state["windows"]["w1"]
        self.assertIn("WIN-ICE-W1-001", w1["blocks"])
        self.assertFalse(w1["buy_allowed"])
        self.assertFalse(w1["manual_review_allowed"])
        self.assertNotIn("WIN-ICE-POLAR-MAINLINE-001", w1["manual_review_rules"])

    def test_ice_w1_manual_review_context_can_come_from_dashboard_data(self):
        """生产路径从 dashboard_data manual_review_context 读取黄灯证据"""
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-06-24"},"market":{},"sentiment":{"二进三晋级率近3日均值":26.966667},'
            '"lianban_pool":[],"trend_pool":[{"代码":"688041","标的":"海光信息"}],'
            '"positions":[],"decision":{},"sectors":[],"risk":{"连亏天数":0},"pnl":{},'
            '"style":{"总分":62,"连板占比":0,"趋势占比":100,"dim3_趋势":18},'
            '"manual_review_context":{'
            '"mainline_strength":"strong","core_stock_confirmation":true,'
            '"pullback_confirmed":true,"intraday_stabilization":true,'
            '"current_price_distance_pct":1.2}}'
        )
        bridge.CACHE["iwencai"] = {
            "情绪值": 25.6,
            "昨日涨停收益": 3.0,
            "晋级率": 0.20,
            "炸板率": 0.20,
            "_updated": "2026-06-24T09:58:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {"_updated": "2026-06-24T09:58:00+08:00"}
        bridge.CACHE["breadth"] = {
            "上涨家数": 1200,
            "下跌家数": 3800,
            "_source": "iwencai",
            "_updated": "2026-06-24T09:58:00+08:00",
        }

        state = bridge._build_rule_state(
            now=datetime(2026, 6, 24, 9, 58),
            account_state={"pnl_pct": 0.8, "valuation_complete": True, "mv": 30000, "total_asset": 100000},
        )

        self.assertFalse(state["windows"]["w1"]["buy_allowed"])
        self.assertTrue(state["windows"]["w1"]["manual_review_allowed"])

    def test_premarket_plan_turns_loss_streak_into_warning(self):
        """盘前预案明确给出仓位时，自动连亏计数只提示不覆盖预案"""
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-29"},"market":{"炸板率":20},"sentiment":{'
            '"情绪值":65,"昨日涨停收益":3.0,"晋级率":25,"二进三晋级率近3日均值":26.966667},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{"连亏天数":2},"pnl":{},'
            '"time_window":{"W1状态":"开放","W2状态":"开放"},'
            '"style":{"总分":57,"连板占比":57,"趋势占比":43,"dim3_趋势":16,'
            '"总仓位上限":60,"_source":"premarket_plan"}}'
        )
        bridge.CACHE["iwencai"] = {
            "情绪值": 65,
            "昨日涨停收益": 3.0,
            "晋级率": 0.25,
            "炸板率": 0.20,
            "_updated": "2026-05-29T09:40:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {"_updated": "2026-05-29T09:40:00+08:00"}

        state = bridge._build_rule_state(now=datetime(2026, 5, 29, 9, 40))

        self.assertEqual(state["caps"]["base_total_pct"], 60)
        self.assertEqual(state["caps"]["opportunity_cap_pct"], 60)
        self.assertEqual(state["caps"]["earned_cap_pct"], 20)
        self.assertEqual(state["caps"]["total_pct"], 20)
        self.assertNotIn("LOSS_STREAK", [b["code"] for b in state["blocks"]])
        self.assertIn("LOSS_STREAK", [w["code"] for w in state["warnings"]])

    def test_appendix_a_plan_turns_loss_streak_into_warning(self):
        """附录A终稿明确给出次日仓位时，连亏计数只提示不覆盖预案"""
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-06-02"},"market":{"炸板率":71.43},"sentiment":{'
            '"情绪值":27.5,"昨日涨停收益":0.78,"晋级率":13.33},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{"连亏天数":2},"pnl":{},'
            '"time_window":{"W1状态":"开放","W2状态":"开放"},'
            '"style":{"总分":49,"风格":"被动趋势日","连板占比":0,"趋势占比":100,'
            '"dim3_趋势":14,"总仓位上限":60,"_source":"appendix_a_plan"}}'
        )
        bridge.CACHE["iwencai"] = {"_updated": "2026-06-03T08:40:00+08:00"}
        bridge.CACHE["live_quotes"] = {"_updated": "2026-06-03T08:40:00+08:00"}

        state = bridge._build_rule_state(now=datetime(2026, 6, 3, 8, 40))

        self.assertNotIn("LOSS_STREAK", [b["code"] for b in state["blocks"]])
        self.assertIn("LOSS_STREAK", [w["code"] for w in state["warnings"]])

    def test_live_iwencai_missing_emotion_does_not_fall_back_to_baseline_emotion(self):
        """盘中 iwencai 缺情绪值时不得用昨日 baseline 情绪值伪装实时情绪"""
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-27"},"market":{"炸板率":86.36},"sentiment":{'
            '"情绪值":17.1,"昨日涨停收益":1.03,"晋级率":17.39},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{"连亏天数":0},"pnl":{},'
            '"style":{"总分":42,"连板占比":12,"趋势占比":88,"dim3_趋势":9}}'
        )
        bridge.CACHE["iwencai"] = {
            "昨日涨停收益": 1.03,
            "晋级率": 0.1739,
            "炸板率": 0.8636,
            "_updated": "2026-05-27T09:40:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {"_updated": "2026-05-27T09:40:00+08:00"}
        bridge.CACHE["breadth"] = {
            "0~3%": 1957,
            "-0~-3%": 3150,
            "_total": 5107,
            "_source": "live_index_fallback",
            "_updated": "2026-05-27T09:40:00+08:00",
        }

        state = bridge._build_rule_state(now=datetime(2026, 5, 27, 9, 40))

        stale = [b for b in state["blocks"] if b["code"] == "SENTIMENT_STALE"]
        self.assertTrue(stale, f"缺实时情绪值应阻断而不是回退昨日 baseline: {state}")
        self.assertIn("emotion_pct", stale[0]["evidence"].get("missing", []))
        self.assertEqual(state["market_regime"], "unknown")
        self.assertNotIn("DOUBLE_ICE", [b["code"] for b in state["blocks"]])

    def test_live_iwencai_emotion_has_priority_over_live_index_fallback_breadth(self):
        """实时 iwencai 情绪值优先于 live_index_fallback 涨跌家数回退"""
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-06-09"},"market":{"炸板率":0},"sentiment":{'
            '"情绪值":12.2,"昨日涨停收益":1.84,"晋级率":19.18,"二进三晋级率近3日均值":26.966667},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{"连亏天数":0},"pnl":{},'
            '"style":{"总分":41,"连板占比":51,"趋势占比":49,"dim3_趋势":10}}'
        )
        bridge.CACHE["iwencai"] = {
            "情绪值": 38.0,
            "昨日涨停收益": 2.4,
            "晋级率": 0.20,
            "炸板率": 0.10,
            "_updated": "2026-06-09T09:40:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {"_updated": "2026-06-09T09:40:00+08:00"}
        bridge.CACHE["breadth"] = {
            "上涨家数": 1957,
            "下跌家数": 3150,
            "_source": "live_index_fallback",
            "_updated": "2026-06-09T09:40:00+08:00",
        }

        state = bridge._build_rule_state(now=datetime(2026, 6, 9, 9, 40))

        self.assertNotIn("DOUBLE_ICE", [b["code"] for b in state["blocks"]])
        self.assertEqual(state["market_regime"], "低迷")
        self.assertNotIn("SENTIMENT_STALE", [b["code"] for b in state["blocks"]])
        self.assertNotIn("W1_EMOTION", [b["code"] for b in state["blocks"]])

    def test_live_index_breadth_derives_emotion_when_iwencai_emotion_missing(self):
        """云端无 PyTDX 时，fresh live_index 上涨/下跌家数可作为实时情绪主源兜底"""
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-06-10"},"market":{},"sentiment":{"二进三晋级率近3日均值":26.966667},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{"连亏天数":0},"pnl":{},'
            '"style":{"总分":59,"连板占比":0,"趋势占比":100,"dim3_趋势":16}}'
        )
        bridge.CACHE["iwencai"] = {
            "昨日涨停收益": 3.0,
            "晋级率": 0.22,
            "炸板率": 0.20,
            "_updated": "2026-06-10T09:40:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {"_updated": "2026-06-10T09:40:00+08:00"}
        bridge.CACHE["live_index"] = {
            "上涨家数": 1293,
            "下跌家数": 3724,
            "_updated": "2026-06-10T09:40:00+08:00",
            "_source": "eastmoney_fallback",
        }
        bridge.CACHE["breadth"] = {}

        state = bridge._build_rule_state(now=datetime(2026, 6, 10, 9, 40))

        codes = [b["code"] for b in state["blocks"]]
        self.assertNotIn("SENTIMENT_STALE", codes)
        self.assertEqual(state["market_regime"], "低迷")
        w1_ice = [b for b in state["blocks"] if b["code"] == "WIN-ICE-W1-001"]
        self.assertTrue(w1_ice, f"情绪<35应继续阻断 W1，而不是数据缺失: {state}")
        self.assertAlmostEqual(w1_ice[0]["evidence"].get("emotion_pct"), 25.8, places=1)

    def test_invalid_iwencai_up_down_emotion_is_sanitized(self):
        """iwencai 上涨侧/下跌侧任一为0时，派生情绪值不可用"""
        dirty = {
            "情绪值": 0.0,
            "_emotion_source": "iwencai_up_down",
            "_emotion_counts": {"up": 0, "down": 2907},
            "_updated": "2026-06-09T09:49:06+08:00",
        }

        cleaned = bridge._sanitize_iwencai_cache_entry(dirty)

        self.assertNotIn("情绪值", cleaned)
        self.assertNotIn("_emotion_source", cleaned)
        self.assertNotIn("_emotion_counts", cleaned)

    def test_weekly_and_monthly_drawdown_are_global_stops(self):
        """Vault 第一层：周回撤>6%、月回撤>10% 都是全局停止"""
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-27"},"market":{"炸板率":20},"sentiment":{'
            '"情绪值":65,"昨日涨停收益":3.0,"晋级率":25,"二进三晋级率近3日均值":26.966667},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{"连亏天数":0,"周累计回撤":-6.1,"月累计回撤":-10.1},'
            '"pnl":{},"style":{"总分":60,"连板占比":60,"趋势占比":40,"dim3_趋势":12}}'
        )
        bridge.CACHE["iwencai"] = {"_updated": "2026-05-27T09:40:00+08:00"}
        bridge.CACHE["live_quotes"] = {"_updated": "2026-05-27T09:40:00+08:00"}

        state = bridge._build_rule_state(now=datetime(2026, 5, 27, 9, 40))
        codes = [b["code"] for b in state["blocks"]]

        self.assertIn("WEEK_STOP", codes)
        self.assertIn("MONTH_STOP", codes)
        self.assertEqual(state["caps"]["total_pct"], 0)

    def test_ice_does_not_close_w2_when_lianban_risk_is_low(self):
        """Vault 冰点可 W2 双轨试错，连板风险<0.5 时不因冰点本身关闭 W2"""
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-27"},"market":{"炸板率":20},"sentiment":{'
            '"情绪值":17.1,"昨日涨停收益":3.0,"晋级率":17.39,"连板风险值":"0.3低"},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{"连亏天数":0},"pnl":{},'
            '"style":{"总分":42,"连板占比":12,"趋势占比":88,"dim3_趋势":9}}'
        )
        bridge.CACHE["iwencai"] = {"情绪值": 17.1, "_updated": "2026-05-27T09:40:00+08:00"}
        bridge.CACHE["live_quotes"] = {"_updated": "2026-05-27T09:40:00+08:00"}

        state = bridge._build_rule_state(now=datetime(2026, 5, 27, 14, 30))
        codes = [b["code"] for b in state["blocks"]]

        self.assertNotIn("W2_ICE", codes)
        self.assertNotIn("W2_ICE_RISK", codes)

    def test_full_snapshot_contains_rule_state(self):
        """_build_full_snapshot() 输出含 rule_state"""
        snap = bridge._build_full_snapshot()
        self.assertIn("rule_state", snap)
        self.assertEqual(snap["rule_state"]["version"], "g1a-v1")

    def test_live_quotes_response_contains_rule_contract(self):
        """mock GET /api/live/quotes 返回含 rule_state"""
        handler = object.__new__(bridge.BridgeHandler)
        handler.request = MagicMock()
        handler.command = "GET"
        handler.requestline = "GET /api/live/quotes HTTP/1.1"
        handler.path = "/api/live/quotes"
        handler.request_version = "HTTP/1.1"
        handler.request.version = "HTTP/1.1"
        handler.client_address = ("127.0.0.1", 12345)
        handler.server = MagicMock()
        handler.headers = MagicMock()
        handler.log_message = MagicMock()
        handler._resp_status = None
        handler._resp_headers = []
        handler._resp_body = b""

        def msr(code, phrase=None): handler._resp_status = code
        def msh(key, value): handler._resp_headers.append((key, value))
        def meh(): pass
        def mww(self_data, data): handler._resp_body += data
        handler.send_response = msr
        handler.send_header = msh
        handler.end_headers = meh
        handler.wfile = type("WFile", (), {"write": mww})()

        do_get = getattr(handler, "do_GET", None)
        do_get()

        body = json.loads(handler._resp_body.decode()) if handler._resp_body else {}
        self.assertIn("rule_state", body)
        self.assertIn("windows", body["rule_state"])

    def test_live_quotes_rule_state_releases_connection(self):
        """GET /api/live/quotes 后连接已释放"""
        handler = object.__new__(bridge.BridgeHandler)
        handler.request = MagicMock()
        handler.command = "GET"
        handler.requestline = "GET /api/live/quotes HTTP/1.1"
        handler.path = "/api/live/quotes"
        handler.request_version = "HTTP/1.1"
        handler.request.version = "HTTP/1.1"
        handler.client_address = ("127.0.0.1", 12345)
        handler.server = MagicMock()
        handler.headers = MagicMock()
        handler.log_message = MagicMock()
        handler._resp_status = None
        handler._resp_headers = []
        handler._resp_body = b""

        def msr(code, phrase=None): handler._resp_status = code
        def msh(key, value): handler._resp_headers.append((key, value))
        def meh(): pass
        def mww(self_data, data): handler._resp_body += data
        handler.send_response = msr
        handler.send_header = msh
        handler.end_headers = meh
        handler.wfile = type("WFile", (), {"write": mww})()

        do_get = getattr(handler, "do_GET", None)
        do_get()

        self.assertIsNone(getattr(db._local, "conn", None),
                          "GET /api/live/quotes 后连接应释放")

    def test_trade_entry_gate_combines_health_and_rule_state(self):
        """live trade_entry_allowed 必须同时服从 health 与 rule_state"""
        allowed, reason = bridge._trade_entry_gate(
            {"trade_entry_allowed": True, "degraded_reasons": None},
            {
                "tradable": False,
                "blocks": [{"code": "DATA_UNTRUSTED", "scope": "all"}],
            },
        )

        self.assertFalse(allowed)
        self.assertIn("DATA_UNTRUSTED", reason)

    def test_ticket_fill_gate_uses_actual_action_and_window(self):
        context = {
            "health": {"trade_entry_allowed": True},
            "rule_state": {
                "tradable": True,
                "blocks": [],
                "source_gaps": [],
                "caps": {"add_allowed": True},
                "windows": {
                    "w1": {"in_session": True, "buy_allowed": False, "blocks": ["W1_LIMIT_UP_PROFIT"]},
                },
            },
        }
        with patch.object(bridge, "_build_ai_context", return_value=context):
            buy_allowed, buy_reason, buy_gate = bridge._ticket_fill_gate({
                "action_type": "buy", "window": "w1", "target_role": "trend_core", "entry_leg": 1,
            })
            sell_allowed, sell_reason, sell_gate = bridge._ticket_fill_gate({
                "action_type": "sell", "window": "w1", "target_role": "trend_core",
            })
        self.assertFalse(buy_allowed)
        self.assertIn("W1_LIMIT_UP_PROFIT", buy_reason)
        self.assertIn("W1_LIMIT_UP_PROFIT", buy_gate["blocking_codes"])
        self.assertTrue(sell_allowed)
        self.assertIsNone(sell_reason)
        self.assertTrue(sell_gate["allowed"])

    def test_execution_card_metadata_marks_compiled_hash_mismatch_stale(self):
        original_root = bridge.AI_RULE_SYSTEM_ROOT
        try:
            rule_root = self.tmp_dir / "ai-rule-system"
            runtime = rule_root / "daily-runtime"
            compiled_dir = rule_root / "compiled"
            runtime.mkdir(parents=True)
            compiled_dir.mkdir(parents=True)
            compiled = compiled_dir / "rules.v1.json"
            compiled.write_text('{"schema_version":"rules.v1","rules":[]}', encoding="utf-8")
            current_hash = hashlib.sha256(compiled.read_bytes()).hexdigest()
            self.assertNotEqual(current_hash, "0" * 64)
            card = {
                "next_trade_date": "2026-07-28",
                "generated_at": "2026-07-28T09:00:00+08:00",
                "rule_snapshot_hash": "sha256:card",
                "rule_snapshot": {
                    "compiled_rules": {"path": str(compiled), "sha256": "0" * 64},
                },
            }
            (runtime / "today_execution_card.json").write_text(json.dumps(card), encoding="utf-8")
            bridge.AI_RULE_SYSTEM_ROOT = rule_root
            meta = bridge._execution_card_metadata(trade_date="2026-07-28")
        finally:
            bridge.AI_RULE_SYSTEM_ROOT = original_root
        self.assertTrue(meta["execution_card_stale"])
        self.assertEqual(meta["stale_reason"], "RULE_SNAPSHOT_STALE")

    def test_execution_card_metadata_uses_declared_compiled_artifact_path(self):
        original_root = bridge.AI_RULE_SYSTEM_ROOT
        try:
            rule_root = self.tmp_dir / "canonical-ai-rule-system"
            runtime = rule_root / "daily-runtime"
            runtime.mkdir(parents=True)
            declared = self.tmp_dir / "implementation-worktree" / "compiled" / "rules.v1.json"
            declared.parent.mkdir(parents=True)
            declared.write_text('{"schema_version":"rules.v1","rules":[]}', encoding="utf-8")
            declared_hash = hashlib.sha256(declared.read_bytes()).hexdigest()
            physical_doc = declared.parent.parent / "07_DAILY_REVIEW_OUTPUT_PROTOCOL.md"
            physical_doc.write_text("canonical worktree bytes", encoding="utf-8")
            physical_doc_hash = hashlib.sha256(physical_doc.read_bytes()).hexdigest()
            card = {
                "next_trade_date": "2026-07-28",
                "generated_at": "2026-07-28T09:00:00+08:00",
                "rule_snapshot_hash": "sha256:card",
                "rule_snapshot": {
                    "compiled_rules": {
                        "path": str(declared),
                        "sha256": declared_hash,
                        "rules": [{
                            "source_doc_hashes": [{
                                "path": str(rule_root / "07_DAILY_REVIEW_OUTPUT_PROTOCOL.md"),
                                "sha256": physical_doc_hash,
                            }],
                        }],
                    },
                },
            }
            (runtime / "today_execution_card.json").write_text(json.dumps(card), encoding="utf-8")
            bridge.AI_RULE_SYSTEM_ROOT = rule_root

            meta = bridge._execution_card_metadata(trade_date="2026-07-28")
        finally:
            bridge.AI_RULE_SYSTEM_ROOT = original_root

        self.assertFalse(meta.get("execution_card_stale"), meta)
        self.assertEqual(str(declared), meta["compiled_rules_path"])

    def test_execution_card_metadata_accepts_deployed_compiled_bundle_without_vault_checkout(self):
        original_root = bridge.AI_RULE_SYSTEM_ROOT
        try:
            rule_root = self.tmp_dir / "deployed-ai-rule-system"
            runtime = rule_root / "daily-runtime"
            compiled_dir = rule_root / "compiled"
            runtime.mkdir(parents=True)
            compiled_dir.mkdir(parents=True)
            canonical_source = "/Users/yimu/Documents/YouMingVault/rules/trading-core.md"
            rules = [{
                "rule_id": "STYLE-SCORE-001",
                "source_doc_hashes": [{
                    "path": canonical_source,
                    "sha256": "a" * 64,
                }],
            }]
            compiled = compiled_dir / "rules.v1.json"
            compiled.write_text(
                json.dumps({"schema_version": "rules.v1", "rules": rules}),
                encoding="utf-8",
            )
            compiled_hash = hashlib.sha256(compiled.read_bytes()).hexdigest()
            card = {
                "next_trade_date": "2026-07-28",
                "generated_at": "2026-07-28T09:00:00+08:00",
                "rule_snapshot_hash": "sha256:card",
                "rule_snapshot": {
                    "compiled_rules": {
                        "path": "/Users/canonical-builder/YM_Capital/ai-rule-system/compiled/rules.v1.json",
                        "sha256": compiled_hash,
                        "rules": rules,
                    },
                },
            }
            (runtime / "today_execution_card.json").write_text(
                json.dumps(card), encoding="utf-8"
            )
            bridge.AI_RULE_SYSTEM_ROOT = rule_root

            meta = bridge._execution_card_metadata(trade_date="2026-07-28")
        finally:
            bridge.AI_RULE_SYSTEM_ROOT = original_root

        self.assertFalse(meta.get("execution_card_stale"), meta)
        self.assertEqual(str(compiled), meta["compiled_rules_path"])


class FreshnessBoundaryTest(unittest.TestCase):
    """验证 freshness stale/dead 在 rule_state 中正确传播"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        self.orig_inited = bridge._db_inited
        self.orig_root = bridge.ROOT
        self.orig_data = bridge.DATA_FILE
        db.DB_PATH = self.tmp_dir / "test.db"
        db._local = threading.local()
        bridge._db_inited = False
        bridge.ROOT = self.tmp_dir
        self.tmp_dashboard = self.tmp_dir / "dashboard_data.json"
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-27"},"market":{},"sentiment":{"二进三晋级率近3日均值":26.966667},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{},"pnl":{},"style":{"总分":59,"连板占比":54,"趋势占比":46}}'
        )
        bridge.DATA_FILE = self.tmp_dashboard
        db.init_db()

        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        db.insert_account_baseline({
            "date": today, "effective_at": f"{today}T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 100000,
            "total_deposit": 100000, "positions": [], "source": "recovery",
        })

    def tearDown(self):
        bridge.CACHE.clear()
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        bridge._db_inited = self.orig_inited
        bridge.ROOT = self.orig_root
        bridge.DATA_FILE = self.orig_data
        self.tmp.cleanup()

    def test_stale_quotes_warns_when_account_valuation_is_complete(self):
        """行情 stale 但账户估值完整时只提示，不全局阻断"""
        bridge.CACHE["iwencai"] = {
            "情绪值": 65, "昨日涨停收益": 3.0,
            "晋级率": 0.22, "炸板率": 0.20,
            "_updated": "2026-05-27T09:40:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {
            "_updated": "2026-05-27T09:37:00+08:00",  # 3min old → stale
        }
        bridge.CACHE["live_index"] = {}
        bridge.CACHE["breadth"] = {}
        bridge.CACHE["hot_list"] = {}

        from datetime import datetime as _dt
        now = _dt(2026, 5, 27, 9, 40)
        state = bridge._build_rule_state(
            now=now,
            account_state={"pnl_pct": 0.0, "valuation_complete": True, "mv": 0},
        )
        codes = [b["code"] for b in state["blocks"]]
        warnings = [w["code"] for w in state["warnings"]]
        self.assertNotIn("DATA_UNTRUSTED", codes)
        self.assertIn("QUOTE_STALE", warnings)
        self.assertTrue(state["tradable"])

    def test_premarket_snapshot_before_0915_is_not_dead(self):
        """09:15前采集器未开跑，同日盘前快照不应被 freshness 判 dead"""
        from datetime import datetime as _dt

        fresh = bridge._compute_freshness(
            "live_quote",
            {"_updated": "2026-05-27T08:54:00+08:00"},
            now=_dt(2026, 5, 27, 9, 8),
        )

        self.assertEqual(fresh, "stale")

    def test_stale_sentiment_with_baseline_fields_blocks_realtime_rule_state(self):
        """情绪缓存 stale 时不得用 baseline 伪装实时规则输入"""
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-29"},"market":{"炸板率":76.2},'
            '"sentiment":{"情绪值":54,"昨日涨停收益":0.84,"晋级率":19.15},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{"连亏天数":2},"pnl":{},'
            '"time_window":{"W1状态":"开放","W2状态":"开放"},'
            '"style":{"总分":57,"连板占比":57,"趋势占比":43,"dim3_趋势":16,'
            '"总仓位上限":60,"_source":"premarket_plan"}}'
        )
        bridge.CACHE["iwencai"] = {
            "情绪值": 54, "昨日涨停收益": 0.84,
            "晋级率": 0.1915, "炸板率": 0.762,
            "_updated": "2026-05-29T09:00:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {"_updated": "2026-05-29T09:17:00+08:00"}
        bridge.CACHE["live_index"] = {}
        bridge.CACHE["breadth"] = {}
        bridge.CACHE["hot_list"] = {}

        from datetime import datetime as _dt
        state = bridge._build_rule_state(
            now=_dt(2026, 5, 29, 9, 17),
            account_state={"pnl_pct": 0.0, "valuation_complete": True, "mv": 69040},
        )

        codes = [b["code"] for b in state["blocks"]]
        warnings = [w["code"] for w in state["warnings"]]
        self.assertEqual(state["caps"]["total_pct"], 0)
        self.assertIn("SENTIMENT_STALE", codes)
        self.assertNotIn("FRIDAY_W1", codes)
        self.assertIn("LOSS_STREAK", warnings)

    def test_production_format_same_minute_is_live(self):
        """生产 +08:00 同分钟数据必须判为 live（时区回归）"""
        bridge.CACHE["iwencai"] = {
            "情绪值": 65, "昨日涨停收益": 3.0,
            "晋级率": 0.22, "炸板率": 0.20,
            "_updated": "2026-05-27T09:40:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {
            "_updated": "2026-05-27T09:40:00+08:00",
        }
        bridge.CACHE["live_index"] = {}
        bridge.CACHE["breadth"] = {}
        bridge.CACHE["hot_list"] = {}

        # Naive now (local time +08:00) — 模拟生产路径
        from datetime import datetime as _dt
        now = _dt(2026, 5, 27, 9, 40)
        state = bridge._build_rule_state(now=now)
        codes = [b["code"] for b in state["blocks"]]
        # 同分钟数据应为 live，不应触发 DATA_UNTRUSTED 或 SENTIMENT_STALE
        self.assertNotIn("DATA_UNTRUSTED", codes,
                         "同分钟生产数据不应判为 DATA_UNTRUSTED")
        self.assertNotIn("SENTIMENT_STALE", codes,
                         "同分钟生产数据不应判为 SENTIMENT_STALE")
        self.assertTrue(state["tradable"],
                        "同分钟生产数据应为可交易")

    def test_dead_sentiment_with_complete_fields_blocks_realtime_rule_state(self):
        """情绪 dead 时即使字段齐全也不得参与实时规则"""
        bridge.CACHE["iwencai"] = {
            "情绪值": 65, "昨日涨停收益": 3.0,
            "晋级率": 0.22, "炸板率": 0.20,
            "_updated": "2026-05-26T09:00:00+08:00",  # >1day old → dead
        }
        bridge.CACHE["live_quotes"] = {
            "_updated": "2026-05-27T09:39:00+08:00",
        }
        bridge.CACHE["live_index"] = {}
        bridge.CACHE["breadth"] = {}
        bridge.CACHE["hot_list"] = {}

        from datetime import datetime as _dt
        now = _dt(2026, 5, 27, 9, 40)
        state = bridge._build_rule_state(now=now)
        codes = [b["code"] for b in state["blocks"]]
        warnings = [w["code"] for w in state["warnings"]]
        self.assertIn("SENTIMENT_STALE", codes)
        stale_blocks = [b for b in state["blocks"] if b["code"] == "SENTIMENT_STALE"]
        self.assertEqual(["lianban"], [b["scope"] for b in stale_blocks])
        self.assertEqual(state["caps"]["total_pct"], 0)
        self.assertTrue(state["tradable"])

    def test_stale_breadth_and_iwencai_do_not_emit_emotion_value(self):
        """过期 breadth/iwencai 不得继续把旧情绪值作为实时规则输入"""
        bridge.CACHE["breadth"] = {
            "上涨家数": 590,
            "下跌家数": 410,
            "_updated": "2026-06-08T11:26:00+08:00",
        }
        bridge.CACHE["iwencai"] = {
            "情绪值": 59,
            "昨日涨停收益": 3.0,
            "晋级率": 0.22,
            "炸板率": 0.20,
            "_updated": "2026-06-08T11:26:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {
            "_updated": "2026-06-08T14:30:00+08:00",
        }
        bridge.CACHE["live_index"] = {}
        bridge.CACHE["hot_list"] = {}

        from datetime import datetime as _dt
        state = bridge._build_rule_state(
            now=_dt(2026, 6, 8, 14, 30),
            account_state={"pnl_pct": 0.0, "valuation_complete": True, "mv": 100000},
        )

        blocks = [b for b in state["blocks"] if b["code"] == "SENTIMENT_STALE"]
        self.assertTrue(blocks, f"过期情绪应阻断连板侧: {state}")
        self.assertEqual(["lianban"], [block["scope"] for block in blocks])
        self.assertIn("emotion_pct", blocks[0]["evidence"].get("missing", []))
        self.assertEqual(state["market_regime"], "unknown")
        self.assertEqual(state["caps"]["total_pct"], 0)
        self.assertTrue(state["tradable"])


class Kline15mPayloadFreshnessTest(unittest.TestCase):
    def tearDown(self):
        bridge.CACHE.clear()

    def test_kline_15m_without_today_marker_is_hidden_from_payload(self):
        bridge.CACHE["上证15min"] = [{"t": "15:00", "chg": 0.1}]
        bridge.CACHE.pop("kline_15m_date", None)

        rows = bridge._kline_15m_payload("上证15min", now=datetime(2026, 6, 3, 10, 0))

        self.assertEqual(rows, [])

    def test_kline_15m_with_today_marker_is_returned(self):
        expected = [{"t": "09:45", "chg": 0.1}]
        bridge.CACHE["上证15min"] = expected
        bridge.CACHE["kline_15m_date"] = "2026-06-03"

        rows = bridge._kline_15m_payload("上证15min", now=datetime(2026, 6, 3, 10, 0))

        self.assertEqual(rows, expected)


class DoubleIceIntegrationTest(unittest.TestCase):
    """验证 DOUBLE_ICE 通过 sentiment_auto.json 日期分组正确找到 previous_emotion"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        self.orig_inited = bridge._db_inited
        self.orig_root = bridge.ROOT
        self.orig_data = bridge.DATA_FILE
        db.DB_PATH = self.tmp_dir / "test.db"
        db._local = threading.local()
        bridge._db_inited = False
        bridge.ROOT = self.tmp_dir
        self.tmp_dashboard = self.tmp_dir / "dashboard_data.json"
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-27"},"market":{},"sentiment":{"二进三晋级率近3日均值":26.966667},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{},"pnl":{},"style":{"总分":59,"连板占比":54,"趋势占比":46}}'
        )
        bridge.DATA_FILE = self.tmp_dashboard
        db.init_db()

        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        db.insert_account_baseline({
            "date": today, "effective_at": f"{today}T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 100000,
            "total_deposit": 100000, "positions": [], "source": "recovery",
        })

        bridge.CACHE["iwencai"] = {
            "情绪值": 15, "昨日涨停收益": 1.0,
            "晋级率": 0.05, "炸板率": 0.20,
            "_updated": "2026-05-27T09:40:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {"_updated": "2026-05-27T09:39:00+08:00"}
        bridge.CACHE["live_index"] = {}
        bridge.CACHE["breadth"] = {}
        bridge.CACHE["hot_list"] = {}

    def tearDown(self):
        bridge.CACHE.clear()
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        bridge._db_inited = self.orig_inited
        bridge.ROOT = self.orig_root
        bridge.DATA_FILE = self.orig_data
        self.tmp.cleanup()

    def test_double_ice_uses_date_grouped_previous_emotion(self):
        """前一日最后节点情绪=10，当前=15 → 双冰触发"""
        import json as _json
        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        # 前一日期
        prev_date = "2026-05-20"
        snap = {prev_date: [{"情绪值": 10, "time": f"{prev_date}T15:00:00+08:00"}],
                today: [{"情绪值": 15, "time": f"{today}T09:25:00+08:00"}]}
        snap_path = self.tmp_dir / "data" / "sentiment_auto.json"
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(_json.dumps(snap))

        # mock ROOT to point temp so sentiment_auto is found
        state = bridge._build_rule_state(now=__import__("datetime").datetime(2026, 5, 27, 9, 40))
        codes = [b["code"] for b in state["blocks"]]
        self.assertIn("DOUBLE_ICE", codes,
                      "前一日情绪=10 + 当前=15 应触发 DOUBLE_ICE")


class DebugSnapshotExceptionReleaseTest(unittest.TestCase):
    """验证 /api/debug/snapshot 异常路径也关闭 DB 连接"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        self.orig_inited = bridge._db_inited
        self.orig_root = bridge.ROOT
        self.orig_data = bridge.DATA_FILE
        db.DB_PATH = self.tmp_dir / "test.db"
        db._local = threading.local()
        bridge._db_inited = False
        bridge.ROOT = self.tmp_dir
        bridge.DATA_FILE = self.tmp_dir / "dashboard_data.json"
        db.init_db()

    def tearDown(self):
        bridge.CACHE.clear()
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        bridge._db_inited = self.orig_inited
        bridge.ROOT = self.orig_root
        bridge.DATA_FILE = self.orig_data
        self.tmp.cleanup()

    def test_debug_snapshot_exception_releases_connection(self):
        """_build_full_snapshot 抛错时连接也释放"""
        handler = object.__new__(bridge.BridgeHandler)
        handler.request = MagicMock()
        handler.command = "GET"
        handler.requestline = "GET /api/debug/snapshot HTTP/1.1"
        handler.path = "/api/debug/snapshot"
        handler.request_version = "HTTP/1.1"
        handler.request.version = "HTTP/1.1"
        handler.client_address = ("127.0.0.1", 12345)
        handler.server = MagicMock()
        handler.headers = MagicMock()
        handler.log_message = MagicMock()
        handler._resp_status = None
        handler._resp_headers = []
        handler._resp_body = b""

        def msr(code, phrase=None): handler._resp_status = code
        def msh(key, value): handler._resp_headers.append((key, value))
        def meh(): pass
        def mww(self_data, data): handler._resp_body += data
        handler.send_response = msr
        handler.send_header = msh
        handler.end_headers = meh
        handler.wfile = type("WFile", (), {"write": mww})()

        # Patch _build_full_snapshot to raise
        with patch.object(bridge, "_build_full_snapshot", side_effect=RuntimeError("boom")):
            do_get = getattr(handler, "do_GET", None)
            try:
                do_get()
            except Exception:
                pass

        self.assertIsNone(getattr(db._local, "conn", None),
                          "异常路径也必须在 finally 中释放连接")


class SseConnectionReleaseTest(unittest.TestCase):
    """验证 SSE 每轮循环释放 DB 连接"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)
        self.orig_path = db.DB_PATH
        self.orig_local = db._local
        self.orig_inited = bridge._db_inited
        self.orig_root = bridge.ROOT
        self.orig_data = bridge.DATA_FILE
        db.DB_PATH = self.tmp_dir / "test.db"
        db._local = threading.local()
        bridge._db_inited = False
        bridge.ROOT = self.tmp_dir
        self.tmp_dashboard = self.tmp_dir / "dashboard_data.json"
        self.tmp_dashboard.write_text(
            '{"meta":{"date":"2026-05-27"},"market":{},"sentiment":{"二进三晋级率近3日均值":26.966667},'
            '"lianban_pool":[],"trend_pool":[],"positions":[],"decision":{},'
            '"sectors":[],"risk":{},"pnl":{},"style":{"总分":59,"连板占比":54,"趋势占比":46}}'
        )
        bridge.DATA_FILE = self.tmp_dashboard
        db.init_db()

        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        db.insert_account_baseline({
            "date": today, "effective_at": f"{today}T09:30:00",
            "trade_id_cutoff": 0, "cash": 100000, "day_start_asset": 100000,
            "total_deposit": 100000, "positions": [], "source": "recovery",
        })

        bridge.CACHE["iwencai"] = {
            "情绪值": 65, "昨日涨停收益": 3.0,
            "晋级率": 0.22, "炸板率": 0.20,
            "_updated": "2026-05-27T09:40:00+08:00",
        }
        bridge.CACHE["live_quotes"] = {
            "_updated": "2026-05-27T09:39:00+08:00",
        }
        bridge.CACHE["live_index"] = {}
        bridge.CACHE["breadth"] = {}
        bridge.CACHE["hot_list"] = {}

    def tearDown(self):
        bridge.CACHE.clear()
        db.close_conn()
        db.DB_PATH = self.orig_path
        db._local = self.orig_local
        bridge._db_inited = self.orig_inited
        bridge.ROOT = self.orig_root
        bridge.DATA_FILE = self.orig_data
        self.tmp.cleanup()

    def test_sse_first_message_contains_rule_state_and_releases(self):
        """SSE 首条消息含 rule_state 且本轮结束后连接释放"""
        handler = object.__new__(bridge.BridgeHandler)
        handler.request = MagicMock()
        handler.command = "GET"
        handler.requestline = "GET /api/live/stream HTTP/1.1"
        handler.path = "/api/live/stream"
        handler.request_version = "HTTP/1.1"
        handler.request.version = "HTTP/1.1"
        handler.client_address = ("127.0.0.1", 12345)
        handler.server = MagicMock()
        handler.headers = MagicMock()
        handler.log_message = MagicMock()
        handler._resp_status = None
        handler._resp_headers = []
        handler._resp_body = b""
        handler._writes = []

        def msr(code, phrase=None): handler._resp_status = code
        def msh(key, value): handler._resp_headers.append((key, value))
        def meh(): pass
        def mww(self_data, data):
            handler._resp_body += data
            handler._writes.append(data)
            # Raise after first write to break SSE loop
            if len(handler._writes) >= 1:
                raise BrokenPipeError()
        handler.send_response = msr
        handler.send_header = msh
        handler.end_headers = meh
        handler.wfile = type("WFile", (), {"write": mww})()

        do_get = getattr(handler, "do_GET", None)
        try:
            do_get()
        except Exception:
            pass

        body = handler._resp_body.decode() if handler._resp_body else ""
        self.assertIn("rule_state", body, "SSE 首条消息应含 rule_state")
        self.assertIsNone(getattr(db._local, "conn", None),
                          "SSE 本轮结束后连接应释放")


if __name__ == "__main__":
    unittest.main()
