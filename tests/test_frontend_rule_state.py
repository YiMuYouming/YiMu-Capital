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

    def test_w14_loss_streak_warning_is_not_shown_as_normal(self):
        fixture = _missing_rs_fixture()
        fixture["risk"]["连亏天数"] = 2
        fixture["rule_state"] = {
            "version": "g1a-v1",
            "tradable": True,
            "caps": {
                "base_total_pct": 60, "total_pct": 60,
                "lianban_side_cap_pct": 60, "trend_side_cap_pct": 40,
                "first_entry_pct": 10,
            },
            "windows": {"w1": {}, "w2": {}},
            "blocks": [],
            "warnings": [
                {"code": "LOSS_STREAK", "scope": "position",
                 "message": "连亏计数提示，盘前预案已覆盖",
                 "evidence": {"loss_streak": 2, "max_days": 2}},
            ],
        }
        result = _render_widget("risk-panel.js", "W14", fixture)
        html = result.get("html", "")
        self.assertIn("连亏计数提示，盘前预案已覆盖", html,
                      f"W14 应展示连亏 warning: {html[:600]}")
        self.assertIn("2天", html, f"W14 风控线应展示 warning 中的连亏天数: {html[:600]}")
        self.assertIn("⚠ 提示", html, f"W14 连亏 warning 不应显示为正常: {html[:600]}")
        self.assertNotIn("2天</span><span style=\"color:var(--info)\">✓ 正常", html)

    def test_w03_shows_baseline_and_execution_sources(self):
        fixture = _day_stop_fixture()
        fixture["style"] = {"总仓位上限": 40, "连板占比": 45, "趋势占比": 55}
        result = _render_widget("position-calc.js", "W03", fixture)
        html = result.get("html", "")
        self.assertIn("执行上限", html, f"W03 应区分实时执行口径: {html[:500]}")
        self.assertIn("风格基线", html, f"W03 应展示 W02 风格基线: {html[:500]}")
        self.assertIn("全局门禁", html, f"W03 阻断应分组展示: {html[:500]}")

    def test_w03_keeps_plan_allocation_visible_when_execution_blocked(self):
        fixture = _day_stop_fixture()
        fixture["style"] = {
            "总仓位上限": 60,
            "连板占比": 0,
            "趋势占比": 100,
            "新开趋势W2上限": "10-14%",
        }
        fixture["pnl_live"] = {"total_asset": 719324.67, "mv": 285999, "cash": 433325.67}
        fixture["rule_state"]["caps"] = {
            "base_total_pct": 40,
            "total_pct": 0,
            "lianban_pct": 0,
            "trend_pct": 0,
            "first_entry_pct": 0,
        }
        result = _render_widget("position-calc.js", "W03", fixture)
        html = result.get("html", "")
        self.assertIn("计划分配", html, f"W03 阻断时仍应展示计划分配: {html[:700]}")
        self.assertIn("连板 0% / 趋势 100%", html, f"W03 应展示附录A计划分配: {html[:700]}")
        self.assertIn("W2 10-14%", html, f"W03 应展示附录A新开趋势上限: {html[:700]}")
        self.assertIn("计划 <b>60%</b>", html, f"W03 第一层应同时展示计划仓位: {html[:700]}")
        self.assertIn("计划可新开", html, f"W03 应显示计划可新开金额: {html[:900]}")
        self.assertIn("145,596", html, f"W03 应按总上限60%扣除已持仓计算计划空间: {html[:900]}")
        self.assertIn("W2趋势上限", html, f"W03 应显示 W2 新开仓位范围: {html[:900]}")

    def test_w03_shows_future_windows_as_pending_not_closed(self):
        fixture = _missing_rs_fixture()
        fixture["rule_state"] = {
            "version": "g1a-v1",
            "tradable": True,
            "caps": {
                "base_total_pct": 60, "total_pct": 60,
                "lianban_pct": 57, "trend_pct": 43, "first_entry_pct": 10,
            },
            "windows": {
                "w1": {"in_session": False, "buy_allowed": False, "blocks": []},
                "w2": {"in_session": False, "buy_allowed": False, "blocks": []},
            },
            "blocks": [],
            "warnings": [],
        }
        fixture["style"] = {"总仓位上限": 60, "连板占比": 57, "趋势占比": 43}
        result = _render_widget("position-calc.js", "W03", fixture)
        html = result.get("html", "")
        self.assertIn("09:30-10:00", html, f"W1 未到时段应展示窗口时间: {html[:600]}")
        self.assertIn("14:00-14:50", html, f"W2 未到时段应展示窗口时间: {html[:600]}")
        self.assertIn("待开", html, f"未到时段应显示待开而不是关闭: {html[:600]}")
        self.assertNotIn("关闭（非W1）", html)
        self.assertNotIn("关闭（非W2）", html)


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


class TradeTicketsWidgetRenderTest(unittest.TestCase):
    def test_w24_renders_ticket_sections_and_blocking_rules(self):
        result = _render_widget("trade-tickets.js", "W24", {
            "trade_tickets": [
                {"ticket_id": "TICKET-1", "code": "002281", "name": "光迅科技", "action_type": "buy", "status": "executable", "window": "W2", "max_qty": 100},
                {"ticket_id": "TICKET-2", "code": "002475", "name": "立讯精密", "action_type": "sell", "status": "blocked", "sellable_quantity": 0, "blocking_rule_ids": ["sellable_qty"]},
                {"ticket_id": "TICKET-3", "code": "000001", "name": "测试", "action_type": "buy", "status": "filled"},
            ]
        })
        self.assertNotIn("_error", result)
        html = result["html"]
        self.assertIn("待确认", html)
        self.assertIn("可执行", html)
        self.assertIn("已阻断", html)
        self.assertIn("已成交/关闭", html)
        self.assertIn("sellable_qty", html)

    def test_w24_displays_linked_trades_and_conflict_summary(self):
        result = _render_widget("trade-tickets.js", "W24", {
            "trade_tickets": [
                {
                    "ticket_id": "TICKET-CONFLICT",
                    "code": "600726",
                    "name": "华电能源",
                    "action_type": "clear",
                    "status": "closed_with_conflict",
                    "linked_trade_ids": [42, 45, 46],
                    "conflicts": [
                        {
                            "conflict_type": "T1_SELLABLE_QTY",
                            "expected_value": "7000",
                            "actual_value": "10000",
                        }
                    ],
                }
            ]
        })
        self.assertNotIn("_error", result)
        html = result["html"]
        self.assertIn("trade 42,45,46", html)
        self.assertIn("T1_SELLABLE_QTY", html)
        self.assertIn("7000", html)
        self.assertIn("10000", html)

    def test_w24_mount_uses_base_render_lifecycle(self):
        base_src = (ROOT / "widget-base.js").read_text(encoding="utf-8")
        widget_src = (ROOT / "widgets" / "trade-tickets.js").read_text(encoding="utf-8")
        script = r"""
global.document = {
  body: { classList: { add: function(){}, remove: function(){} } },
  addEventListener: function(){},
  createElement: function() {
    return {
      className: '', textContent: '', title: '',
      classList: { add: function(){}, remove: function(){} },
      querySelector: function(){ return null; },
      insertBefore: function(){}
    };
  },
  querySelector: function(){ return null; }
};
global.DataStore = {
  merged: { trade_tickets: [] },
  tiers: { manual: {} },
  subscribe: function(){ return function(){}; },
  refresh: function(){}
};
global.WidgetRegistry = {
  _map: {},
  register: function(id, cls) { this._map[id] = cls; }
};
""" + base_src + "\n" + widget_src + r"""
var bodyEl = {
  innerHTML: '',
  style: {},
  querySelector: function(){ return null; }
};
var errEl = { style: {} };
var tsEl = {
  textContent: '',
  classList: { add: function(){}, remove: function(){} },
  querySelector: function(){ return null; },
  insertBefore: function(){}
};
var container = {
  innerHTML: '',
  addEventListener: function(){},
  querySelector: function(sel) {
    if (sel === '.widget-body') return bodyEl;
    if (sel === '.widget-error') return errEl;
    if (sel === '.data-timestamp') return tsEl;
    return null;
  },
  closest: function() { return { classList: { add: function(){}, remove: function(){} } }; }
};
var cls = WidgetRegistry._map["W24"];
var inst = new cls({id:"W24", type:"trade-tickets", title:"交易票据", category:"risk", tier:"manual", dataPaths:["trade_tickets"], defaultSize:{w:12,h:5}});
inst.mount(container);
console.log(JSON.stringify({html: bodyEl.innerHTML.replace(/\s+/g, ' ')}));
"""
        result = subprocess.run(
            ["node", "--no-warnings", "-e", script],
            capture_output=True, text=True, timeout=10,
            cwd=str(ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        html = json.loads(result.stdout.strip().split("\n")[-1])["html"]
        self.assertIn("待确认", html)
        self.assertNotIn("widget-skeleton", html)

    def test_w24_prepare_preview_confirm_frontend_flow(self):
        widget_src = (ROOT / "widgets" / "trade-tickets.js").read_text(encoding="utf-8")
        script = PREAMBLE + "\n" + widget_src + r"""
(async function() {
var calls = [];
global.fetch = function(url, opts) {
  calls.push({url: String(url), method: (opts && opts.method) || 'GET', body: opts && opts.body ? JSON.parse(opts.body) : null});
  if (String(url) === '/api/trade/tickets/prepare') {
    return Promise.resolve({ok:true, json:function(){ return Promise.resolve({ok:true, ticket:{ticket_id:'TICKET-UI-1', status:'executable', code:'002281', name:'光迅科技'}}); }});
  }
  if (String(url) === '/api/trade/fills/preview') {
    return Promise.resolve({ok:true, json:function(){ return Promise.resolve({ok:true, requires_confirmation:true, confirmation_id:'CONFIRM-UI-1', preview_token:'tok', preview_hash:'sha256:abc', parsed:{qty:200}}); }});
  }
  if (String(url) === '/api/trade/fills/confirm') {
    return Promise.resolve({ok:true, json:function(){ return Promise.resolve({ok:true, trade_id:49, ticket_id:'TICKET-UI-1'}); }});
  }
  if (String(url) === '/api/trade/tickets') {
    return Promise.resolve({ok:true, json:function(){ return Promise.resolve({tickets:[{ticket_id:'TICKET-UI-1', status:'filled', code:'002281', name:'光迅科技', linked_trade_ids:[49]}]}); }});
  }
  return Promise.resolve({ok:false, json:function(){ return Promise.resolve({error:'unexpected'}); }});
};
var body = {
  innerHTML: '',
  querySelector: function(){ return null; },
  querySelectorAll: function(){ return []; }
};
var cls = WidgetRegistry._map["W24"];
var inst = new cls({id:"W24"});
inst.getBody = function() { this._body = body; return body; };
inst.render({trade_tickets: []});
await inst._prepareTicket({intent_text:'准备 W2 买 光迅科技', action_type:'buy', code:'002281', name:'光迅科技', window:'W2', qty:200});
await inst._previewFill({ticket_id:'TICKET-UI-1', input_text:'已买 光迅科技 200股 222.38'});
await inst._confirmFill({confirmed_by:'yimu'});
await new Promise(function(r){ setTimeout(r, 20); });
console.log(JSON.stringify({calls:calls, html:body.innerHTML.replace(/\s+/g, ' '), pending:inst._pendingPreview}));
})();
"""
        result = subprocess.run(
            ["node", "--no-warnings", "-e", script],
            capture_output=True, text=True, timeout=10,
            cwd=str(ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        resp = json.loads(result.stdout.strip().split("\n")[-1])
        urls = [c["url"] for c in resp["calls"]]
        self.assertLess(urls.index("/api/trade/tickets/prepare"), urls.index("/api/trade/fills/preview"))
        self.assertLess(urls.index("/api/trade/fills/preview"), urls.index("/api/trade/fills/confirm"))
        self.assertIn("/api/trade/tickets", urls)
        by_url = {c["url"]: c for c in resp["calls"] if c["body"]}
        self.assertEqual(by_url["/api/trade/tickets/prepare"]["body"]["window"], "W2")
        self.assertEqual(by_url["/api/trade/fills/preview"]["body"]["ticket_id"], "TICKET-UI-1")
        self.assertEqual(by_url["/api/trade/fills/confirm"]["body"]["preview_hash"], "sha256:abc")
        self.assertIsNone(resp["pending"])
        self.assertIn("trade 49", resp["html"])

    def test_w24_fetches_api_when_datastore_ticket_list_is_empty(self):
        widget_src = (ROOT / "widgets" / "trade-tickets.js").read_text(encoding="utf-8")
        script = PREAMBLE + "\n" + widget_src + r"""
(async function() {
var calls = [];
global.fetch = function(url) {
  calls.push(String(url));
  if (String(url) === '/api/trade/tickets') {
    return Promise.resolve({ok:true, json:function(){ return Promise.resolve({tickets:[{ticket_id:'TICKET-API-1', status:'blocked', code:'002281', name:'光迅科技', action_type:'reduce', blocking_rule_ids:['sellable_qty']} ]}); }});
  }
  return Promise.resolve({ok:false, json:function(){ return Promise.resolve({error:'unexpected'}); }});
};
var body = {
  innerHTML: '',
  querySelector: function(){ return null; },
  querySelectorAll: function(){ return []; }
};
var cls = WidgetRegistry._map["W24"];
var inst = new cls({id:"W24"});
inst.getBody = function() { this._body = body; return body; };
inst.render({trade_tickets: []});
await new Promise(function(r){ setTimeout(r, 20); });
console.log(JSON.stringify({calls:calls, html:body.innerHTML.replace(/\s+/g, ' ')}));
})();
"""
        result = subprocess.run(
            ["node", "--no-warnings", "-e", script],
            capture_output=True, text=True, timeout=10,
            cwd=str(ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        resp = json.loads(result.stdout.strip().split("\n")[-1])
        self.assertIn("/api/trade/tickets", resp["calls"])
        self.assertIn("TICKET-API-1", resp["html"])
        self.assertIn("sellable_qty", resp["html"])

    def test_w15_manual_backfill_copy_and_payload_metadata(self):
        src = (ROOT / "widgets" / "positions.js").read_text(encoding="utf-8")
        self.assertIn("手工补录成交", src)
        self.assertIn("优先用交易票据确认成交", src)
        self.assertIn("manual_backfill", src)
        self.assertIn("audit_note", src)

    def test_index_exposes_ticket_entry_and_default_workspace(self):
        src = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-widget="W24"', src)
        self.assertIn("_addWidgetToGrid('W24')", src)
        self.assertIn("本地预览 · 只读", src)

    def test_w23_groups_review_rows_by_ticket_or_trade_group(self):
        wpath = ROOT / "widgets" / "trade-review.js"
        widget_src = wpath.read_text(encoding="utf-8")
        reviews = [
            {"id": 42, "ticket_id": "T-HD", "trade_group_id": "G-HD", "name": "华电能源", "action": "卖出", "code": "600726", "qty": 3000, "price": 3.1},
            {"id": 45, "ticket_id": "T-HD", "trade_group_id": "G-HD", "name": "华电能源", "action": "卖出", "code": "600726", "qty": 4000, "price": 3.2},
            {"id": 43, "ticket_id": "T-GX", "trade_group_id": "G-GX", "name": "光迅科技", "action": "买入", "code": "002281", "qty": 500, "price": 39.1},
        ]
        script = PREAMBLE + "\n" + widget_src + r"""
var cls = WidgetRegistry._map["W23"];
var inst = new cls({id:"W23"});
inst.getBody = function() { var d = document.createElement('div'); this._body = d; return d; };
var body = inst.getBody();
inst._renderTable(body, REVIEWS, "2026-06-03");
console.log(JSON.stringify({html: body.innerHTML.replace(/\s+/g, ' ')}));
""".replace("REVIEWS", json.dumps(reviews))
        result = subprocess.run(
            ["node", "--no-warnings", "-e", script],
            capture_output=True, text=True, timeout=10,
            cwd=str(ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        html = json.loads(result.stdout.strip().split("\n")[-1])["html"]
        self.assertIn("华电能源", html)
        self.assertIn("清仓/卖出票据", html)
        self.assertIn("trade 42,45", html)
        self.assertIn("光迅科技", html)
        self.assertIn("买入票据", html)
        self.assertIn("trade 43", html)


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


class W04MarketOverviewTest(unittest.TestCase):
    """W04 市场全景成交额与昨日基线口径"""

    def test_w04_uses_midday_same_period_turnover_not_scaled_full_day(self):
        extra_js = """
var RealDate = Date;
global.Date = class extends RealDate {
  constructor() {
    if (arguments.length === 0) return new RealDate('2026-05-29T11:59:00+08:00');
    return new RealDate(...arguments);
  }
  static now() { return new RealDate('2026-05-29T11:59:00+08:00').getTime(); }
  static parse(v) { return RealDate.parse(v); }
  static UTC() { return RealDate.UTC.apply(RealDate, arguments); }
};
"""
        result = _render_widget("market-overview.js", "W04", {
            "live_index": {
                "成交额": "2.12万亿",
                "上涨家数": 1849,
                "下跌家数": 3336,
            },
            "yesterday_baseline": {
                "上证昨成交额": "2.97万亿",
                "昨日午间成交额": "1.78万亿",
            },
        }, extra_js=extra_js)
        html = result.get("html", "")
        self.assertIn("昨午盘", html, f"W04 应标明午盘同段比较: {html[:700]}")
        self.assertIn("+3400亿", html, f"W04 应显示同段多约 3400 亿: {html[:700]}")
        self.assertIn("+19.1%", html, f"W04 应使用午盘同段而非全天进度估算: {html[:700]}")
        self.assertNotIn("+42.8%", html)

    def test_w04_does_not_estimate_same_period_turnover_when_backend_compare_missing(self):
        extra_js = """
var RealDate = Date;
global.Date = class extends RealDate {
  constructor() {
    if (arguments.length === 0) return new RealDate('2026-06-02T11:05:00+08:00');
    return new RealDate(...arguments);
  }
  static now() { return new RealDate('2026-06-02T11:05:00+08:00').getTime(); }
  static parse(v) { return RealDate.parse(v); }
  static UTC() { return RealDate.UTC.apply(RealDate, arguments); }
};
"""
        result = _render_widget("market-overview.js", "W04", {
            "live_index": {
                "成交额": "1.67万亿",
                "上涨家数": 1255,
                "下跌家数": 3957,
            },
            "yesterday_baseline": {
                "昨日全天成交额": "2.88万亿",
            },
        }, extra_js=extra_js)
        html = result.get("html", "")
        self.assertNotIn("昨同段估算", html, f"W04 不应按全天线性估算同段: {html[:700]}")
        self.assertNotIn("+5300亿", html)
        self.assertNotIn("-100.0%", html)

    def test_w04_renders_shenzhen_chuangye_baseline_and_no_pending_llm(self):
        result = _render_widget("market-overview.js", "W04", {
            "live_index": {},
            "yesterday_baseline": {
                "上证昨涨幅": "+0.12%",
                "上证昨成交额": "2.97万亿",
                "深证昨涨幅": "-0.50%",
                "深证昨成交额": "1.12万亿",
                "创业昨涨幅": "+1.96%",
                "创业昨成交额": "5200亿",
            },
        })
        html = result.get("html", "")
        self.assertIn("深证", html, f"W04 应展示深证昨日基线: {html[:900]}")
        self.assertIn("-0.50%", html, f"W04 应展示深证昨日涨幅: {html[:900]}")
        self.assertIn("创业", html, f"W04 应展示创业昨日基线: {html[:900]}")
        self.assertIn("+1.96%", html, f"W04 应展示创业昨日涨幅: {html[:900]}")
        self.assertNotIn("待研判", html)
        self.assertNotIn("🤖", html)

    def test_w04_uses_iwencai_zero_limit_counts_not_baseline(self):
        result = _render_widget("market-overview.js", "W04", {
            "live_index": {},
            "market": {"涨停家数": 100, "跌停家数": 8},
            "iwencai": {"涨停家数": 0, "跌停家数": 0, "_updated": "2026-05-29T14:17:56+08:00"},
            "sentiment": {},
        })
        html = result.get("html", "")
        self.assertIn(">0</span>/<span class=\"down\">0<", html,
                      f"W04 应采用问财实时 0/0，不应回退昨日基线: {html[:800]}")
        self.assertNotIn(">100</span>/<span class=\"down\">8<", html)

    def test_w04_does_not_show_baseline_returns_as_live_when_iwencai_partial(self):
        result = _render_widget("market-overview.js", "W04", {
            "live_index": {},
            "market": {},
            "iwencai": {"涨停家数": 0, "跌停家数": 0, "_updated": "2026-05-29T14:17:56+08:00"},
            "sentiment": {
                "昨日涨停收益": 0.84,
                "连板收益": 4.01,
                "昨日炸板收益": 12.74,
            },
        })
        html = result.get("html", "")
        self.assertIn("昨停今日", html, f"W04 收益标签应标明口径: {html[:900]}")
        self.assertNotIn("+0.84%", html, f"盘中问财收益缺失时不应显示复盘基线: {html[:900]}")
        self.assertNotIn("+4.01%", html, f"盘中问财收益缺失时不应显示复盘基线: {html[:900]}")
        self.assertNotIn("+12.74%", html, f"盘中问财收益缺失时不应显示复盘基线: {html[:900]}")


class W10SectorHeatTest(unittest.TestCase):
    """W10 应以复盘板块为主线，实时数据只做校验"""

    def test_w10_uses_sector_inflow_and_removes_noise(self):
        result = _render_widget("sector-heat.js", "W10", {
            "sectors": [
                {"板块": "半导体🔥🔥", "类型": "趋势主线", "涨停数": "~10",
                 "梯队": "2板+首板", "龙头": "中京电子3板/紫光",
                 "状态": "+111亿🔥🔥趋势确认，均线上升中"},
                {"板块": "电力⚡", "类型": "防守参考", "涨停数": "~5",
                 "梯队": "2板+首板", "龙头": "粤电力A2板",
                 "状态": "延续走强，防守属性"},
            ],
            "sector_inflow": {"data": [
                {"name": "电力", "change_pct": 3.09, "net_inflow_yi": 76.35,
                 "up_count": 100, "down_count": 9, "leader": "珈伟新能",
                 "leader_change_pct": 13.04},
            ]},
            "trend_pool": [
                {"标的": "⭐紫光国微", "代码": "002049", "板块": "半导体🔥",
                 "角色": "主趋势股", "操作": "持仓处理", "涨幅": "+1.46%✅"},
            ],
            "lianban_pool": [],
            "live_quotes": {"002049": {"涨幅": -5.12}},
        })
        html = result.get("html", "")
        self.assertIn("复盘板块", html, f"W10 应展示新版表头: {html[:600]}")
        self.assertIn("+3.09%", html, f"W10 应读取 sector_inflow 涨跌幅: {html[:800]}")
        self.assertIn("+76.3亿", html, f"W10 应读取 sector_inflow 净流入: {html[:800]}")
        self.assertIn("涨跌 100:9", html, f"W10 应展示涨跌家数: {html[:800]}")
        self.assertIn("紫光国微", html, f"W10 应保留关键标的: {html[:800]}")
        self.assertIn("-5.12%", html, f"W10 无官方板块涨跌时应回退到自选池实时涨幅: {html[:800]}")
        self.assertIn("池均", html, f"W10 自选池涨幅回退应标注池均口径: {html[:800]}")
        self.assertNotIn("待分析", html)
        self.assertNotIn("🔥", html)
        self.assertNotIn("⭐", html)

    def test_w10_falls_back_to_review_status_metrics(self):
        result = _render_widget("sector-heat.js", "W10", {
            "sectors": [
                {"板块": "元件/PCB🚨", "类型": "趋势分歧", "涨停数": "~5",
                 "梯队": "2板+首板", "龙头": "中京电子3板",
                 "状态": "+3.72%但主力-39.51亿🚨量价背离"},
            ],
            "sector_inflow": {"data": []},
            "trend_pool": [],
            "lianban_pool": [],
            "live_quotes": {},
        })
        html = result.get("html", "")
        self.assertIn("+3.72%", html, f"W10 无实时数据时应从复盘状态抽涨幅: {html[:700]}")
        self.assertIn("-39.5亿", html, f"W10 无实时数据时应从复盘状态抽资金: {html[:700]}")
        self.assertIn("复盘", html, f"W10 应标注复盘口径: {html[:700]}")


class W21ZtEchelonTest(unittest.TestCase):
    """W21 应区分确认涨停、问财连板与同花顺热榜观察"""

    def test_w21_does_not_treat_hot_list_as_confirmed_zt(self):
        extra_js = """
var RealDate = Date;
global.Date = class extends RealDate {
  constructor() {
    if (arguments.length === 0) return new RealDate('2026-05-29T12:30:00+08:00');
    return new RealDate(...arguments);
  }
  static now() { return new RealDate('2026-05-29T12:30:00+08:00').getTime(); }
  static parse(v) { return RealDate.parse(v); }
  static UTC() { return RealDate.UTC.apply(RealDate, arguments); }
};
global.localStorage = {
  _data: {},
  getItem: function(k) { return this._data[k] || null; },
  setItem: function(k, v) { this._data[k] = String(v); }
};
global.fetch = function() { return Promise.resolve({ok: false}); };
"""
        result = _render_widget("zt-echelon.js", "W21", {
            "hot_list": {
                "date": "2026-05-29",
                "source": "ths_hot",
                "total": 2,
                "zt_count": 0,
                "zt_stocks": [],
                "stocks": [
                    {"code": "301373", "name": "凌玮科技", "zhangfu": 0.0,
                     "reason": "球形硅微粉+业绩增长"},
                    {"code": "603989", "name": "艾华集团", "zhangfu": 0.0,
                     "reason": "AI服务器+新能源"},
                ],
                "reason_stats": {"球形硅微粉": 1, "AI服务器": 1},
                "zt_history": {
                    "2026-05-28": [
                        {"code": "002272", "name": "川润股份", "zhangfu": 10.01,
                         "reason": "电力"}
                    ]
                },
            },
            "iwencai": {"连板股列表": [
                {"代码": "000090", "名称": "天健集团", "连板数": 2, "所属概念": "地产"},
                {"代码": "000539", "名称": "粤电力A", "连板数": 3, "所属概念": "电力"},
            ]},
        }, extra_js=extra_js)
        html = result.get("html", "")
        self.assertIn("问财连板", html, f"W21 应展示问财确认连板源: {html[:900]}")
        self.assertIn("3板", html, f"W21 应渲染连板阶梯: {html[:900]}")
        self.assertIn("热榜观察", html, f"W21 热榜股票只能作为观察池: {html[:900]}")
        self.assertIn("首板源未确认", html, f"W21 应提示今日首板源不可用: {html[:900]}")
        self.assertNotIn("最高板: <b>—</b>", html)
        self.assertNotIn("共2只", html, f"W21 不应把热榜 2 只计为确认涨停: {html[:900]}")
        self.assertNotIn("🤖", html)


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

    def test_store_fetch_all_merges_trade_tickets(self):
        store_path = ROOT / "store.js"
        with open(store_path, encoding="utf-8") as f:
            store_src = f.read()

        script = r"""
(async function() {
if (typeof window === 'undefined') global.window = {};
if (typeof location === 'undefined') global.location = { protocol: 'http:' };
if (typeof EventSource === 'undefined') global.EventSource = function() {};
if (typeof EMBEDDED_DATA === 'undefined') global.EMBEDDED_DATA = null;
global.fetch = function(url) {
  var u = String(url);
  if (u.indexOf('/api/baseline') >= 0) {
    return Promise.resolve({ ok: true, json: function() { return Promise.resolve({ meta: {}, market: {}, sentiment: {}, lianban_pool: [], trend_pool: [] }); } });
  }
  if (u.indexOf('/api/live/quotes') >= 0) {
    return Promise.resolve({ ok: true, json: function() { return Promise.resolve({ live_quotes: {}, rule_state: { version: "g1a-v1" } }); } });
  }
  if (u.indexOf('/api/pnl/summary') >= 0) {
    return Promise.resolve({ ok: true, json: function() { return Promise.resolve({ total_asset: 100000 }); } });
  }
  if (u.indexOf('/api/trade/tickets') >= 0) {
    return Promise.resolve({ ok: true, json: function() { return Promise.resolve({ tickets: [{ ticket_id: "T-1", status: "executable" }] }); } });
  }
  return Promise.resolve({ ok: false, json: function() { return Promise.resolve(null); } });
};
""" + store_src + r"""
await DataStore.fetchAll();
await new Promise(function(r) { setTimeout(r, 20); });
console.log(JSON.stringify({tickets: DataStore.merged && DataStore.merged.trade_tickets}));
})();
"""
        result = subprocess.run(
            ["node", "--no-warnings", "-e", script],
            capture_output=True, text=True, timeout=15,
            cwd=str(ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        resp = json.loads(result.stdout.strip().split("\n")[-1])
        self.assertEqual(resp["tickets"][0]["ticket_id"], "T-1")


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
