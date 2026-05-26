"""test_llm_validation.py — AI 输出校验 + rule_state 硬阻断 (Gate 1C)

全隔离：temp DB、temp DATA_FILE、temp LLM_INSIGHTS_FILE、mock CACHE。
"""
import io
import json
import threading
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import scripts.db as db
import scripts.bridge as bridge


def _setup_isolated_bridge(test):
    test.tmp = tempfile.TemporaryDirectory()
    d = Path(test.tmp.name)
    test.orig_path = db.DB_PATH
    test.orig_local = db._local
    test.orig_inited = bridge._db_inited
    test.orig_root = bridge.ROOT
    test.orig_data = bridge.DATA_FILE
    test.orig_llm = bridge.LLM_INSIGHTS_FILE
    db.DB_PATH = d / "test.db"
    db._local = threading.local()
    bridge._db_inited = False
    bridge.ROOT = d
    bridge.DATA_FILE = d / "dashboard_data.json"
    bridge.DATA_FILE.write_text(json.dumps({
        "meta": {"date": "2026-05-27"}, "market": {}, "sentiment": {},
        "lianban_pool": [], "trend_pool": [], "positions": [], "decision": {},
        "sectors": [], "risk": {}, "pnl": {},
        "style": {"总分": 85, "连板占比": 54, "趋势占比": 46},
    }))
    bridge.LLM_INSIGHTS_FILE = d / "llm_insights.json"
    db.init_db()
    today = datetime.now().strftime("%Y-%m-%d")
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
    bridge.CACHE["live_quotes"] = {"_updated": "2026-05-27T09:39:00+08:00"}
    bridge.CACHE["live_index"] = {}
    bridge.CACHE["breadth"] = {}
    bridge.CACHE["hot_list"] = {}


def _teardown_isolated_bridge(test):
    bridge.CACHE.clear()
    db.close_conn()
    db.DB_PATH = test.orig_path
    db._local = test.orig_local
    bridge._db_inited = test.orig_inited
    bridge.ROOT = test.orig_root
    bridge.DATA_FILE = test.orig_data
    bridge.LLM_INSIGHTS_FILE = test.orig_llm
    test.tmp.cleanup()


def _day_stop_snapshot():
    from scripts.rule_engine import evaluate_rule_state
    return {
        "指数": {}, "情绪": {}, "连板池": [], "趋势池": [
            {"标的": "测试趋势", "代码": "000001", "板块": "科技",
             "涨幅": "+4.5", "量比": "0.5", "MA10_60m": "0.1"},
        ], "持仓": [], "板块": [{"板块": "科技", "类型": "主线"}],
        "风控": {}, "涨停梯队TOP5": [],
        "rule_state": evaluate_rule_state(
            {"account": {"pnl_pct": -4.0, "valuation_complete": True},
             "risk": {"loss_streak": 0},
             "style": {"score": 85, "lianban_pct": 54, "trend_pct": 46},
             "sentiment": {"emotion_pct": 65, "previous_emotion_pct": 45,
                            "limit_up_profit_pct": 3.0, "broken_board_pct": 20,
                            "promotion_pct": 22},
             "freshness": {"quotes": "live", "sentiment": "live"}},
            datetime(2026, 5, 27, 14, 10)),
    }


def _tradable_snapshot():
    from scripts.rule_engine import evaluate_rule_state
    return {
        "指数": {}, "情绪": {"emotion_pct": 65}, "连板池": [], "趋势池": [
            {"标的": "测试趋势", "代码": "000001", "板块": "科技",
             "涨幅": "-2", "量比": "0.5", "MA10_60m": "0.1", "MA10_60m_dir": "向上", "最新价": "0.1"},
        ], "持仓": [], "板块": [{"板块": "科技", "类型": "主线"}],
        "风控": {}, "涨停梯队TOP5": [],
        "rule_state": evaluate_rule_state(
            {"account": {"pnl_pct": 0.5, "valuation_complete": True},
             "risk": {"loss_streak": 0},
             "style": {"score": 85, "lianban_pct": 54, "trend_pct": 46},
             "sentiment": {"emotion_pct": 65, "previous_emotion_pct": 45,
                            "limit_up_profit_pct": 3.0, "broken_board_pct": 20,
                            "promotion_pct": 22},
             "freshness": {"quotes": "live", "sentiment": "live"}},
            datetime(2026, 5, 27, 14, 10)),
    }


class BuyHardValidationTest(unittest.TestCase):

    def setUp(self):
        _setup_isolated_bridge(self)

    def tearDown(self):
        _teardown_isolated_bridge(self)

    def test_day_stop_buy_must_be_warning(self):
        snap = _day_stop_snapshot()
        signals = [{"type": "BUY", "target": "测试趋势", "code": "000001",
                     "window": "W2", "direction": "多", "confidence": "高",
                     "basis": ["回踩MA10"]}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "⚠️")
        self.assertIn("tradable", verified[0]["note"].lower() or "")

    def test_tradable_buy_passes(self):
        snap = _tradable_snapshot()
        signals = [{"type": "BUY", "target": "测试趋势", "code": "000001",
                     "window": "W2", "direction": "多", "confidence": "高",
                     "basis": ["回踩MA10"]}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "✅")

    def test_buy_stock_not_in_pool_is_warning(self):
        snap = _tradable_snapshot()
        signals = [{"type": "BUY", "target": "不存在标的", "code": "999999",
                     "window": "W2", "direction": "多", "confidence": "高"}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "⚠️")
        self.assertIn("不在", verified[0]["note"])

    def test_buy_unknown_type_is_warning(self):
        snap = _tradable_snapshot()
        signals = [{"type": "EXECUTE", "target": "测试", "code": "",
                     "window": "—", "direction": "—", "confidence": "高"}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "⚠️")
        self.assertIn("unknown type", verified[0]["note"])

    def test_buy_empty_target_is_warning(self):
        snap = _tradable_snapshot()
        signals = [{"type": "BUY", "target": "", "code": "000001",
                     "window": "W2", "direction": "多", "confidence": "高"}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "⚠️")
        self.assertIn("target is empty", verified[0]["note"])

    def test_buy_window_dash_is_warning(self):
        snap = _tradable_snapshot()
        signals = [{"type": "BUY", "target": "测试趋势", "code": "000001",
                     "window": "—", "direction": "多", "confidence": "高"}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "⚠️")
        self.assertIn("window must be W1 or W2", verified[0]["note"])

    def test_buy_bad_tech_conditions_is_warning(self):
        snap = _tradable_snapshot()
        snap["趋势池"][0]["涨幅"] = "—"
        snap["趋势池"][0]["量比"] = "1"
        snap["趋势池"][0]["MA10_60m"] = "—"
        signals = [{"type": "BUY", "target": "测试趋势", "code": "000001",
                     "window": "W2", "direction": "多", "confidence": "高"}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "⚠️")
        self.assertIn("缺涨", verified[0]["note"])

    def test_parse_non_json_produces_warning(self):
        text, sigs, warns = bridge._parse_llm_response("not json at all")
        self.assertGreater(len(warns), 0)

    def test_parse_json_reordered_fields(self):
        raw = '{"signals":[{"window":"W2","type":"BUY","confidence":"高","target":"测试","direction":"多","code":"","basis":["a"]}],"text":"test"}'
        text, sigs, warns = bridge._parse_llm_response(raw)
        self.assertEqual(text, "test")
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]["type"], "BUY")

    def test_parse_json_missing_field_warning(self):
        raw = '{"text":"test","signals":[{"type":"BUY"}]}'
        text, sigs, warns = bridge._parse_llm_response(raw)
        self.assertEqual(len(sigs), 1)
        self.assertIn("_schema_errors", sigs[0])
        self.assertGreater(len(sigs[0]["_schema_errors"]), 0)
        has_missing = any("missing" in e for e in sigs[0]["_schema_errors"])
        self.assertTrue(has_missing, f"应有字段缺失schema错误: {sigs[0]['_schema_errors']}")

    def test_parse_legacy_format_warning(self):
        raw = "[TEXT] test\n[SIGNALS]\nBUY | 测试 | 多 | 高"
        text, sigs, warns = bridge._parse_llm_response(raw)
        self.assertGreater(len(sigs), 0)
        has_legacy = any("legacy" in w for w in warns)
        self.assertTrue(has_legacy, f"应有 legacy 警告: {warns}")

    def test_parse_json_signals_array(self):
        raw = '{"text":"test","signals":[{"type":"BUY","target":"测试","code":"","window":"W2","direction":"多","confidence":"高","basis":["a"]}]}'
        text, sigs, warns = bridge._parse_llm_response(raw)
        self.assertEqual(text, "test")
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]["type"], "BUY")

    def test_w1_buy_allowed_false_blocks_buy(self):
        from scripts.rule_engine import evaluate_rule_state
        rs = evaluate_rule_state(
            {"account": {"pnl_pct": 0.5, "valuation_complete": True},
             "risk": {"loss_streak": 0},
             "style": {"score": 85, "lianban_pct": 54, "trend_pct": 46},
             "sentiment": {"emotion_pct": 45, "previous_emotion_pct": 45,
                            "limit_up_profit_pct": 3.0, "broken_board_pct": 20,
                            "promotion_pct": 22},
             "freshness": {"quotes": "live", "sentiment": "live"}},
            datetime(2026, 5, 27, 9, 40))
        snap = {"指数": {}, "情绪": {}, "连板池": [{"标的": "测试连板", "代码": "000001",
                "板块": "科技", "涨幅": "+5", "量比": "0.5", "MA10_60m": "—"}],
                "趋势池": [], "持仓": [], "板块": [], "风控": {}, "涨停梯队TOP5": [],
                "rule_state": rs}
        signals = [{"type": "BUY", "target": "测试连板", "code": "000001",
                     "window": "W1", "direction": "多", "confidence": "高"}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "⚠️")
        self.assertIn("W1 buy_allowed", verified[0]["note"])

    def test_double_ice_blocks_buy(self):
        from scripts.rule_engine import evaluate_rule_state
        rs = evaluate_rule_state(
            {"account": {"pnl_pct": 0.5, "valuation_complete": True},
             "risk": {"loss_streak": 0},
             "style": {"score": 85, "lianban_pct": 54, "trend_pct": 46},
             "sentiment": {"emotion_pct": 15, "previous_emotion_pct": 10,
                            "limit_up_profit_pct": 3.0, "broken_board_pct": 20,
                            "promotion_pct": 22},
             "freshness": {"quotes": "live", "sentiment": "live"}},
            datetime(2026, 5, 27, 14, 10))
        snap = {"指数": {}, "情绪": {}, "连板池": [], "趋势池": [
                {"标的": "测试趋势", "代码": "000001", "涨幅": "+4.5", "量比": "0.5", "MA10_60m": "0.1"}],
                "持仓": [], "板块": [], "风控": {}, "涨停梯队TOP5": [], "rule_state": rs}
        signals = [{"type": "BUY", "target": "测试趋势", "code": "000001",
                     "window": "W2", "direction": "多", "confidence": "高"}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "⚠️")
        self.assertIn("tradable", verified[0]["note"].lower() or "")

    def test_basis_missing_buy_gets_warning_status(self):
        """缺 basis 的技术合法 BUY 最终 status=⚠️ 且 verified_count=0"""
        raw = '{"text":"test","signals":[{"type":"BUY","target":"测试趋势","code":"000001","window":"W2","direction":"多","confidence":"高","basis":["回踩MA10"]}]}'
        # Remove basis to simulate missing-basis through full parse→verify flow
        raw_no_basis = '{"text":"test","signals":[{"type":"BUY","target":"测试趋势","code":"000001","window":"W2","direction":"多","confidence":"高"}]}'
        snap = _tradable_snapshot()
        snap["趋势池"][0]["涨幅"] = "-2"
        snap["趋势池"][0]["量比"] = "0.5"
        snap["趋势池"][0]["MA10_60m"] = "145"
        snap["趋势池"][0]["MA10_60m_dir"] = "向上"
        snap["趋势池"][0]["最新价"] = "145"
        today = "2026-05-27"
        insight, sigs, vc, wc = bridge._process_llm_result(raw_no_basis, snap, today, "14:00:00", "auto")
        buy_sigs = [s for s in sigs if s["type"] == "BUY"]
        self.assertEqual(len(buy_sigs), 1)
        self.assertEqual(buy_sigs[0]["status"], "⚠️",
                         f"缺basis BUY应被降级: {buy_sigs[0]}")
        self.assertEqual(vc, 0, "缺basis BUY verified_count 应为 0")

    def test_extra_text_buy_not_verified(self):
        """JSON 前后夹带文字且含 BUY 时，BUY 不得 verified"""
        raw = 'some extra text {"text":"test","signals":[{"type":"BUY","target":"测试趋势","code":"000001","window":"W2","direction":"多","confidence":"高","basis":["回踩MA10"]}]}'
        snap = _tradable_snapshot()
        snap["趋势池"][0]["涨幅"] = "-2"
        snap["趋势池"][0]["量比"] = "0.5"
        snap["趋势池"][0]["MA10_60m"] = "145"
        snap["趋势池"][0]["MA10_60m_dir"] = "向上"
        snap["趋势池"][0]["最新价"] = "145"
        today = "2026-05-27"
        insight, sigs, vc, wc = bridge._process_llm_result(raw, snap, today, "14:00:00", "auto")
        buy_sigs = [s for s in sigs if s["type"] == "BUY"]
        self.assertEqual(len(buy_sigs), 1)
        self.assertEqual(buy_sigs[0]["status"], "⚠️",
                         f"extra text BUY应被降级: {buy_sigs[0]}")
        self.assertEqual(vc, 0, "extra text BUY verified_count 应为 0")


class CommonFlowTest(unittest.TestCase):

    def setUp(self):
        _setup_isolated_bridge(self)

    def tearDown(self):
        _teardown_isolated_bridge(self)

    def test_process_llm_result_common_flow(self):
        snap = _tradable_snapshot()
        raw = '{"text":"test","signals":[{"type":"BUY","target":"测试趋势","code":"000001","window":"W2","direction":"多","confidence":"高","basis":["a"]}]}'
        today = "2026-05-27"
        insight, sigs, vc, wc = bridge._process_llm_result(raw, snap, today, "10:00:00", "auto")
        self.assertEqual(insight["mode"], "auto")
        self.assertGreater(vc, 0)
        self.assertEqual(sigs[0]["type"], "BUY")
        # 验证写入临时文件
        self.assertTrue(bridge.LLM_INSIGHTS_FILE.exists())

    def test_results_release_connection(self):
        snap = _tradable_snapshot()
        raw = '{"text":"test","signals":[]}'
        today = "2026-05-27"
        bridge._process_llm_result(raw, snap, today, "10:00:00", "manual")

    def test_user_before_assistant_conversation_order(self):
        snap = _tradable_snapshot()
        raw = '{"text":"test reply","signals":[]}'
        today = "2026-05-27"
        userMsg = {"ts": "10:00:00", "text": "user question"}
        bridge._process_llm_result(raw, snap, today, "10:00:05", "manual", userMsg=userMsg)
        # 读取临时文件验证顺序
        data = json.loads(bridge.LLM_INSIGHTS_FILE.read_text())
        conv = data[today]["conversation"]
        # 应至少有 user 和 assistant 两条
        roles = [m["role"] for m in conv]
        user_idx = next(i for i, r in enumerate(roles) if r == "user")
        asst_idx = next(i for i, r in enumerate(roles) if r == "assistant")
        self.assertLess(user_idx, asst_idx, "user 应在 assistant 之前")
        self.assertEqual(conv[user_idx]["text"], "user question")
        self.assertEqual(conv[asst_idx]["text"], "test reply")

    def test_manual_and_auto_produce_same_signals(self):
        snap = _tradable_snapshot()
        raw = '{"text":"test","signals":[{"type":"BUY","target":"测试趋势","code":"000001","window":"W2","direction":"多","confidence":"高","basis":["a"]}]}'
        today = "2026-05-27"
        i1, s1, _, _ = bridge._process_llm_result(raw, snap, today, "10:00:00", "manual")
        i2, s2, _, _ = bridge._process_llm_result(raw, snap, today, "10:00:00", "auto")
        self.assertEqual(i1["mode"], "manual")
        self.assertEqual(i2["mode"], "auto")
        for s in [s1, s2]:
            self.assertEqual(len(s), 1)
            self.assertEqual(s[0]["type"], "BUY")
            self.assertEqual(s[0]["status"], "✅")

    def test_llm_handler_releases_connection(self):
        payload = json.dumps({"mode": "auto", "node": "10:00:00"}).encode()
        handler = object.__new__(bridge.BridgeHandler)
        handler.request = MagicMock()
        handler.command = "POST"
        handler.requestline = "POST /api/llm HTTP/1.1"
        handler.path = "/api/llm"
        handler.request_version = "HTTP/1.1"
        handler.request.version = "HTTP/1.1"
        handler.client_address = ("127.0.0.1", 12345)
        handler.server = MagicMock()
        handler.rfile = io.BytesIO(payload)
        handler.headers = MagicMock()
        handler.headers.get = lambda k, d=None: str(len(payload))
        handler.log_message = MagicMock()
        handler._resp_status = None
        handler._resp_headers = []
        handler._resp_body = b""
        def msr(code, p=None): handler._resp_status = code
        def msh(k, v): handler._resp_headers.append((k, v))
        def meh(): pass
        def mww(s, d): handler._resp_body += d
        handler.send_response = msr
        handler.send_header = msh
        handler.end_headers = meh
        handler.wfile = type("WFile", (), {"write": mww})()

        with patch("scripts.bridge._call_llm_api",
                   return_value={"ok": True, "text": '{"text":"test","signals":[]}'}):
            do_post = getattr(handler, "do_POST", None)
            do_post()

        self.assertIsNone(getattr(db._local, "conn", None))


class TriggerLLMAutoTest(unittest.TestCase):

    def setUp(self):
        _setup_isolated_bridge(self)

    def tearDown(self):
        _teardown_isolated_bridge(self)

    def test_trigger_llm_auto_releases_connection(self):
        with patch("scripts.bridge._call_llm_api",
                   return_value={"ok": True, "text": '{"text":"auto test","signals":[]}'}), \
             patch("scripts.bridge.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 27, 10, 0, 0)
            mock_dt.strftime = datetime.strftime
            bridge.trigger_llm_auto()

        self.assertIsNone(getattr(db._local, "conn", None))

    def test_trigger_llm_auto_writes_to_temp_only(self):
        import hashlib
        real_llm = self.orig_llm
        h_before = hashlib.sha256(real_llm.read_bytes()).hexdigest() if real_llm.exists() else None

        with patch("scripts.bridge._call_llm_api",
                   return_value={"ok": True, "text": '{"text":"auto check","signals":[{"type":"INFO","target":"科技","code":"","window":"—","direction":"—","confidence":"中","basis":[]}]}'}), \
             patch("scripts.bridge.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 27, 10, 0, 0)
            mock_dt.strftime = datetime.strftime
            bridge.trigger_llm_auto()

        if h_before and real_llm.exists():
            h_after = hashlib.sha256(real_llm.read_bytes()).hexdigest()
            self.assertEqual(h_before, h_after, "不应写真实 llm_insights.json")


class W2TrendValidationTest(unittest.TestCase):
    """趋势 W2 BUY 技术条件对齐 W09 组件"""

    def _make_rs(self, tradable=True, w2_buy=True):
        from scripts.rule_engine import evaluate_rule_state as ev
        return ev(
            {"account": {"pnl_pct": 0.5, "valuation_complete": True},
             "risk": {"loss_streak": 0},
             "style": {"score": 85, "lianban_pct": 54, "trend_pct": 46},
             "sentiment": {"emotion_pct": 65, "previous_emotion_pct": 45,
                            "limit_up_profit_pct": 3.0, "broken_board_pct": 20,
                            "promotion_pct": 22},
             "freshness": {"quotes": "live", "sentiment": "live"}},
            __import__("datetime").datetime(2026, 5, 27, 14, 10))

    def test_trend_w2_all_conditions_pass(self):
        snap = {"指数": {}, "情绪": {"emotion_pct": 65}, "连板池": [], "趋势池": [
            {"标的": "测试", "代码": "000001", "涨幅": "-2", "量比": "0.5",
             "MA10_60m": "145", "MA10_60m_dir": "向上", "最新价": "145"}],
            "持仓": [], "板块": [], "风控": {}, "涨停梯队TOP5": [],
            "rule_state": self._make_rs()}
        signals = [{"type": "BUY", "target": "测试", "code": "000001",
                     "window": "W2", "direction": "多", "confidence": "高"}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "✅", f"应通过: {verified[0]['note']}")

    def test_trend_w2_ma_dir_down_is_warning(self):
        snap = {"指数": {}, "情绪": {}, "连板池": [], "趋势池": [
            {"标的": "测试", "代码": "000001", "涨幅": "-2", "量比": "0.5",
             "MA10_60m": "145", "MA10_60m_dir": "向下"}],
            "持仓": [], "板块": [], "风控": {}, "涨停梯队TOP5": [],
            "rule_state": self._make_rs()}
        signals = [{"type": "BUY", "target": "测试", "code": "000001",
                     "window": "W2", "direction": "多", "confidence": "高"}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "⚠️")
        self.assertIn("MA10方向", verified[0]["note"])

    def test_trend_w2_no_shrink_is_warning(self):
        snap = {"指数": {}, "情绪": {}, "连板池": [], "趋势池": [
            {"标的": "测试", "代码": "000001", "涨幅": "-2", "量比": "1.5",
             "MA10_60m": "145", "MA10_60m_dir": "向上"}],
            "持仓": [], "板块": [], "风控": {}, "涨停梯队TOP5": [],
            "rule_state": self._make_rs()}
        signals = [{"type": "BUY", "target": "测试", "code": "000001",
                     "window": "W2", "direction": "多", "confidence": "高"}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "⚠️")
        self.assertIn("量比", verified[0]["note"])

    def test_trend_w2_crashed_is_warning(self):
        snap = {"指数": {}, "情绪": {}, "连板池": [], "趋势池": [
            {"标的": "测试", "代码": "000001", "涨幅": "-7", "量比": "0.5",
             "MA10_60m": "145", "MA10_60m_dir": "向上"}],
            "持仓": [], "板块": [], "风控": {}, "涨停梯队TOP5": [],
            "rule_state": self._make_rs()}
        signals = [{"type": "BUY", "target": "测试", "code": "000001",
                     "window": "W2", "direction": "多", "confidence": "高"}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "⚠️")
        self.assertIn("涨幅=-7", verified[0]["note"])

    def test_w2_missing_ma_dir_is_warning(self):
        snap = {"指数": {}, "情绪": {}, "连板池": [], "趋势池": [
            {"标的": "测试", "代码": "000001", "涨幅": "-2", "量比": "0.5",
             "MA10_60m": "145", "MA10_60m_dir": "—"}],
            "持仓": [], "板块": [], "风控": {}, "涨停梯队TOP5": [],
            "rule_state": self._make_rs()}
        signals = [{"type": "BUY", "target": "测试", "code": "000001",
                     "window": "W2", "direction": "多", "confidence": "高"}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "⚠️")
        self.assertIn("缺MA10方向", verified[0]["note"])

    def test_lianban_w2_diverge_conditions(self):
        snap = {"指数": {}, "情绪": {"情绪值": 65}, "连板池": [
            {"标的": "连板测试", "代码": "000002", "板块": "科技", "角色": "情绪标",
             "涨幅": "-3", "量比": "0.6", "MA10_60m": "100", "MA10_60m_dir": "—"}],
            "趋势池": [], "持仓": [], "板块": [], "风控": {}, "涨停梯队TOP5": [],
            "rule_state": self._make_rs()}
        signals = [{"type": "BUY", "target": "连板测试", "code": "000002",
                     "window": "W2", "direction": "多", "confidence": "高"}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "✅",
                         f"连板W2分歧回落应通过: {verified[0]['note']}")


    def test_trend_w2_price_far_from_ma_is_warning(self):
        snap = {"指数": {}, "情绪": {}, "连板池": [], "趋势池": [
            {"标的": "测试", "代码": "000001", "涨幅": "5", "量比": "0.5",
             "MA10_60m": "145", "MA10_60m_dir": "向上", "最新价": "150"}],
            "持仓": [], "板块": [], "风控": {}, "涨停梯队TOP5": [],
            "rule_state": self._make_rs()}
        signals = [{"type": "BUY", "target": "测试", "code": "000001",
                     "window": "W2", "direction": "多", "confidence": "高"}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "⚠️")
        self.assertIn("距MA10", verified[0]["note"])

    def test_trend_w2_illegal_chg_is_warning(self):
        snap = {"指数": {}, "情绪": {}, "连板池": [], "趋势池": [
            {"标的": "测试", "代码": "000001", "涨幅": "abc", "量比": "0.5",
             "MA10_60m": "145", "MA10_60m_dir": "向上", "最新价": "145"}],
            "持仓": [], "板块": [], "风控": {}, "涨停梯队TOP5": [],
            "rule_state": self._make_rs()}
        signals = [{"type": "BUY", "target": "测试", "code": "000001",
                     "window": "W2", "direction": "多", "confidence": "高"}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "⚠️")
        self.assertIn("涨", verified[0]["note"])

    def test_trend_w2_illegal_vol_is_warning(self):
        snap = {"指数": {}, "情绪": {}, "连板池": [], "趋势池": [
            {"标的": "测试", "代码": "000001", "涨幅": "-2", "量比": "xyz",
             "MA10_60m": "145", "MA10_60m_dir": "向上", "最新价": "145"}],
            "持仓": [], "板块": [], "风控": {}, "涨停梯队TOP5": [],
            "rule_state": self._make_rs()}
        signals = [{"type": "BUY", "target": "测试", "code": "000001",
                     "window": "W2", "direction": "多", "confidence": "高"}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "⚠️")
        self.assertIn("量比", verified[0]["note"])

    def test_lianban_w2_emotion_10_is_warning(self):
        """连板 W2 情绪值=10（冰点）应 warning"""
        snap = {"指数": {}, "情绪": {"情绪值": 10}, "连板池": [
            {"标的": "连板测试", "代码": "000002", "板块": "科技", "角色": "情绪标",
             "涨幅": "-3", "量比": "0.6", "MA10_60m": "100", "MA10_60m_dir": "—"}],
            "趋势池": [], "持仓": [], "板块": [], "风控": {}, "涨停梯队TOP5": [],
            "rule_state": self._make_rs()}
        signals = [{"type": "BUY", "target": "连板测试", "code": "000002",
                     "window": "W2", "direction": "多", "confidence": "高"}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "⚠️")
        self.assertIn("情绪", verified[0]["note"])

    def test_lianban_w2_emotion_missing_is_warning(self):
        """连板 W2 缺情绪数据应 warning"""
        snap = {"指数": {}, "情绪": {}, "连板池": [
            {"标的": "连板测试", "代码": "000002", "板块": "科技", "角色": "情绪标",
             "涨幅": "-3", "量比": "0.6", "MA10_60m": "100", "MA10_60m_dir": "—"}],
            "趋势池": [], "持仓": [], "板块": [], "风控": {}, "涨停梯队TOP5": [],
            "rule_state": self._make_rs()}
        signals = [{"type": "BUY", "target": "连板测试", "code": "000002",
                     "window": "W2", "direction": "多", "confidence": "高"}]
        verified = bridge._verify_signals(signals, snap)
        self.assertEqual(verified[0]["status"], "⚠️")
        self.assertIn("缺情绪", verified[0]["note"])


class JsonSchemaTest(unittest.TestCase):
    """JSON schema 校验"""

    def test_basis_missing_is_warning(self):
        raw = '{"text":"t","signals":[{"type":"BUY","target":"x","window":"W2","direction":"多","confidence":"高"}]}'
        _, sigs, warns = bridge._parse_llm_response(raw)
        self.assertEqual(len(sigs), 1)
        self.assertIn("_schema_errors", sigs[0])
        self.assertTrue(any("basis" in e for e in sigs[0]["_schema_errors"]),
                        f"应有basis schema错误: {sigs[0]['_schema_errors']}")

    def test_basis_not_array_is_warning(self):
        raw = '{"text":"t","signals":[{"type":"BUY","target":"x","window":"W2","direction":"多","confidence":"高","basis":"not array"}]}'
        _, sigs, warns = bridge._parse_llm_response(raw)
        self.assertEqual(len(sigs), 1)
        self.assertIn("_schema_errors", sigs[0])
        self.assertTrue(any("basis" in e for e in sigs[0]["_schema_errors"]),
                        f"应有basis schema错误: {sigs[0]['_schema_errors']}")

    def test_json_with_extra_text_before_is_warning(self):
        raw = 'extra text\n{"text":"t","signals":[]}'
        _, _, warns = bridge._parse_llm_response(raw)
        self.assertTrue(any("extra text" in w for w in warns), f"应有extra text警告: {warns}")

    def test_json_with_extra_text_after_is_warning(self):
        raw = '{"text":"t","signals":[]}\nmore text'
        _, _, warns = bridge._parse_llm_response(raw)
        self.assertTrue(any("extra text" in w for w in warns), f"应有extra text警告: {warns}")


if __name__ == "__main__":
    unittest.main()
