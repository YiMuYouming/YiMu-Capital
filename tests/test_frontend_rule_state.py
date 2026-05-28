"""test_frontend_rule_state.py — 真实 Widget 渲染回归测试 (Gate 1B+)

在 Node 中加载并执行真实 widget 源文件，mock 最小运行时，
验证关键 rule_state fixture 下的渲染输出不含误导致命结论。
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── 最小 Node 运行环境 preamble（加载真实源文件前注入） ──
PREAMBLE = r"""
// Mock DOM
if (typeof document === 'undefined') {
  global.document = { createElement: function() {
    return { innerHTML: '', style: {}, getAttribute: function() { return null; },
      setAttribute: function() {}, querySelector: function() { return null; },
      querySelectorAll: function() { return []; },
      addEventListener: function() {} };
  }};
}
// Mock YiMuWidget base class
if (typeof YiMuWidget === 'undefined') {
  global.YiMuWidget = function() {};
  YiMuWidget.prototype.getBody = function() {
    return document.createElement('div');
  };
  YiMuWidget.prototype.updateTimestamp = function() {};
}
// Mock DataStore — subclassable per test
global.DataStore = {
  merged: {},
  initialBase: null,
  manualData: { getAll: function() { return {}; } },
  getInitialBase: function() { return this.initialBase; },
  get: function(p) {
    var parts = p.split('.'); var v = this.merged;
    for (var i = 0; i < parts.length; i++) { if (v == null) return; v = v[parts[i]]; }
    return v;
  }
};
// Mock WidgetRegistry
global.WidgetRegistry = {
  _map: {},
  register: function(id, cls) { this._map[id] = cls; },
  getClass: function(id) { return this._map[id]; },
  getMeta: function() { return {}; }
};
"""

# ── 公共：加载 widget 文件 + fixture → 渲染 HTML ──

def _render_widget(widget_file, widget_id, data_fixture, extra_js=""):
    """在 Node 中加载真实 widget 文件，用 fixture data 调用 render()，返回 HTML"""
    wpath = ROOT / "widgets" / widget_file
    if not wpath.exists():
        return {"_error": f"file not found: {widget_file}"}

    with open(wpath, encoding="utf-8") as f:
        widget_src = f.read()

    script = PREAMBLE + "\n" + extra_js + "\n" + widget_src + "\n"

    # 实例化并渲染
    script += r"""
var cls = WidgetRegistry._map["WIDGET_ID"];
if (!cls) { console.log(JSON.stringify({_error: "Widget not registered"})); process.exit(); }
var inst = new cls({id: "WIDGET_ID"});
// Inject body
inst.getBody = function() { var d = document.createElement('div'); this._body = d; return d; };
inst.render(DATA_FIXTURE);
var html = inst._body.innerHTML.replace(/\s+/g, ' ');
console.log(JSON.stringify({html: html}));
""".replace("WIDGET_ID", widget_id).replace("DATA_FIXTURE", json.dumps(data_fixture))

    result = subprocess.run(
        ["node", "--no-warnings", "-e", script],
        capture_output=True, text=True, timeout=10,
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        return {"_error": result.stderr.strip()[:600]}
    try:
        return json.loads(result.stdout.strip().split("\n")[-1])
    except json.JSONDecodeError:
        return {"_error": result.stdout.strip()[:400]}


# ── 公共 fixtures ──

def _day_stop_fixture():
    return {
        "rule_state": {
            "version": "g1a-v1", "tradable": False, "market_regime": "低迷",
            "caps": {"base_total_pct": 40, "total_pct": 0, "lianban_pct": 0,
                      "trend_pct": 0, "first_entry_pct": 0},
            "windows": {
                "w1": {"in_session": False, "buy_allowed": False, "blocks": ["DAY_STOP"]},
                "w2": {"in_session": True, "buy_allowed": False, "blocks": ["DAY_STOP"]},
            },
            "blocks": [{"code": "DAY_STOP", "scope": "all", "message": "单日熔断触发",
                          "evidence": {"pnl_pct": -4.0}}],
            "warnings": [],
        },
        "sentiment": {"情绪值": 45},
        "live_index": {},
        "live_quotes": {},
        "lianban_pool": [{"标的": "测试连板", "代码": "000001", "板块": "科技",
                           "角色": "情绪标", "操作": "低吸", "窗口": "W2",
                           "涨幅": "+3"}],
        "trend_pool": [{"标的": "测试趋势", "代码": "000002", "板块": "科技",
                          "角色": "持仓", "窗口": "W2", "涨幅": "-2"}],
    }


def _missing_rs_fixture():
    return {
        "sentiment": {"情绪值": 45, "竞价情绪值": 45},
        "live_index": {},
        "live_quotes": {},
        "decision": {"盘中": {"V反检测": {"场景": "V反", "当前状态": "观察"}}},
        "pnl_live": {"total_asset": 100000, "cash": 60000, "mv": 40000},
        "positions": [],
        "risk": {"熔断触发": False, "连亏天数": 0, "周累计回撤": 2, "月累计回撤": 5},
        "style": {"总仓位上限": 40, "连板占比": 54, "趋势占比": 46},
    }


class W09DayStopTest(unittest.TestCase):
    """DAY_STOP fixture 下 W09 无买入/低吸"""

    def test_w09_trend_no_buy_under_day_stop(self):
        result = _render_widget("w2-check.js", "W09", _day_stop_fixture())
        html = result.get("html", "")
        self.assertNotIn("买入", html,
                         f"DAY_STOP 下趋势候选不应含买入: {html[:200]}")
        self.assertNotIn("✓ 买入", html)

    def test_w09_lianban_no_dip_under_day_stop(self):
        result = _render_widget("w2-check.js", "W09", _day_stop_fixture())
        html = result.get("html", "")
        self.assertNotIn("低吸", html,
                         f"DAY_STOP 下连板候选不应含低吸: {html[:200]}")
        self.assertNotIn("✓ 低吸", html)
        self.assertIn("关闭", html,
                      f"DAY_STOP 下候选应显示 '关闭': {html[:200]}")


class W07W14W19MissingRuleStateTest(unittest.TestCase):
    """rule_state 缺失时各组件降级为不可确认"""

    def test_w07_missing_rs_shows_unavailable(self):
        result = _render_widget("climax-guard.js", "W07", _missing_rs_fixture())
        html = result.get("html", "")
        self.assertIn("不可用", html, f"W07 缺失 rule_state 应显示不可用: {html[:200]}")
        self.assertNotIn("未触发", html)
        self.assertNotIn("W1 正常", html)
        self.assertNotIn("W2 正常", html)

    def test_w14_missing_rs_shows_unavailable(self):
        result = _render_widget("risk-panel.js", "W14", _missing_rs_fixture())
        html = result.get("html", "")
        self.assertIn("不可用", html, f"W14 缺失 rule_state 应显示不可用: {html[:200]}")

    def test_w19_missing_rs_no_double_ice_conclusion(self):
        result = _render_widget("midday-review.js", "W19", _missing_rs_fixture())
        html = result.get("html", "")
        self.assertIn("不可用", html,
                      f"W19 缺失 rule_state 双冰应显示不可用: {html[:200]}")
        self.assertNotIn("无双冰 (rule_state)", html)


class RuleCodeDisplayTest(unittest.TestCase):
    """W03/W14 不应把机器规则码直接暴露给交易界面"""

    def test_w03_translates_rule_codes(self):
        result = _render_widget("position-calc.js", "W03", _day_stop_fixture())
        html = result.get("html", "")
        self.assertNotIn("DAY_STOP", html, f"W03 不应裸露机器码: {html[:300]}")
        self.assertIn("单日熔断", html, f"W03 应显示中文规则说明: {html[:300]}")

    def test_w14_translates_rule_codes(self):
        result = _render_widget("risk-panel.js", "W14", _day_stop_fixture())
        html = result.get("html", "")
        self.assertNotIn("DAY_STOP", html, f"W14 不应裸露机器码: {html[:300]}")
        self.assertIn("单日熔断", html, f"W14 应显示中文规则说明: {html[:300]}")

    def test_w14_groups_system_and_trade_risk(self):
        fixture = _day_stop_fixture()
        fixture["rule_state"]["blocks"] = [
            {"code": "DATA_UNTRUSTED", "scope": "all", "message": "账户估值或行情数据不可信", "evidence": {}},
            {"code": "LOSS_STREAK", "scope": "all", "message": "连亏触发强制空仓", "evidence": {"loss_streak": 2}},
            {"code": "W2_ICE_RISK", "scope": "w2", "message": "W2 冰点风险过高", "evidence": {}},
        ]
        fixture["rule_state"]["caps"] = {
            "base_total_pct": 20, "total_pct": 0,
            "lianban_side_cap_pct": 0, "trend_side_cap_pct": 20,
            "first_entry_pct": 0,
        }
        result = _render_widget("risk-panel.js", "W14", fixture)
        html = result.get("html", "")
        self.assertIn("账户风控", html, f"W14 应展示账户风控分组: {html[:500]}")
        self.assertIn("系统状态", html, f"W14 应把数据健康单独分组: {html[:500]}")
        self.assertIn("交易条件", html, f"W14 应把 W1/W2 条件单独分组: {html[:500]}")
        self.assertIn("收盘/行情状态", html, f"W14 数据不可信应避免吓人的红字主文案: {html[:500]}")

    def test_w03_shows_baseline_and_execution_sources(self):
        fixture = _day_stop_fixture()
        fixture["style"] = {"总仓位上限": 40, "连板占比": 45, "趋势占比": 55}
        result = _render_widget("position-calc.js", "W03", fixture)
        html = result.get("html", "")
        self.assertIn("执行上限", html, f"W03 应区分实时执行口径: {html[:500]}")
        self.assertIn("风格基线", html, f"W03 应展示 W02 风格基线: {html[:500]}")
        self.assertIn("全局门禁", html, f"W03 阻断应分组展示: {html[:500]}")


class W01TimelineRenderTest(unittest.TestCase):
    """W01 时间线应在低高度组件内渲染核心状态"""

    def test_w01_renders_visible_status_and_segments(self):
        result = _render_widget(
            "timeline.js", "W01", {"meta": {"weekday": "周三"}},
            extra_js="global.setInterval = function(){ return 0; };"
        )
        html = result.get("html", "")
        self.assertTrue(
            ("盘前准备" in html) or ("已闭市" in html) or ("窗口" in html) or ("休市" in html),
            f"W01 应显示当前状态: {html[:300]}",
        )
        self.assertIn("全天进度", html, f"W01 应显示进度: {html[:300]}")
        self.assertIn("time-line", html, f"W01 应使用稳定布局 class: {html[:300]}")


class W02StyleDisplayTest(unittest.TestCase):
    """W02 应清楚展示每日风格基线，避免误认为实时开仓门禁"""

    def test_w02_labels_daily_baseline_and_market_volume(self):
        result = _render_widget("style-detect.js", "W02", {
            "meta": {"date": "2026-05-27", "updated": "2026-05-27T21:18:31+08:00"},
            "style": {
                "总分": 45,
                "风格": "混合（偏趋势）",
                "置信度": 53,
                "连板占比": 42,
                "趋势占比": 58,
                "总仓位上限": 40,
                "_iwencai_全市场成交额": 32400,
                "dim1_量能": 17,
                "dim2_连板生态": 9,
                "dim3_趋势": 12,
                "dim4_情绪广度": 7,
                "一进二晋级率": 14.71,
                "二进三晋级率": 37.5,
                "三进四晋级率": 0.0,
                "连板信号描述": "连板偏弱（谨慎开仓）",
                "趋势信号描述": "趋势正常",
            },
        })
        html = result.get("html", "")
        self.assertIn("每日基线", html, f"W02 应标明这是每日基线: {html[:400]}")
        self.assertIn("基线仓位", html, f"W02 仓位口径应避免误认为实时可开仓: {html[:400]}")
        self.assertIn("3.24万亿", html, f"W02 应展示可读成交额: {html[:400]}")
        self.assertNotIn("class=\"tag down\"", html, f"W02 不应用涨跌色表达趋势风格: {html[:400]}")

    def test_w02_weak_dimension_uses_renderable_progress_class(self):
        result = _render_widget("style-detect.js", "W02", {
            "style": {
                "总分": 42,
                "风格": "混合（均衡）",
                "连板占比": 45,
                "趋势占比": 55,
                "dim1_量能": 17,
                "dim2_连板生态": 9,
                "dim3_趋势": 9,
                "dim4_情绪广度": 7,
            },
        })
        html = result.get("html", "")
        self.assertIn("progress-fill danger", html, f"W02 弱项应输出 danger 进度条: {html[:400]}")

        css = (ROOT / "css" / "theme.css").read_text(encoding="utf-8")
        self.assertIn(".progress-fill.danger", css)


class StoreMergeRuleStateTest(unittest.TestCase):
    """store.js 真实 DataStore 流程可取得 rule_state"""

    def test_store_fetch_all_merges_rule_state(self):
        """执行 store.js，mock fetch→fetchAll→merge，验证 merged 含 rule_state"""
        store_path = ROOT / "store.js"
        with open(store_path, encoding="utf-8") as f:
            store_src = f.read()

        script = r"""
(async function() {
if (typeof window === 'undefined') global.window = {};
if (typeof location === 'undefined') global.location = { protocol: 'http:' };
if (typeof EventSource === 'undefined') global.EventSource = function() {};
if (typeof EMBEDDED_DATA === 'undefined') global.EMBEDDED_DATA = null;
var callCount = 0;
global.fetch = function(url) {
  callCount++;
  var isBase = callCount === 1;
  var data = isBase
    ? { meta: { date: "2026-05-27" }, sentiment: {}, market: {}, lianban_pool: [], trend_pool: [], positions: [], sectors: [], risk: {}, style: {} }
    : { rule_state: { version: "g1a-v1", tradable: true, caps: {}, windows: {w1:{},w2:{}}, blocks: [], warnings: [] }, live_index: {}, live_quotes: {}, _freshness: {} };
  return Promise.resolve({ ok: true, json: function() { return Promise.resolve(data); } });
};
""" + store_src + r"""
var got = null, errMsg = '';
try {
  await DataStore.fetchAll();
  // Allow microtasks/timers to settle
  await new Promise(function(r) { setTimeout(r, 100); });
} catch(e) { errMsg = String(e).slice(0, 200); }
got = DataStore.merged ? DataStore.merged.rule_state : null;
console.log(JSON.stringify({
  ok: !!(got),
  version: got ? got.version : null,
  tradable: got ? got.tradable : null,
  hasMerged: DataStore.merged !== null && DataStore.merged !== undefined,
  mergedType: typeof DataStore.merged,
  err: errMsg
}));
})();
"""
        result = subprocess.run(
            ["node", "--no-warnings", "-e", script],
            capture_output=True, text=True, timeout=15,
            cwd=str(ROOT),
        )
        resp = json.loads(result.stdout.strip().split("\n")[-1])
        self.assertTrue(resp.get("ok"), f"merged 应含 rule_state: {resp}")
        self.assertEqual(resp.get("version"), "g1a-v1")


if __name__ == "__main__":
    unittest.main()



class W1TradeEntryGateTest(unittest.TestCase):
    """v3 Phase 4: W1 录入入口按 trade_entry_allowed 关闭"""

    def test_w1_closed_when_trade_entry_disallowed(self):
        """trade_entry_allowed=false → W1 显示关闭状态"""
        fixture = _day_stop_fixture()
        fixture['trade_entry_allowed'] = False
        fixture['trade_entry_reason'] = '锚点被阻断'
        result = _render_widget("w1-check.js", "W08", fixture)
        html = result.get("html", "")
        self.assertIn("关闭", html, f"trade_entry_allowed=false W1 应显示关闭: {html[:200]}")

    def test_w1_shows_candidates_when_trade_entry_allowed(self):
        """trade_entry_allowed=true 且 rule_state 正常 → W1 显示候选"""
        fixture = {
            "rule_state": {
                "version": "g1a-v1", "tradable": True,
                "caps": {"base_total_pct": 40, "total_pct": 20},
                "windows": {"w1": {"in_session": True, "buy_allowed": True},
                            "w2": {"in_session": True, "buy_allowed": True}},
                "blocks": [], "warnings": [],
            },
            "sentiment": {"情绪值": 65},
            "live_index": {}, "live_quotes": {},
            "lianban_pool": [], "trend_pool": [],
            "trade_entry_allowed": True,
        }
        result = _render_widget("w1-check.js", "W08", fixture)
        html = result.get("html", "")
        self.assertNotIn("关闭", html, f"trade_entry_allowed=true W1 不应说关闭: {html[:200]}")


class W2TradeEntryGateTest(unittest.TestCase):
    """v3 Phase 4: W2 录入入口按 trade_entry_allowed 关闭"""

    def test_w2_closed_when_trade_entry_disallowed(self):
        """trade_entry_allowed=false → W2 显示关闭状态"""
        fixture = _day_stop_fixture()
        fixture['trade_entry_allowed'] = False
        fixture['trade_entry_reason'] = '锚点被阻断'
        result = _render_widget("w2-check.js", "W09", fixture)
        html = result.get("html", "")
        self.assertIn("关闭", html, f"trade_entry_allowed=false W2 应显示关闭: {html[:200]}")

    def test_w2_shows_candidates_when_trade_entry_allowed(self):
        """trade_entry_allowed=true 且 rule_state 正常 → W2 显示候选"""
        fixture = {
            "rule_state": {
                "version": "g1a-v1", "tradable": True,
                "caps": {"base_total_pct": 40, "total_pct": 20},
                "windows": {"w1": {"in_session": True, "buy_allowed": True},
                            "w2": {"in_session": True, "buy_allowed": True}},
                "blocks": [], "warnings": [],
            },
            "sentiment": {"情绪值": 65},
            "live_index": {}, "live_quotes": {},
            "lianban_pool": [{"标的": "测试连板", "代码": "000001", "板块": "科技",
                               "角色": "情绪标", "涨幅": "+3"}],
            "trend_pool": [{"标的": "测试趋势", "代码": "000002", "板块": "科技",
                             "角色": "持仓", "涨幅": "-2"}],
            "trade_entry_allowed": True,
        }
        result = _render_widget("w2-check.js", "W09", fixture)
        html = result.get("html", "")
        self.assertNotIn("关闭", html, f"trade_entry_allowed=true W2 不应说关闭: {html[:200]}")


if __name__ == "__main__":
    unittest.main()
