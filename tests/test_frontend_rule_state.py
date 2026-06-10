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
var body = document.createElement('div');
var inst = new cls({id: "WIDGET_ID"});
inst.getBody = function() { return body; };
inst.render(DATA_FIXTURE);
var html = body.innerHTML.replace(/\s+/g, ' ');
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
        self.assertIn("ui-degraded", html, f"W07 缺失 rule_state 应使用统一降级态: {html[:200]}")
        self.assertNotIn("未触发", html)
        self.assertNotIn("W1 正常", html)
        self.assertNotIn("W2 正常", html)

    def test_w14_missing_rs_shows_unavailable(self):
        result = _render_widget("risk-panel.js", "W14", _missing_rs_fixture())
        html = result.get("html", "")
        self.assertIn("不可用", html, f"W14 缺失 rule_state 应显示不可用: {html[:200]}")
        self.assertIn("ui-degraded", html, f"W14 缺失 rule_state 应使用统一降级态: {html[:300]}")

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

    def test_w14_shows_command_summary_first(self):
        fixture = _day_stop_fixture()
        result = _render_widget("risk-panel.js", "W14", fixture)
        html = result.get("html", "")
        theme = (ROOT / "css" / "theme.css").read_text()
        self.assertIn("w14-command", html, f"W14 应先展示风控指令摘要: {html[:500]}")
        self.assertIn("风控门禁", html, f"W14 应有主结论标题: {html[:500]}")
        self.assertIn("交易状态", html, f"W14 应前置交易状态: {html[:500]}")
        self.assertIn("执行仓位", html, f"W14 应前置执行仓位: {html[:500]}")
        self.assertLess(html.index("w14-command"), html.index("w14-gate"),
                        f"W14 主结论应在风险分组前: {html[:700]}")
        self.assertIn(".w14-command-grid", theme)
        self.assertIn(".w14-risk-lines", theme)


class TradeTicketsStatusGroupingTest(unittest.TestCase):
    """W24 票据分组不应把可确认的审计降级票据显示成已阻断"""

    def test_audit_degraded_is_not_grouped_as_blocked(self):
        src = (ROOT / "widgets" / "trade-tickets.js").read_text(encoding="utf-8")

        self.assertNotIn(
            "t.status === 'blocked' || t.status === 'audit_degraded'",
            src,
            "audit_degraded 可继续成交确认，不应归入已阻断列",
        )
        self.assertIn(
            "return s === 'audit_degraded' || s === 'executable'",
            src,
            "audit_degraded 应与可执行票据同列展示",
        )

    def test_legacy_context_blocked_exit_ticket_is_displayed_as_audit_degraded(self):
        fixture = {
            "trade_tickets": [
                {
                    "ticket_id": "TICKET-20260609-002281-0007",
                    "status": "blocked",
                    "action_type": "clear",
                    "code": "002281",
                    "name": "光迅科技",
                    "max_qty": 200,
                    "sellable_quantity": 200,
                    "blocking_rule_ids": ["context_status"],
                },
                {
                    "ticket_id": "TICKET-20260609-301488-0002",
                    "status": "blocked",
                    "action_type": "buy",
                    "code": "301488",
                    "name": "豪恩汽电",
                    "max_qty": 500,
                    "blocking_rule_ids": ["DOUBLE_ICE"],
                },
            ],
        }

        result = _render_widget("trade-tickets.js", "W24", fixture)
        html = result.get("html", "")

        self.assertIn("审计降级", html, f"旧 context_status 清仓票应显示审计降级: {html[:900]}")
        self.assertIn("审计原因 context_status", html, f"旧 context_status 清仓票应显示审计原因: {html[:900]}")
        self.assertIn("阻断原因 DOUBLE_ICE", html, f"买入硬阻断仍应显示阻断原因: {html[:900]}")
        self.assertIn(
            "已阻断</span><span class=\"ticket-section-count\">1</span>",
            html,
            f"已阻断分组应只包含真实硬阻断: {html[:900]}",
        )

    def test_superseded_legacy_context_exit_tickets_are_hidden(self):
        fixture = {
            "trade_tickets": [
                {
                    "ticket_id": "TICKET-20260609-002281-0007",
                    "created_at": "2026-06-09 10:08:37",
                    "status": "blocked",
                    "action_type": "clear",
                    "code": "002281",
                    "name": "光迅科技",
                    "max_qty": 200,
                    "sellable_quantity": 200,
                    "blocking_rule_ids": ["context_status"],
                },
                {
                    "ticket_id": "TICKET-20260609-002281-0008",
                    "created_at": "2026-06-09 10:09:56",
                    "status": "filled",
                    "action_type": "sell",
                    "code": "002281",
                    "name": "光迅科技",
                },
                {
                    "ticket_id": "TICKET-20260609-301488-0002",
                    "created_at": "2026-06-09 09:38:04",
                    "status": "blocked",
                    "action_type": "buy",
                    "code": "301488",
                    "name": "豪恩汽电",
                    "max_qty": 500,
                    "blocking_rule_ids": ["DOUBLE_ICE"],
                },
            ],
        }

        result = _render_widget("trade-tickets.js", "W24", fixture)
        html = result.get("html", "")

        self.assertNotIn("TICKET-20260609-002281-0007", html, f"已被后续成交覆盖的旧清仓审计票不应占可执行列: {html[:1200]}")
        self.assertIn("TICKET-20260609-002281-0008", html, f"后续真实成交票应保留: {html[:1200]}")
        self.assertIn("TICKET-20260609-301488-0002", html, f"买入硬阻断票应保留: {html[:1200]}")
        self.assertNotIn("审计降级", html, f"被成交覆盖后不应再显示审计降级待执行: {html[:1200]}")

    def test_w14_sanitizes_rule_state_dynamic_text(self):
        fixture = _missing_rs_fixture()
        fixture["rule_state"] = {
            "version": "g1a-v1",
            "tradable": False,
            "caps": {
                "base_total_pct": "40<img src=x onerror=alert(1)>",
                "total_pct": "0<img src=x onerror=alert(2)>",
                "lianban_side_cap_pct": "20<img src=x onerror=alert(3)>",
                "trend_side_cap_pct": "30<img src=x onerror=alert(4)>",
                "first_entry_pct": "10<img src=x onerror=alert(5)>",
            },
            "windows": {"w1": {}, "w2": {}},
            "blocks": [
                {"code": "CUSTOM_ALERT_alert(6)", "scope": "all",
                 "message": "<img src=x onerror=alert(7)>", "evidence": {}},
            ],
            "warnings": [
                {"code": "LOSS_STREAK", "scope": "position",
                 "message": "<img src=x onerror=alert(8)>",
                 "evidence": {"loss_streak": 2}},
            ],
        }
        result = _render_widget("risk-panel.js", "W14", fixture)
        html = result.get("html", "")
        self.assertNotIn("<img", html, f"W14 不应注入 HTML: {html[:900]}")
        self.assertNotIn("alert(", html, f"W14 不应显示污染脚本文案: {html[:900]}")
        self.assertIn("执行仓位 0%", html, f"W14 应保留合法 total_pct: {html[:600]}")

    def test_w14_sanitizes_loss_streak_evidence_number(self):
        fixture = _missing_rs_fixture()
        fixture["risk"]["连亏天数"] = 1
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
                 "message": "连亏计数提示",
                 "evidence": {"loss_streak": "2<img src=x onerror=alert(9)>"}},
            ],
        }
        result = _render_widget("risk-panel.js", "W14", fixture)
        html = result.get("html", "")
        self.assertNotIn("<img", html, f"W14 evidence 数字不应注入 HTML: {html[:900]}")
        self.assertNotIn("alert(", html, f"W14 evidence 数字不应显示污染脚本文案: {html[:900]}")
        self.assertIn("2天", html, f"W14 应保留 evidence 中合法连亏天数: {html[:600]}")

    def test_w14_scoped_block_uses_watch_visual_state(self):
        fixture = _missing_rs_fixture()
        fixture["rule_state"] = {
            "version": "g1a-v1",
            "tradable": True,
            "caps": {
                "base_total_pct": 60, "total_pct": 40,
                "lianban_side_cap_pct": 0, "trend_side_cap_pct": 40,
                "first_entry_pct": 10,
            },
            "windows": {"w1": {"buy_allowed": False}, "w2": {"buy_allowed": True}},
            "blocks": [
                {"code": "W1_EMOTION", "scope": "w1", "message": "W1 情绪不足", "evidence": {}},
            ],
            "warnings": [],
        }
        result = _render_widget("risk-panel.js", "W14", fixture)
        html = result.get("html", "")
        self.assertIn("w14-command is-watch", html,
                      f"W14 局部 block 应使用 watch 态，避免显示 ready 绿态: {html[:500]}")
        self.assertNotIn("w14-command is-ready", html)
        self.assertIn("提示", html, f"W14 局部 block 应显示提示结论: {html[:500]}")

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
        self.assertIn(">提示</span>", html, f"W14 连亏 warning 不应显示为正常: {html[:600]}")
        self.assertNotIn("2天</span><span style=\"color:var(--info)\">正常", html)

    def test_w03_shows_baseline_and_execution_sources(self):
        fixture = _day_stop_fixture()
        fixture["style"] = {"总仓位上限": 40, "连板占比": 45, "趋势占比": 55}
        result = _render_widget("position-calc.js", "W03", fixture)
        html = result.get("html", "")
        theme = (ROOT / "css" / "theme.css").read_text()
        self.assertIn("w03-command is-blocked", html, f"W03 应先展示仓位指令摘要: {html[:500]}")
        self.assertIn("仓位指令", html, f"W03 应有主结论标题: {html[:500]}")
        self.assertIn("可新开", html, f"W03 应把可新开金额前置: {html[:500]}")
        self.assertIn("执行上限", html, f"W03 应区分实时执行口径: {html[:500]}")
        self.assertIn("风格基线", html, f"W03 应展示 W02 风格基线: {html[:500]}")
        self.assertIn("全局门禁", html, f"W03 阻断应分组展示: {html[:500]}")
        self.assertIn(".w03-command-grid", theme)
        self.assertIn(".w03-track-lb{background:var(--up)}", theme)
        self.assertIn(".w03-track-trend{background:var(--info)}", theme)

    def test_w03_escapes_warning_messages(self):
        fixture = _missing_rs_fixture()
        fixture["rule_state"] = {
            "version": "g1a-v1",
            "tradable": True,
            "caps": {
                "base_total_pct": 60, "total_pct": 60,
                "lianban_pct": 57, "trend_pct": 43, "first_entry_pct": 10,
            },
            "windows": {"w1": {}, "w2": {}},
            "blocks": [],
            "warnings": [
                {"code": "CUSTOM", "scope": "position",
                 "message": "<img src=x onerror=alert(1)>",
                 "evidence": {}},
            ],
        }
        result = _render_widget("position-calc.js", "W03", fixture)
        html = result.get("html", "")
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html,
                      f"W03 warning 文案应转义: {html[:600]}")
        self.assertNotIn("<img src=x", html, f"W03 不应注入 HTML: {html[:600]}")

    def test_w03_sanitizes_caps_and_style_numbers(self):
        fixture = _missing_rs_fixture()
        fixture["style"] = {
            "总仓位上限": "60<img src=x onerror=alert(2)>",
            "连板占比": "56<img src=x onerror=alert(3)>",
            "趋势占比": "44<img src=x onerror=alert(4)>",
            "新开趋势W2上限": "10-14%<img src=x onerror=alert(5)>",
        }
        fixture["rule_state"] = {
            "version": "g1a-v1",
            "tradable": True,
            "caps": {
                "base_total_pct": "40<img src=x onerror=alert(6)>",
                "total_pct": "20<img src=x onerror=alert(7)>",
                "lianban_pct": "12<img src=x onerror=alert(8)>",
                "trend_pct": "8<img src=x onerror=alert(9)>",
                "first_entry_pct": "10<img src=x onerror=alert(10)>",
            },
            "windows": {"w1": {}, "w2": {}},
            "blocks": [],
            "warnings": [],
        }
        result = _render_widget("position-calc.js", "W03", fixture)
        html = result.get("html", "")
        self.assertNotIn("<img", html, f"W03 caps/style 不应注入 HTML: {html[:900]}")
        self.assertIn("20%", html, f"W03 应保留合法 total_pct 数值: {html[:500]}")
        self.assertIn("W2 10-14%", html, f"W03 应只展示合法 W2 区间: {html[:900]}")
        self.assertNotIn("alert(", html, f"W03 不应展示污染脚本文案: {html[:900]}")

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
        self.assertIn("timeline-shell", html, f"W01 应使用稳定布局 class: {html[:300]}")
        self.assertIn("timeline-track", html, f"W01 应使用稳定时间条 class: {html[:300]}")


class W11VolumeBarsRenderTest(unittest.TestCase):
    """W11 量价图应使用统一空态和稳定 tooltip class。"""

    def test_w11_empty_uses_shared_quiet_state(self):
        result = _render_widget("volume-bars.js", "W11", {})
        html = result.get("html", "")
        self.assertIn("w11-tip", html)
        self.assertIn("ui-empty", html)
        self.assertIn("w11-empty", html)
        self.assertIn("等待今日15min数据", html)
        self.assertNotIn("style=\"height:156px;display:flex", html)


class CandidatePoolWidgetTest(unittest.TestCase):
    def test_w12_lianban_pool_shows_summary_and_escapes_rows(self):
        fixture = {
            "lianban_pool": [
                {"标的": "<img src=x onerror=alert(1)>", "代码": "000001", "板块": "科技", "窗口": "W1", "角色": "1进2", "操作": "追涨", "涨幅": "+4.2%"},
                {"标的": "测试B", "代码": "000002", "板块": "消费", "窗口": "W2", "角色": "观察", "操作": "只盯", "涨幅": "-1.1%"},
            ],
            "live_quotes": {"000001": {"涨幅": "+5.0%", "最新价": "10.2"}},
        }
        result = _render_widget("lianban-pool.js", "W12", fixture)
        html = result.get("html", "")
        theme = (ROOT / "css" / "theme.css").read_text()
        self.assertIn("candidate-brief", html)
        self.assertIn("连板池验收", html)
        self.assertIn("W1", html)
        self.assertIn("W2", html)
        self.assertIn("candidate-table-wrap", html)
        self.assertNotIn("<img", html, f"W12 不应注入 HTML: {html[:900]}")
        self.assertNotIn("alert(", html, f"W12 不应显示污染脚本文案: {html[:900]}")
        self.assertIn("测试B", html)
        self.assertIn("000001", html)
        self.assertIn(".candidate-brief-grid", theme)

    def test_w13_trend_pool_shows_summary_and_escapes_rows(self):
        fixture = {
            "trend_pool": [
                {"标的": "趋势A", "代码": "000003", "板块": "AI", "窗口": "W2", "角色": "持仓", "操作": "买入", "涨幅": "+2.3%"},
                {"标的": "趋势B", "代码": "000004", "板块": "<script>alert(2)</script>", "窗口": "观察", "角色": "观察", "操作": "等待", "涨幅": "-0.5%"},
            ],
            "live_quotes": {"000003": {"涨幅": "+3.0%", "最新价": "20.1"}},
        }
        result = _render_widget("trend-pool.js", "W13", fixture)
        html = result.get("html", "")
        self.assertIn("candidate-brief", html)
        self.assertIn("趋势池验收", html)
        self.assertIn("W2", html)
        self.assertIn("观察", html)
        self.assertIn("candidate-table-wrap", html)
        self.assertNotIn("<script", html, f"W13 不应注入 HTML: {html[:900]}")
        self.assertNotIn("alert(", html, f"W13 不应显示污染脚本文案: {html[:900]}")
        self.assertIn("趋势A", html)
        self.assertIn("000004", html)


class TradeTicketsWidgetRenderTest(unittest.TestCase):
    def test_index_keeps_health_confirmed_when_trade_entry_is_blocked(self):
        src = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn(
            "window._healthCritical = true; window._healthConfirmed = true;",
            src,
            "健康接口已响应但 trade_entry_allowed=false 时，应标记为已确认的风控阻断",
        )

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
        self.assertIn("ticket-summary-grid", html)
        self.assertIn("ticket-summary-pill", html)
        self.assertIn("ticket-acceptance-rail", html)
        self.assertIn('data-ticket-stage="handoff"', html)
        self.assertIn('data-ticket-stage="execute"', html)
        self.assertIn('data-ticket-stage="review"', html)
        self.assertIn('data-ticket-stage="closed"', html)
        self.assertIn("AI交付", html)
        self.assertIn("终端执行", html)
        self.assertIn("规则复核", html)
        self.assertIn("闭环对账", html)
        self.assertIn("ticket-card", html)
        self.assertIn("ticket-section-title", html)
        self.assertIn("sellable_qty", html)
        self.assertIn("买入", html)
        self.assertIn("可执行", html)
        self.assertIn("阻断原因", html)
        self.assertIn("已成交", html)
        self.assertNotIn(">buy<", html)
        self.assertNotIn(">filled<", html)

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

    def test_w24_shows_execution_chain_from_ticket_to_account(self):
        result = _render_widget("trade-tickets.js", "W24", {
            "trade_tickets": [
                {"ticket_id": "TICKET-PENDING", "code": "002281", "name": "光迅科技", "action_type": "buy", "status": "executable"},
                {"ticket_id": "TICKET-FILLED", "code": "000001", "name": "测试A", "action_type": "buy", "status": "filled", "linked_trade_ids": [42]},
                {"ticket_id": "TICKET-CONFLICT", "code": "600726", "name": "华电能源", "action_type": "clear", "status": "closed_with_conflict", "linked_trade_ids": [45, 46], "conflicts": [{"conflict_type": "T1_SELLABLE_QTY"}]},
            ]
        })
        self.assertNotIn("_error", result)
        html = result["html"]
        self.assertIn("ticket-execution-chain", html)
        self.assertIn('data-ticket-chain="ticket"', html)
        self.assertIn('data-ticket-chain="trade"', html)
        self.assertIn('data-ticket-chain="account"', html)
        self.assertIn('data-ticket-chain="risk"', html)
        self.assertIn("执行链", html)
        self.assertIn("E2票据", html)
        self.assertIn("W23成交", html)
        self.assertIn("E1账户", html)
        self.assertIn("异常", html)
        self.assertIn("3张票据", html)
        self.assertIn("3笔成交", html)
        self.assertIn("2张待核", html)
        self.assertIn("1项冲突", html)
        self.assertLess(html.index("ticket-command-strip"), html.index("ticket-execution-chain"))
        self.assertLess(html.index("ticket-execution-chain"), html.index("ticket-acceptance-rail"))

    def test_w24_empty_sections_use_shared_quiet_state(self):
        result = _render_widget("trade-tickets.js", "W24", {"trade_tickets": []})
        self.assertNotIn("_error", result)
        html = result["html"]
        self.assertIn("ui-empty ui-empty-inline", html)
        self.assertIn("暂无", html)
        self.assertNotIn("border:1px dashed var(--border-light)", html)

    def test_w24_prioritizes_acceptance_view_and_keeps_emergency_entry(self):
        result = _render_widget("trade-tickets.js", "W24", {
            "trade_tickets": [
                {"ticket_id": "TICKET-DRAFT", "code": "002281", "name": "光迅科技", "action_type": "buy", "status": "draft", "window": "W2", "max_qty": 100},
                {"ticket_id": "TICKET-EXEC", "code": "000001", "name": "测试A", "action_type": "add", "status": "executable", "window": "W2", "max_qty": 200},
                {"ticket_id": "TICKET-BLOCK", "code": "000002", "name": "测试B", "action_type": "clear", "status": "blocked", "blocking_rule_ids": ["sellable_qty"]},
                {"ticket_id": "TICKET-FILLED", "code": "000003", "name": "测试C", "action_type": "sell", "status": "filled", "linked_trade_ids": [51]},
            ]
        })
        self.assertNotIn("_error", result)
        html = result["html"]
        self.assertIn("ticket-command-strip", html)
        self.assertIn("AI验收台", html)
        self.assertIn("下一步", html)
        self.assertIn("ticket-emergency-dock", html)
        self.assertIn("ticket-emergency-entry", html)
        self.assertIn("ticket-acceptance-rail", html)
        self.assertLess(html.index("ticket-command-strip"), html.index("ticket-acceptance-rail"))
        self.assertLess(html.index("ticket-acceptance-rail"), html.index("ticket-summary-grid"))
        self.assertIn("data-tt-prepare", html, "应急出票据入口必须保留")
        self.assertIn("data-tt-preview", html, "应急预览成交入口必须保留")
        self.assertIn("data-tt-confirm", html, "应急确认入账入口必须保留")
        self.assertLess(html.index("ticket-command-strip"), html.index("ticket-layout"))
        self.assertLess(html.index("ticket-layout"), html.index("ticket-emergency-entry"),
                        f"应急入口应收在主验收视图之后: {html[:1000]}")

    def test_w24_readonly_mode_hides_mutating_controls(self):
        readonly_js = """
global.window = {
  _detectRuntimeMode: function(){ return {readonly:true}; },
  _healthConfirmed: true,
  _healthCritical: false,
  _tradeEntryAllowed: true
};
"""
        result = _render_widget("trade-tickets.js", "W24", {
            "trade_tickets": [
                {"ticket_id": "TICKET-1", "code": "002281", "name": "光迅科技",
                 "action_type": "buy", "status": "executable", "window": "W2", "max_qty": 100}
            ]
        }, extra_js=readonly_js)
        self.assertNotIn("_error", result)
        html = result["html"]
        self.assertIn("只读闭环", html)
        self.assertNotIn("data-tt-prepare", html)
        self.assertNotIn("data-tt-preview", html)
        self.assertNotIn("data-tt-confirm", html)

    def test_w24_readonly_direct_write_methods_do_not_post(self):
        widget_src = (ROOT / "widgets" / "trade-tickets.js").read_text(encoding="utf-8")
        script = PREAMBLE + "\n" + r"""
global.window = {
  _detectRuntimeMode: function(){ return {readonly:true}; },
  _healthConfirmed: true,
  _healthCritical: false,
  _tradeEntryAllowed: true
};
""" + widget_src + r"""
(async function() {
var calls = [];
global.fetch = function(url, opts) {
  calls.push({url:String(url), method:(opts && opts.method) || 'GET'});
  return Promise.resolve({ok:true, json:function(){ return Promise.resolve({ok:true}); }});
};
var cls = WidgetRegistry._map["W24"];
var inst = new cls({id:"W24"});
var body = { innerHTML:'', querySelector:function(){ return null; }, querySelectorAll:function(){ return []; } };
inst.getBody = function(){ return body; };
var err = '';
try {
  await inst._prepareTicket({intent_text:'准备 W2 买 光迅科技', action_type:'buy', code:'002281', name:'光迅科技', window:'W2', qty:200});
} catch (e) {
  err = e && e.message || String(e);
}
console.log(JSON.stringify({calls:calls, err:err, status:inst._statusMessage}));
})();
"""
        result = subprocess.run(
            ["node", "--no-warnings", "-e", script],
            capture_output=True, text=True, timeout=10,
            cwd=str(ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        resp = json.loads(result.stdout.strip().split("\n")[-1])
        self.assertEqual([], resp["calls"])
        self.assertIn("只读", resp["err"])
        self.assertIn("只读", resp["status"])

    def test_w24_health_gate_blocks_buy_but_allows_clear_prepare(self):
        widget_src = (ROOT / "widgets" / "trade-tickets.js").read_text(encoding="utf-8")
        script = PREAMBLE + "\n" + r"""
global.window = {
  _detectRuntimeMode: function(){ return {readonly:false}; },
  _healthConfirmed: true,
  _healthCritical: true,
  _tradeEntryAllowed: false
};
""" + widget_src + r"""
(async function() {
var calls = [];
global.fetch = function(url, opts) {
  calls.push({url:String(url), method:(opts && opts.method) || 'GET', body:opts && opts.body ? JSON.parse(opts.body) : null});
  return Promise.resolve({ok:true, json:function(){ return Promise.resolve({ok:true, ticket:{ticket_id:'TICKET-EXIT', status:'audit_degraded', action_type:'clear'}}); }});
};
var cls = WidgetRegistry._map["W24"];
var inst = new cls({id:"W24"});
var body = { innerHTML:'', querySelector:function(){ return null; }, querySelectorAll:function(){ return []; } };
inst.getBody = function(){ return body; };
inst.render({trade_tickets: [{ticket_id:'TICKET-OLD', status:'executable', action_type:'clear', code:'002281', name:'光迅科技'}]});
var initialHtml = body.innerHTML.replace(/\s+/g, ' ');
var buyErr = '';
try {
  await inst._prepareTicket({intent_text:'准备买', action_type:'buy', code:'002281', name:'光迅科技', qty:100});
} catch (e) {
  buyErr = e && e.message || String(e);
}
await inst._prepareTicket({intent_text:'清仓', action_type:'clear', code:'002281', name:'光迅科技', qty:200});
console.log(JSON.stringify({calls:calls, buyErr:buyErr, initialHtml:initialHtml}));
})();
"""
        result = subprocess.run(
            ["node", "--no-warnings", "-e", script],
            capture_output=True, text=True, timeout=10,
            cwd=str(ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        resp = json.loads(result.stdout.strip().split("\n")[-1])
        prepare_calls = [c for c in resp["calls"] if c["url"] == "/api/trade/tickets/prepare"]
        self.assertEqual(1, len(prepare_calls), resp)
        self.assertEqual("clear", prepare_calls[0]["body"]["action_type"])
        self.assertIn("健康门禁", resp["buyErr"])
        self.assertIn("data-tt-prepare", resp["initialHtml"])

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

    def test_w24_preview_without_selected_ticket_shows_friendly_message(self):
        widget_src = (ROOT / "widgets" / "trade-tickets.js").read_text(encoding="utf-8")
        script = PREAMBLE + "\n" + widget_src + r"""
(async function() {
var calls = [];
global.fetch = function(url, opts) {
  calls.push({url:String(url), body: opts && opts.body ? JSON.parse(opts.body) : null});
  return Promise.resolve({ok:false, json:function(){ return Promise.resolve({error:'ticket not found:'}); }});
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
try {
  await inst._previewFill({input_text:'已卖 光迅科技 200股 232.30'});
} catch (e) {}
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
        self.assertNotIn("/api/trade/fills/preview", [c["url"] for c in resp["calls"]])
        self.assertIn("请先选择一张票据", resp["html"])
        self.assertNotIn("ticket not found", resp["html"])

    def test_w24_preserves_selected_action_in_form(self):
        widget_src = (ROOT / "widgets" / "trade-tickets.js").read_text(encoding="utf-8")
        script = PREAMBLE + "\n" + widget_src + r"""
var body = {
  innerHTML: '',
  querySelector: function(sel){
    if (sel === '[data-tt-action]') return {value:'reduce'};
    return {value:'', addEventListener:function(){}};
  },
  querySelectorAll: function(){ return []; }
};
var cls = WidgetRegistry._map["W24"];
var inst = new cls({id:"W24"});
inst.getBody = function() { this._body = body; return body; };
inst._selectedAction = 'reduce';
inst.render({trade_tickets: []});
var form = inst._readForm(body);
console.log(JSON.stringify({html:body.innerHTML.replace(/\s+/g, ' '), action:form.action_type}));
"""
        result = subprocess.run(
            ["node", "--no-warnings", "-e", script],
            capture_output=True, text=True, timeout=10,
            cwd=str(ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        resp = json.loads(result.stdout.strip().split("\n")[-1])
        self.assertEqual(resp["action"], "reduce")
        self.assertIn('value="reduce"', resp["html"])

    def test_w15_manual_backfill_copy_and_payload_metadata(self):
        src = (ROOT / "widgets" / "positions.js").read_text(encoding="utf-8")
        self.assertIn("手工补录成交", src)
        self.assertIn("优先用交易票据确认成交", src)
        self.assertIn("manual_backfill", src)
        self.assertIn("audit_note", src)
        self.assertIn("w15-kpi-grid", src)
        self.assertIn("w15-kpi-value", src)
        self.assertIn("data-table w15-table", src)

    def test_w15_readonly_mode_hides_manual_backfill(self):
        readonly_js = """
global.window = {
  _detectRuntimeMode: function(){ return {readonly:true}; },
  _healthConfirmed: true,
  _healthCritical: false,
  _tradeEntryAllowed: true
};
"""
        result = _render_widget("positions.js", "W15", {
            "pnl_live": {
                "total_asset": 100000,
                "cash": 100000,
                "mv": 0,
                "pos_pct": 0,
                "pnl_amount": 0,
                "pnl_pct": 0,
                "positions": [],
                "trades": [],
            },
            "live_quotes": {},
        }, extra_js=readonly_js)
        self.assertNotIn("_error", result)
        html = result["html"]
        self.assertIn("w15-readonly-lock", html)
        self.assertIn("只读", html)
        self.assertNotIn("w15_add", html)
        self.assertNotIn("应急补录", html)

    def test_w15_shows_account_acceptance_before_kpis(self):
        result = _render_widget("positions.js", "W15", {
            "pnl_live": {
                "total_asset": 200000,
                "cash": 100000,
                "mv": 100000,
                "pos_pct": 50,
                "pnl_amount": 500,
                "pnl_pct": 0.25,
                "quote_status": "close_snapshot",
                "valuation_complete": True,
                "positions": [
                    {"标的": "测试", "代码": "000001", "市值": 100000, "现价": 100, "成本": 98, "today_pnl": 500, "today_pnl_pct": 0.5, "状态": "持有"}
                ],
                "trades": [{"trade_time": "10:00", "action": "买入", "name": "测试", "code": "000001", "price": 100, "qty": 100}],
                "closed_positions": [{"name": "旧仓", "code": "000002", "sell_price": 20, "realized_today_pnl": 100, "reason": "止盈"}],
            },
            "live_quotes": {"000002": {"最新价": 21}},
        })
        self.assertNotIn("_error", result)
        html = result["html"]
        self.assertIn("w15-acceptance", html)
        self.assertIn('data-w15-check="valuation"', html)
        self.assertIn('data-w15-check="positions"', html)
        self.assertIn('data-w15-check="trades"', html)
        self.assertIn('data-w15-check="closed"', html)
        self.assertIn("账户验收", html)
        self.assertIn("估值状态", html)
        self.assertIn("持仓", html)
        self.assertIn("今日记录", html)
        self.assertIn("清仓追踪", html)
        self.assertLess(html.index("w15-acceptance"), html.index("w15-kpi-grid"))

    def test_index_exposes_ticket_entry_and_default_workspace(self):
        src = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-widget="W25"', src)
        self.assertIn('data-widget="W24"', src)
        self.assertIn("_ensureRequiredLayoutWidgets()", src)
        self.assertIn("本地预览 · 只读", src)
        self.assertIn("REQUIRED_LAYOUT_WIDGETS", src)

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
        self.assertIn("w23-toolbar", html)
        self.assertIn("filter-btn w23-filter-btn active", html)
        self.assertIn("w23-table-wrap", html)
        self.assertIn("data-table w23-table", html)
        self.assertIn("w23-group-row", html)
        self.assertIn("w23-summary-row", html)

    def test_w23_shows_review_acceptance_summary_before_table(self):
        wpath = ROOT / "widgets" / "trade-review.js"
        widget_src = wpath.read_text(encoding="utf-8")
        reviews = [
            {"id": 1, "trade_time": "10:01", "action": "买入", "name": "可信", "code": "000001", "qty": 100, "context_status": "trusted", "rule_state": {"tradable": True, "windows": {"w2": {"buy_allowed": True}}, "blocks": [], "warnings": []}, "market_snapshot": {"iwencai": {"情绪值": 59}, "live_index": {}}},
            {"id": 2, "trade_time": "10:02", "action": "卖出", "name": "未验证", "code": "000002", "qty": 100, "context_status": "unverified"},
            {"id": 3, "trade_time": "10:03", "action": "卖出", "name": "不可用", "code": "000003", "qty": 100, "context_status": "unavailable", "context_unavailable_reason": "历史补录"},
        ]
        script = PREAMBLE + "\n" + widget_src + r"""
var cls = WidgetRegistry._map["W23"];
var inst = new cls({id:"W23"});
inst.getBody = function() { var d = document.createElement('div'); this._body = d; return d; };
var body = inst.getBody();
inst._renderTable(body, REVIEWS, "2026-06-06");
console.log(JSON.stringify({html: body.innerHTML.replace(/\s+/g, ' ')}));
""".replace("REVIEWS", json.dumps(reviews))
        result = subprocess.run(
            ["node", "--no-warnings", "-e", script],
            capture_output=True, text=True, timeout=10,
            cwd=str(ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        html = json.loads(result.stdout.strip().split("\n")[-1])["html"]
        self.assertIn("w23-review-brief", html)
        self.assertIn("复盘验收", html)
        self.assertIn("已验证", html)
        self.assertIn("未验证", html)
        self.assertIn("不可用", html)
        self.assertLess(html.index("w23-review-brief"), html.index("w23-filter-bar"))
        self.assertLess(html.index("w23-review-brief"), html.index("w23-table-wrap"))

    def test_w23_empty_and_loading_use_shared_quiet_state(self):
        wpath = ROOT / "widgets" / "trade-review.js"
        widget_src = wpath.read_text(encoding="utf-8")
        script = PREAMBLE + "\n" + widget_src + r"""
var cls = WidgetRegistry._map["W23"];
var inst = new cls({id:"W23"});
inst.getBody = function() { var d = document.createElement('div'); this._body = d; return d; };
var body = inst.getBody();
inst._renderTable(body, [], "2026-06-03");
var emptyHtml = body.innerHTML.replace(/\s+/g, ' ');
body.innerHTML = inst._loadingHtml();
var loadingHtml = body.innerHTML.replace(/\s+/g, ' ');
inst._error = 'fail';
inst.render();
var errorHtml = inst._body.innerHTML.replace(/\s+/g, ' ');
console.log(JSON.stringify({emptyHtml: emptyHtml, loadingHtml: loadingHtml, errorHtml: errorHtml}));
"""
        result = subprocess.run(
            ["node", "--no-warnings", "-e", script],
            capture_output=True, text=True, timeout=10,
            cwd=str(ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip().split("\n")[-1])
        self.assertIn("ui-empty w23-empty", payload["emptyHtml"])
        self.assertIn("暂无成交记录", payload["emptyHtml"])
        self.assertIn("w23-filter-bar", payload["emptyHtml"])
        self.assertIn("ui-empty ui-empty-inline w23-loading", payload["loadingHtml"])
        self.assertIn("ui-degraded w23-error", payload["errorHtml"])
        self.assertNotIn("text-align:center;padding:var(--sp-md)", payload["errorHtml"])


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
        self.assertIn("style-detect-head", html, f"W02 应使用稳定头部布局 class: {html[:400]}")
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

    def test_w02_warning_and_exec_messages_are_escaped(self):
        result = _render_widget("style-detect.js", "W02", {
            "style": {
                "总分": 30,
                "风格": "混合<script>",
                "连板占比": 50,
                "趋势占比": 50,
                "预警": ["<script>alert(1)</script>"],
                "实际执行": {
                    "原因": "<b>硬卡</b>",
                    "原因2": "<img src=x onerror=alert(1)>",
                },
            },
        })
        html = result.get("html", "")
        self.assertIn("style-detect-warning", html)
        self.assertIn("style-detect-exec-block", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("&lt;b&gt;硬卡&lt;/b&gt;", html)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)


class W04MarketOverviewTest(unittest.TestCase):
    """W04 市场全景成交额与昨日基线口径"""

    def test_w04_uses_stable_layout_classes_and_escapes_dynamic_text(self):
        result = _render_widget("market-overview.js", "W04", {
            "live_index": {
                "上证指数": "<script>alert(1)</script>",
                "上证指数涨幅": "+1.23%",
                "深证指数": "10000",
                "深证指数涨幅": "-0.45%",
                "创业指数": "2000",
                "创业指数涨幅": "<img src=x onerror=alert(1)>",
                "成交额": "<b>2万亿</b>",
                "上涨家数": "<u>3000</u>",
                "下跌家数": 2000,
            },
            "live_breadth": {"_total": 100, "涨停": 5, "0~3%": 45, "-0~-3%": 50},
            "yesterday_baseline": {
                "上证昨涨幅": "<svg onload=alert(1)>",
                "上证昨成交额": "2.97万亿",
            },
        })
        html = result.get("html", "")
        self.assertIn("w04-board", html)
        self.assertIn("w04-index-grid", html)
        self.assertIn("w04-metric-grid", html)
        self.assertIn("w04-breadth-bar", html)
        self.assertIn("w04-baseline-pill", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("&lt;b&gt;2万亿&lt;/b&gt;", html)
        self.assertIn("&lt;u&gt;3000&lt;/u&gt;", html)
        self.assertIn("&lt;svg onload=alert(1)&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>2万亿</b>", html)
        self.assertNotIn("onmouseover=", html)
        self.assertNotIn("onmouseout=", html)

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

    def test_w04_sanitizes_malformed_yesterday_baseline_turnover(self):
        result = _render_widget("market-overview.js", "W04", {
            "live_index": {},
            "yesterday_baseline": {
                "深证昨涨幅": "-3.22%",
                "深证昨成交额": "1525460900000.00万亿",
                "创业昨涨幅": "-3.69%",
                "创业昨成交额": "727291600000.00万亿",
            },
        })
        html = result.get("html", "")
        self.assertIn("1.53万亿", html, f"W04 应把误标为万亿的深证原始元值净化: {html[:900]}")
        self.assertIn("7273亿", html, f"W04 应把误标为万亿的创业原始元值净化: {html[:900]}")
        self.assertNotIn("1525460900000.00万亿", html)
        self.assertNotIn("727291600000.00万亿", html)

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

    def test_w04_uses_hot_list_limit_up_and_masks_missing_limit_down_when_iwencai_dead(self):
        result = _render_widget("market-overview.js", "W04", {
            "live_index": {},
            "market": {"涨停家数": 128, "跌停家数": 5},
            "live_breadth": {"_source": "live_index_fallback", "_total": 5211, "涨停": 0, "跌停": 0},
            "iwencai": {
                "涨停家数": 0,
                "跌停家数": 0,
                "_updated": "2026-06-10T11:32:21+08:00",
                "_freshness": {"level": "dead", "type": "iwencai", "age_seconds": 2040},
            },
            "hot_list": {"zt_count": 55, "zt_stocks": [{"code": "300001"}], "_updated": "2026-06-10T12:52:09+08:00"},
            "sentiment": {},
        })
        html = result.get("html", "")
        self.assertIn(">55</span>/<span class=\"down\">—<", html,
                      f"W04 应忽略 dead 问财和粗略 breadth，用热榜涨停并隐藏缺失跌停: {html[:900]}")
        self.assertNotIn(">128</span>/<span class=\"down\">5<", html)
        self.assertNotIn(">0</span>/<span class=\"down\">0<", html)

    def test_w04_masks_limit_counts_when_only_stale_baseline_exists(self):
        result = _render_widget("market-overview.js", "W04", {
            "live_index": {},
            "market": {"涨停家数": 73, "跌停家数": 11},
            "iwencai": {
                "_updated": "2026-06-05T15:07:01+08:00",
                "_freshness": {"level": "dead", "type": "iwencai", "age_seconds": 2040},
            },
            "sentiment": {},
        })
        html = result.get("html", "")
        self.assertIn(">—</span>/<span class=\"down\">—<", html,
                      f"W04 盘中涨跌停缺实时源时不应显示昨日基线: {html[:900]}")
        self.assertNotIn(">73</span>/<span class=\"down\">11<", html)

    def test_w04_uses_baseline_returns_when_iwencai_dead(self):
        result = _render_widget("market-overview.js", "W04", {
            "live_index": {},
            "market": {},
            "iwencai": {
                "昨日涨停收益": -0.6,
                "_updated": "2026-06-05T15:07:01+08:00",
                "_freshness": {"level": "dead", "type": "iwencai", "age_seconds": 2040},
            },
            "sentiment": {
                "昨日涨停收益": 3.1,
                "连板收益": 3.88,
                "昨日炸板收益": -0.18,
            },
        })
        html = result.get("html", "")
        self.assertIn("+3.1%", html, f"W04 应在问财 dead 时回退昨停收益基线: {html[:900]}")
        self.assertIn("+3.88%", html, f"W04 应在问财 dead 时回退连板收益基线: {html[:900]}")
        self.assertIn("-0.18%", html, f"W04 应在问财 dead 时回退炸板收益基线: {html[:900]}")

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


class W06Auction5DTest(unittest.TestCase):
    """W06 有效竞价快照主路径不应因状态灯文案崩溃"""

    def test_w06_renders_valid_snapshot_without_emoji_light_dependency(self):
        result = _render_widget("auction-5d.js", "W06", {
            "auction_snapshot": {
                "_available": True,
                "_stale": False,
                "time": "09:28",
                "竞价强势家数": 12,
                "涨跌家数": {"上涨": 3200, "下跌": 1800, "涨跌比": "1.78"},
                "指数竞价": [{"名称": "上证", "竞价涨幅": 0.23}],
                "情绪指标": {"情绪值": 58, "赚钱效应": "中性", "昨日涨停收益": 1.2},
                "高标竞价": [{"名称": "测试高标", "板数": 3, "竞价涨幅": 5.2, "异动": "抢筹"}],
                "自选池竞价": [{"名称": "测试自选", "来源": "趋势", "竞价涨幅": -1.3}],
                "板块竞价": [{"板块": "算力", "竞价涨幅": 2.4}],
                "信号灯": {
                    "综合": {"灯": "green", "label": "可观察"},
                    "涨跌": {"灯": "green", "label": "扩散"},
                    "强势": {"灯": "orange", "label": "分歧"},
                    "高标": {"灯": "red", "label": "风险"},
                },
            }
        })
        self.assertNotIn("_error", result)
        html = result["html"]
        self.assertIn("正常 涨跌:扩散", html)
        self.assertIn("关注 强势:分歧", html)
        self.assertIn("风险 高标:风险", html)
        self.assertNotIn("🟢", html)
        self.assertNotIn("🔴", html)


class W10SectorHeatTest(unittest.TestCase):
    """W10 只展示今日实时匹配板块，避免复盘数据误导"""

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
        self.assertIn("候选板块", html, f"W10 应展示新版表头: {html[:600]}")
        self.assertIn("w10-acceptance", html, f"W10 应前置板块验收摘要: {html[:800]}")
        self.assertIn("主线", html, f"W10 摘要应突出主线数量: {html[:800]}")
        self.assertIn("风险", html, f"W10 摘要应突出风险/分歧数量: {html[:800]}")
        self.assertIn("候选", html, f"W10 摘要应突出候选匹配: {html[:800]}")
        self.assertIn("隐藏复盘 1/2", html, f"W10 应标明未匹配实时数据的复盘板块被隐藏: {html[:800]}")
        self.assertIn("+3.09%", html, f"W10 应读取 sector_inflow 涨跌幅: {html[:800]}")
        self.assertIn("+76.3亿", html, f"W10 应读取 sector_inflow 净流入: {html[:800]}")
        self.assertIn("涨跌 100:9", html, f"W10 应展示涨跌家数: {html[:800]}")
        self.assertNotIn("半导体", html, f"W10 无实时匹配时不应展示复盘板块: {html[:800]}")
        self.assertNotIn("紫光国微", html, f"W10 无实时匹配时不应展示该板块候选: {html[:800]}")
        self.assertNotIn("-5.12%", html, f"W10 不应回退到自选池均值伪装板块热度: {html[:800]}")
        self.assertNotIn("池均", html, f"W10 不再使用池均回退口径: {html[:800]}")
        self.assertNotIn("待分析", html)
        self.assertNotIn("🔥", html)
        self.assertNotIn("⭐", html)

    def test_w10_empty_uses_shared_quiet_state(self):
        result = _render_widget("sector-heat.js", "W10", {"sectors": []})
        html = result.get("html", "")
        self.assertIn("ui-empty", html)
        self.assertIn("w10-empty", html)
        self.assertIn("板块状态未录入", html)

    def test_w10_hides_review_status_metrics_without_live_match(self):
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
        self.assertIn("暂无实时板块热度", html, f"W10 无实时数据时应显示空态: {html[:700]}")
        self.assertIn("已隐藏复盘回退项", html, f"W10 应解释隐藏原因: {html[:700]}")
        self.assertNotIn("+3.72%", html, f"W10 不应从复盘状态抽涨幅: {html[:700]}")
        self.assertNotIn("-39.5亿", html, f"W10 不应从复盘状态抽资金: {html[:700]}")

    def test_w10_ignores_stale_live_sectors(self):
        result = _render_widget("sector-heat.js", "W10", {
            "sectors": [
                {"板块": "电力", "类型": "风险", "涨停数": "1+", "状态": "复盘大跌"},
            ],
            "live_sectors": {
                "电力": {"涨跌幅": 1.32, "MA5方向": "向下"},
                "_updated": "2026-05-19T17:03:13+08:00",
            },
            "sector_inflow": {"data": []},
            "trend_pool": [],
            "lianban_pool": [],
            "live_quotes": {},
        })
        html = result.get("html", "")
        self.assertIn("暂无实时板块热度", html, f"W10 不应展示过期 live_sectors: {html[:700]}")
        self.assertNotIn("+1.32%", html, f"W10 不应使用旧 live_sectors 涨跌幅: {html[:700]}")


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
        self.assertIn("zt-acceptance", html, f"W21 应前置梯队验收摘要: {html[:900]}")
        self.assertIn("梯队验收", html, f"W21 摘要应有明确标题: {html[:900]}")
        self.assertIn("观察", html, f"W21 摘要应包含热榜观察数量: {html[:900]}")
        self.assertIn("问财连板", html, f"W21 应展示问财确认连板源: {html[:900]}")
        self.assertIn("3板", html, f"W21 应渲染连板阶梯: {html[:900]}")
        self.assertIn("热榜观察", html, f"W21 热榜股票只能作为观察池: {html[:900]}")
        self.assertIn("首板源未确认", html, f"W21 应提示今日首板源不可用: {html[:900]}")
        self.assertNotIn("最高板: <b>—</b>", html)
        self.assertNotIn("共2只", html, f"W21 不应把热榜 2 只计为确认涨停: {html[:900]}")
        self.assertNotIn("🤖", html)

    def test_w21_empty_uses_shared_quiet_state(self):
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
global.localStorage = { getItem: function() { return null; }, setItem: function() {} };
"""
        result = _render_widget("zt-echelon.js", "W21", {"hot_list": {"date": "2026-05-29", "stocks": [], "zt_stocks": []}}, extra_js=extra_js)
        html = result.get("html", "")
        self.assertIn("ui-empty", html)
        self.assertIn("zt-empty", html)
        self.assertIn("今日确认涨停源暂不可用", html)


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
        self.assertIn("ui-degraded", html, f"trade_entry_allowed=false W1 应使用统一降级态: {html[:200]}")

    def test_w1_missing_rule_state_uses_degraded_state(self):
        result = _render_widget("w1-check.js", "W08", _missing_rs_fixture())
        html = result.get("html", "")
        self.assertIn("规则状态不可用", html, f"W1 缺失 rule_state 应显示不可用: {html[:200]}")
        self.assertIn("ui-degraded", html, f"W1 缺失 rule_state 应使用统一降级态: {html[:200]}")

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

    def test_w1_shows_window_acceptance_command_first(self):
        fixture = {
            "rule_state": {
                "version": "g1a-v1", "tradable": True,
                "caps": {"base_total_pct": 40, "total_pct": 20},
                "windows": {"w1": {"in_session": True, "buy_allowed": True},
                            "w2": {"in_session": False, "buy_allowed": False}},
                "blocks": [], "warnings": [],
            },
            "sentiment": {"情绪值": 65, "昨日涨停收益": "3.2%", "最高板": "4板"},
            "market": {"涨停家数": 54, "炸板率": "18%"},
            "iwencai": {"涨停家数": 54, "一进二晋级率": 0.4},
            "live_index": {}, "live_quotes": {},
            "lianban_pool": [
                {"标的": "测试连板", "代码": "000001", "板块": "科技", "角色": "1进2", "窗口": "W1", "涨幅": "+4"}
            ],
            "trend_pool": [],
            "trade_entry_allowed": True,
        }
        result = _render_widget("w1-check.js", "W08", fixture)
        html = result.get("html", "")
        theme = (ROOT / "css" / "theme.css").read_text()
        self.assertIn("window-command", html, f"W08 应先展示窗口验收卡: {html[:600]}")
        self.assertIn("W1验收", html, f"W08 应有验收标题: {html[:600]}")
        self.assertIn("当前窗口", html, f"W08 应前置窗口状态: {html[:600]}")
        self.assertIn("规则状态", html, f"W08 应前置规则状态: {html[:600]}")
        self.assertIn("候选", html, f"W08 应前置候选数量: {html[:600]}")
        self.assertLess(html.index("window-command"), html.index("情绪≥60%"),
                        f"W08 验收卡应在细节信号前: {html[:900]}")
        self.assertIn(".window-command-grid", theme)


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
        self.assertIn("ui-degraded", html, f"trade_entry_allowed=false W2 应使用统一降级态: {html[:200]}")

    def test_w2_missing_rule_state_uses_degraded_state(self):
        result = _render_widget("w2-check.js", "W09", _missing_rs_fixture())
        html = result.get("html", "")
        self.assertIn("规则状态不可用", html, f"W2 缺失 rule_state 应显示不可用: {html[:200]}")
        self.assertIn("ui-degraded", html, f"W2 缺失 rule_state 应使用统一降级态: {html[:200]}")

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

    def test_w2_shows_window_acceptance_command_first(self):
        fixture = {
            "rule_state": {
                "version": "g1a-v1", "tradable": True,
                "caps": {"base_total_pct": 40, "total_pct": 20},
                "windows": {"w1": {"in_session": False, "buy_allowed": False},
                            "w2": {"in_session": True, "buy_allowed": True}},
                "blocks": [], "warnings": [],
            },
            "sentiment": {"情绪值": 65, "昨日涨停收益": "3.2%", "赚钱效应": "好"},
            "live_index": {"上涨家数": 3000, "下跌家数": 1800, "上证指数涨幅": "+0.3%"},
            "live_quotes": {
                "000002": {"最新价": 10.1, "涨幅": "+1.2%", "量比": 0.7, "MA10_60m": 10, "MA10_60m_dir": "向上"}
            },
            "lianban_pool": [],
            "trend_pool": [{"标的": "测试趋势", "代码": "000002", "板块": "科技",
                             "角色": "持仓", "窗口": "W2", "涨幅": "+1.2", "MA5": 10.0}],
            "trade_entry_allowed": True,
        }
        result = _render_widget("w2-check.js", "W09", fixture)
        html = result.get("html", "")
        theme = (ROOT / "css" / "theme.css").read_text()
        self.assertIn("window-command", html, f"W09 应先展示窗口验收卡: {html[:600]}")
        self.assertIn("W2验收", html, f"W09 应有验收标题: {html[:600]}")
        self.assertIn("当前窗口", html, f"W09 应前置窗口状态: {html[:600]}")
        self.assertIn("规则状态", html, f"W09 应前置规则状态: {html[:600]}")
        self.assertIn("候选", html, f"W09 应前置候选数量: {html[:600]}")
        self.assertLess(html.index("window-command"), html.index("趋势 W2"),
                        f"W09 验收卡应在候选明细前: {html[:900]}")
        self.assertIn(".window-command-grid", theme)

class EvidenceBoardWidgetTest(unittest.TestCase):
    """W25 renders stable S0/E/A/R references for external AI workflows"""

    def test_w25_renders_s0_evidence_alert_risk(self):
        fixture = {
            "pnl_live": {
                "total_asset": 720227.67,
                "cash": 583679.67,
                "mv": 136548,
                "pos_pct": 18.96,
                "pnl_pct": -0.51,
                "quote_status": "close_snapshot",
                "valuation_complete": True,
                "positions": [{"标的": "光讯科技", "代码": "002281", "市值": 136548, "成本": 219.49, "today_pnl_pct": 4.12}],
            },
            "trade_tickets": [{"status": "filled"}, {"status": "closed"}],
            "sentiment": {"情绪值": 59},
            "iwencai": {"涨停家数": 46, "跌停家数": 2, "_freshness": {"level": "delayed"}},
            "rule_state": {"tradable": True, "caps": {"total_pct": 40}, "blocks": []},
        }
        extra_js = (ROOT / "evidence-summary.js").read_text(encoding="utf-8")
        result = _render_widget("evidence-board.js", "W25", fixture, extra_js=extra_js)
        html = result.get("html", "")
        self.assertNotIn("_error", html)
        self.assertIn("S0", html)
        self.assertIn("E1", html)
        self.assertIn("A1", html)
        self.assertIn("R1", html)
        self.assertIn("光讯科技", html)
        self.assertIn("收盘快照", html)
        self.assertIn("evidence-dashboard-hero", html)
        self.assertIn("盘中裁决", html)
        self.assertIn("evidence-gate-row", html)
        self.assertIn("数据可信", html)
        self.assertIn("规则门禁", html)
        self.assertIn("窗口状态", html)
        self.assertIn("仓位空间", html)
        self.assertIn("票据闭环", html)
        self.assertIn("优先处理", html)
        self.assertIn("当前阶段", html)
        self.assertIn("关键风险", html)
        self.assertIn("下一步", html)
        self.assertIn('data-evidence-target="widget:W15"', html)
        self.assertIn('data-evidence-target="widget:W24"', html)
        self.assertIn('data-evidence-target="widget:W04"', html)
        self.assertIn('role="button"', html)
        self.assertIn('tabindex="0"', html)

        widget_src = (ROOT / "widgets" / "evidence-board.js").read_text(encoding="utf-8")
        self.assertIn("_bindEvidenceTraceLinks", widget_src)
        self.assertIn("_openEvidenceTarget", widget_src)
        self.assertIn("keydown", widget_src)


class ReadOnlyInsightUxTest(unittest.TestCase):
    """Dashboard keeps AI interaction outside the cockpit surface."""

    def test_dashboard_does_not_mount_chat_or_post_llm(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        chat = (ROOT / "widgets" / "llm-chat.js").read_text(encoding="utf-8")
        monitor = (ROOT / "widgets" / "llm-monitor.js").read_text(encoding="utf-8")
        registry = (ROOT / "widget-registry.js").read_text(encoding="utf-8")
        w1 = (ROOT / "widgets" / "w1-check.js").read_text(encoding="utf-8")
        pnl = (ROOT / "widgets" / "pnl-curve.js").read_text(encoding="utf-8")

        self.assertNotIn('src="widgets/llm-chat.js"', index)
        self.assertNotIn("llmChatMount", index)
        self.assertNotIn("llmPanelBtn", index)
        self.assertNotIn("fetch('/api/llm'", index)
        self.assertNotIn('fetch("/api/llm"', index)
        self.assertNotIn("fetch('/api/llm'", chat)
        self.assertNotIn('fetch("/api/llm"', chat)
        self.assertIn("function _uiEsc", index)
        self.assertIn("_uiEsc(e.text || '')", index)
        self.assertIn("_uiEsc(e.node)", index)
        self.assertIn("_uiEsc(e.ts)", index)
        self.assertIn("研判摘要", registry)
        self.assertNotIn("title:'AI盯盘'", registry)
        self.assertNotIn("打开对话", monitor)
        self.assertNotIn("_llmChat", monitor)
        self.assertIn("只读展示", monitor)
        self.assertNotIn("AI 盯盘", w1)
        self.assertIn("研判信号", w1)
        self.assertNotIn("📊", pnl)


class CoreQuietStateUxTest(unittest.TestCase):
    """Core cockpit widgets share the same empty/degraded state language."""

    def test_shared_quiet_state_css_exists(self):
        theme = (ROOT / "css" / "theme.css").read_text(encoding="utf-8")
        self.assertIn(".ui-empty{", theme)
        self.assertIn(".ui-empty-inline", theme)
        self.assertIn(".ui-empty-title", theme)
        self.assertIn(".ui-empty-detail", theme)
        self.assertIn(".ui-degraded{", theme)

    def test_core_cockpit_refinement_css_exists(self):
        theme = (ROOT / "css" / "theme.css").read_text(encoding="utf-8")
        for cls in [
            ".ticket-summary-grid",
            ".ticket-summary-pill",
            ".ticket-card",
            ".ticket-entry-grid",
            ".w15-kpi-grid",
            ".w15-kpi-value",
            ".data-table.w15-table",
        ]:
            self.assertIn(cls, theme)

    def test_secondary_widgets_use_shared_empty_states(self):
        files = [
            "today-ops.js",
            "midday-review.js",
            "lianban-pool.js",
            "trend-pool.js",
            "anchor-stocks.js",
            "auction-5d.js",
            "sentiment-dash.js",
            "position-calc.js",
            "trade-tickets.js",
        ]
        joined = "\n".join((ROOT / "widgets" / f).read_text(encoding="utf-8") for f in files)
        self.assertIn("ui-note", (ROOT / "css" / "theme.css").read_text(encoding="utf-8"))
        for phrase in [
            "今日无操作",
            "午盘数据待录入",
            "连板池数据未录入",
            "趋势池数据未录入",
            "锚定股数据未录入",
            "竞价数据不可用",
            "情绪节点数据不可用",
            "规则状态不可用",
            "加载票据",
        ]:
            self.assertIn(phrase, joined)
        self.assertNotIn("🤖 待研判", joined)
        self.assertNotIn("🟢", joined)
        self.assertNotIn("🔴", joined)
        self.assertNotIn("🟠", joined)
        self.assertNotIn("padding:var(--sp-lg);text-align:center;color:var(--text-disabled)", joined)

    def test_decision_risk_widgets_avoid_alert_emoji_states(self):
        files = [
            "climax-guard.js",
            "risk-panel.js",
        ]
        joined = "\n".join((ROOT / "widgets" / f).read_text(encoding="utf-8") for f in files)
        for phrase in [
            "规则状态不可用",
            "高潮保护触发",
            "单日熔断",
            "止损触发",
            "接近止损",
        ]:
            self.assertIn(phrase, joined)
        for noisy in ["⚠ ", "✓ ", "🔴", "🟡"]:
            self.assertNotIn(noisy, joined)

    def test_visible_status_copy_uses_quiet_text(self):
        sources = {
            "index": (ROOT / "index.html").read_text(encoding="utf-8"),
            "input": (ROOT / "widgets" / "input-panel.js").read_text(encoding="utf-8"),
            "style": (ROOT / "widgets" / "style-detect.js").read_text(encoding="utf-8"),
            "theme": (ROOT / "css" / "theme.css").read_text(encoding="utf-8"),
        }
        self.assertNotIn("✓ 已更新", sources["index"])
        self.assertNotIn("✓ 已更新", sources["input"])
        self.assertNotIn("⚠ ' + w", sources["style"])
        self.assertIn("style-detect-warning", sources["style"])
        self.assertIn(".w10-empty{padding:12px 10px", sources["theme"])
        self.assertIn(".zt-empty{padding:12px 10px", sources["index"])

    def test_data_widgets_have_stable_layout_classes(self):
        theme = (ROOT / "css" / "theme.css").read_text(encoding="utf-8")
        for cls in [
            ".timeline-shell",
            ".timeline-track",
            ".style-detect-head",
            ".style-detect-warning",
            ".style-detect-exec-block",
            ".w11-empty",
            ".w11-tip",
            ".w23-toolbar",
            ".w23-filter-bar",
            ".w23-table-wrap",
            ".data-table.w23-table",
            ".w04-board",
            ".w04-index-grid",
            ".w04-breadth-bar",
            ".w04-baseline-pill",
        ]:
            self.assertIn(cls, theme)

    def test_core_widgets_use_shared_quiet_states(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        monitor = (ROOT / "widgets" / "llm-monitor.js").read_text(encoding="utf-8")
        tickets = (ROOT / "widgets" / "trade-tickets.js").read_text(encoding="utf-8")
        positions = (ROOT / "widgets" / "positions.js").read_text(encoding="utf-8")

        for src in (index, monitor, tickets, positions):
            self.assertIn("ui-empty", src)

        self.assertIn("ui-degraded", tickets)
        self.assertNotIn("⏳", index)
        self.assertNotIn("等待外部 Agent 写入研判</div>", monitor)
        self.assertNotIn("数据不可用 — 锚点被阻断</div>", positions)
        self.assertNotIn("padding:var(--sp-sm);text-align:center;color:var(--text-disabled);font-size:var(--fs-body)", positions)


class WidgetPanelUxTest(unittest.TestCase):
    """Widget picker uses cockpit-style metadata instead of the old dev panel."""

    def test_market_evidence_shelf_is_secondary_overlay(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        theme = (ROOT / "css" / "theme.css").read_text(encoding="utf-8")
        self.assertIn('id="evidenceShelfBtn"', index)
        self.assertIn('id="evidenceShelfOverlay"', index)
        self.assertIn('id="evidenceShelfSummary"', index)
        self.assertIn('id="evidenceShelfNav"', index)
        self.assertIn("EVIDENCE_SHELF_WIDGETS", index)
        for wid in ["W10", "W12", "W13", "W21"]:
            self.assertIn("'" + wid + "'", index)
            self.assertIn("{ id: '" + wid + "'", index)
        self.assertIn('data-target="SHELF_\' + item.id + \'"', index)
        self.assertIn("document.getElementById('evidenceShelfBody')", index)
        self.assertIn("scroller.scrollTo", index)
        self.assertIn("REQUIRED_LAYOUT_WIDGETS = ['W25', 'W15', 'W24']", index)
        self.assertIn("_showEvidenceShelf", index)
        self.assertIn("_renderEvidenceShelfSummary", index)
        self.assertIn("_renderEvidenceShelfNav", index)
        self.assertIn("evidence-shelf-nav", index)
        self.assertIn("evidence-shelf-summary", index)
        self.assertIn("SHELF_", index)
        self.assertIn(".evidence-shelf-overlay", theme)
        self.assertIn(".evidence-shelf-nav", theme)
        self.assertIn(".evidence-shelf-nav-btn", theme)
        self.assertIn(".evidence-shelf-summary", theme)
        self.assertIn(".evidence-shelf-summary-grid", theme)
        self.assertIn(".evidence-shelf-grid", theme)
        self.assertIn(".evidence-shelf-card", theme)

    def test_dashboard_exposes_evidence_trace_router(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        theme = (ROOT / "css" / "theme.css").read_text(encoding="utf-8")
        self.assertIn("function _openEvidenceTarget", index)
        self.assertIn("window._openEvidenceTarget = _openEvidenceTarget", index)
        self.assertIn("target.indexOf('shelf:') === 0", index)
        self.assertIn("_showEvidenceShelf()", index)
        self.assertIn("_addWidgetToGrid(widgetId)", index)
        self.assertIn("evidence-focus-pulse", index)
        self.assertIn(".evidence-focus-pulse", theme)

    def test_widget_panel_uses_ref_priority_and_tier_pills(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("widget-panel-title", index)
        self.assertIn("VIEW MODULES", index)
        self.assertIn("item-ref", index)
        self.assertIn("item-pill-priority", index)
        self.assertIn("tierLabels", index)
        self.assertNotIn("catIcons", index)
        self.assertNotIn("🎯", index)
        self.assertNotIn("📊", index)
        self.assertNotIn("💰", index)
        self.assertNotIn("🔧", index)
        self.assertNotIn(" + w.defaultSize.w + '×' + w.defaultSize.h + ' · ' + w.id", index)

    def test_w03_default_size_matches_command_card_density(self):
        registry = (ROOT / "widget-registry.js").read_text(encoding="utf-8")
        self.assertIn("id:'W03'", registry)
        self.assertIn("defaultSize:{w:6,h:6}", registry)
        self.assertIn("'style.趋势占比'", registry)


class TransientSurfaceUxTest(unittest.TestCase):
    """Menus and overlays should not linger on a monitoring cockpit."""

    def test_default_widget_mount_does_not_depend_on_raf(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("if (contentEl) instance.mount(contentEl);", index)
        self.assertNotIn("requestAnimationFrame(function() {\n    var contentEl = document.getElementById('content_' + widgetId);", index)

    def test_menus_close_on_actions_and_escape(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        theme = (ROOT / "css" / "theme.css").read_text(encoding="utf-8")

        self.assertIn("function _closeTopbarMenus()", index)
        self.assertIn("function _closeTransientSurfaces()", index)
        self.assertIn("if (e.key === 'Escape')", index)
        self.assertIn("_closeTopbarMenus(); _addWidgetToGrid", index)
        self.assertIn("_closeTopbarMenus(); exportLayout();", index)
        self.assertIn("safeLeft", index)
        self.assertIn("safeTop", index)
        self.assertIn(".context-menu-item b", theme)
        self.assertIn('" data-category="', index)
        self.assertIn("w.category", index)


if __name__ == "__main__":
    unittest.main()
