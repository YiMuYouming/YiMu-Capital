# AI Evidence Cockpit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only `W25 态势证据屏` that turns existing dashboard data into stable `S0/E/A/R` evidence references for external CodexIDE / terminal AI workflows.

**Architecture:** Add a pure `evidence-summary.js` module that derives a normalized evidence snapshot from `DataStore.merged` plus runtime health flags. Add `widgets/evidence-board.js` to render that snapshot as a GridStack widget. Register `W25`, include it in core view, and add focused tests before implementation.

**Tech Stack:** Vanilla JavaScript, existing `YiMuWidget` base class, existing `DataStore`, GridStack registration, Python `unittest` invoking Node for frontend unit tests.

---

## File Structure

- Create `evidence-summary.js`: pure helpers and `EvidenceSummary.build(data, runtime)`; no DOM reads, no fetch, no side effects.
- Create `widgets/evidence-board.js`: `W25` widget rendering `S0/E/A/R` from `EvidenceSummary`.
- Modify `index.html`: load `evidence-summary.js` before widgets and load `widgets/evidence-board.js`.
- Modify `widget-registry.js`: register metadata for `W25`.
- Modify `css/theme.css`: shared evidence badge/card styles and responsive half-screen rules.
- Modify `tests/test_evidence_summary.py`: Node-based tests for pure summary behavior.
- Modify `tests/test_frontend_rule_state.py`: add one widget render smoke test.

## Task 1: Evidence Summary Unit Tests

**Files:**
- Create: `tests/test_evidence_summary.py`
- Test target: `evidence-summary.js`

- [ ] **Step 1: Write failing test file**

Create `tests/test_evidence_summary.py`:

```python
import json
import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_summary(data, runtime=None):
    runtime = runtime or {}
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const src = fs.readFileSync('{(ROOT / "evidence-summary.js").as_posix()}', 'utf8');
        const ctx = {{ console, window: {{}}, globalThis: {{}} }};
        vm.createContext(ctx);
        vm.runInContext(src, ctx);
        const mod = ctx.EvidenceSummary || ctx.window.EvidenceSummary || ctx.globalThis.EvidenceSummary;
        if (!mod || typeof mod.build !== 'function') {{
          console.log(JSON.stringify({{error: 'EvidenceSummary.build missing'}}));
          process.exit(0);
        }}
        const result = mod.build({json.dumps(data, ensure_ascii=False)}, {json.dumps(runtime, ensure_ascii=False)});
        console.log(JSON.stringify(result));
        """
    )
    result = subprocess.run(["node", "-e", script], cwd=str(ROOT), capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    if payload.get("error"):
        raise AssertionError(payload["error"])
    return payload


class EvidenceSummaryTest(unittest.TestCase):
    def test_builds_stable_situation_and_evidence(self):
        data = {
            "pnl_live": {
                "total_asset": 720227.67,
                "cash": 583679.67,
                "mv": 136548,
                "pos_pct": 18.96,
                "pnl_amount": -3672,
                "pnl_pct": -0.51,
                "quote_status": "close_snapshot",
                "valuation_complete": True,
                "positions": [
                    {"标的": "光讯科技", "代码": "002281", "市值": 136548, "现价": 227.58, "成本": 219.49, "today_pnl": 8188, "today_pnl_pct": 4.12, "total_pnl": 4854, "total_pnl_pct": 3.69}
                ],
            },
            "trade_tickets": [
                {"ticket_id": "T1", "status": "filled", "action_type": "clear", "name": "立讯精密"},
                {"ticket_id": "T2", "status": "closed", "action_type": "clear", "name": "立讯精密"},
            ],
            "sentiment": {"情绪值": 59},
            "iwencai": {"涨停家数": 46, "跌停家数": 2, "_freshness": {"level": "delayed"}},
            "rule_state": {"tradable": True, "caps": {"total_pct": 40}, "blocks": []},
        }
        snapshot = run_summary(data, {"healthLabel": "降级", "tradeEntryAllowed": True, "connectionStatus": "close_snapshot"})
        self.assertEqual(snapshot["situation"]["id"], "S0")
        self.assertEqual(snapshot["situation"]["health"]["label"], "降级")
        self.assertEqual(snapshot["evidence"][0]["id"], "E1")
        self.assertIn("光讯科技", snapshot["evidence"][0]["title"])
        self.assertTrue(any(item["id"] == "E2" and "票据" in item["title"] for item in snapshot["evidence"]))
        self.assertTrue(any(item["id"] == "A1" and "降级" in item["title"] for item in snapshot["alerts"]))
        self.assertTrue(any(item["id"] == "A2" and "收盘快照" in item["title"] for item in snapshot["alerts"]))

    def test_trade_block_becomes_risk(self):
        data = {
            "pnl_live": {"total_asset": 100000, "cash": 60000, "mv": 40000, "pnl_pct": -4.2, "pos_pct": 40},
            "rule_state": {
                "tradable": False,
                "blocks": [{"code": "DAY_STOP", "message": "单日熔断触发"}],
                "caps": {"total_pct": 0},
            },
            "trade_tickets": [],
            "sentiment": {"情绪值": 18},
        }
        snapshot = run_summary(data, {"healthLabel": "阻断", "tradeEntryAllowed": False, "connectionStatus": "live"})
        self.assertEqual(snapshot["situation"]["trade"]["allowed"], False)
        self.assertTrue(any(item["id"] == "R1" and item["tone"] == "danger" for item in snapshot["risks"]))
        self.assertTrue(any("单日熔断" in item["detail"] for item in snapshot["risks"]))

    def test_missing_data_does_not_crash(self):
        snapshot = run_summary({}, {})
        self.assertEqual(snapshot["situation"]["id"], "S0")
        self.assertEqual(snapshot["situation"]["pnl"]["pnl_pct_text"], "—")
        self.assertGreaterEqual(len(snapshot["alerts"]), 1)
```

- [ ] **Step 2: Verify failing state**

Run:

```bash
pytest tests/test_evidence_summary.py -q
```

Expected: FAIL with `ENOENT` for `evidence-summary.js`.

## Task 2: Pure Evidence Summary Module

**Files:**
- Create: `evidence-summary.js`
- Test: `tests/test_evidence_summary.py`

- [ ] **Step 1: Implement module skeleton and helpers**

Create `evidence-summary.js`:

```javascript
// evidence-summary.js — S0/E/A/R summary for external AI workflows
'use strict';

(function(root) {
  function num(v) {
    if (v === null || v === undefined || v === '') return null;
    var n = Number(String(v).replace(/,/g, '').replace('%', ''));
    return isNaN(n) ? null : n;
  }
  function text(v, fallback) {
    if (v === null || v === undefined || v === '') return fallback || '—';
    return String(v);
  }
  function signedPct(v) {
    var n = num(v);
    if (n === null) return '—';
    return (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
  }
  function moneyWan(v) {
    var n = num(v);
    if (n === null) return '—';
    return (n / 10000).toFixed(1) + '万';
  }
  function toneForPct(v) {
    var n = num(v);
    if (n === null || n === 0) return 'neutral';
    return n > 0 ? 'up' : 'down';
  }
  function activePositions(pnl) {
    var list = Array.isArray(pnl.positions) ? pnl.positions : [];
    return list.filter(function(p) {
      var st = String(p['状态'] || p.status || '');
      return st.indexOf('清') < 0 && st.indexOf('删') < 0;
    });
  }
  function pickCorePosition(pnl) {
    var list = activePositions(pnl);
    if (!list.length) return null;
    return list.slice().sort(function(a, b) {
      return (num(b['市值'] || b.market_value) || 0) - (num(a['市值'] || a.market_value) || 0);
    })[0];
  }
  function ticketCounts(tickets) {
    var counts = { pending: 0, executable: 0, blocked: 0, done: 0, total: 0 };
    (Array.isArray(tickets) ? tickets : []).forEach(function(t) {
      counts.total += 1;
      var st = String(t.status || '').toLowerCase();
      if (st === 'draft' || st === 'confirmed') counts.pending += 1;
      else if (st === 'executable') counts.executable += 1;
      else if (st === 'blocked' || st === 'audit_degraded') counts.blocked += 1;
      else if (st === 'filled' || st === 'closed' || st === 'closed_with_conflict' || st === 'cancelled') counts.done += 1;
    });
    return counts;
  }
```

- [ ] **Step 2: Implement `build()`**

Append in the same IIFE:

```javascript
  function normalizeRuntime(runtime) {
    runtime = runtime || {};
    return {
      healthLabel: text(runtime.healthLabel, runtime.healthCritical ? '阻断' : '—'),
      healthCritical: runtime.healthCritical === true,
      healthConfirmed: runtime.healthConfirmed === true,
      tradeEntryAllowed: runtime.tradeEntryAllowed !== false,
      connectionStatus: text(runtime.connectionStatus, '—'),
      quoteHealthStatus: runtime.quoteHealthStatus || '',
      now: runtime.now || new Date().toISOString()
    };
  }

  function build(data, runtime) {
    data = data || {};
    var rt = normalizeRuntime(runtime);
    var pnl = data.pnl_live || {};
    var rule = data.rule_state || {};
    var sentiment = data.sentiment || {};
    var iw = data.iwencai || {};
    var tickets = Array.isArray(data.trade_tickets) ? data.trade_tickets : [];
    var core = pickCorePosition(pnl);
    var counts = ticketCounts(tickets);
    var quoteStatus = pnl.quote_status || rt.quoteHealthStatus || rt.connectionStatus;
    var valuationComplete = pnl.valuation_complete !== false;
    var tradeAllowed = rt.tradeEntryAllowed !== false && rule.tradable !== false;

    var positionPctText = pnl.pos_pct == null
      ? (num(pnl.mv) !== null && num(pnl.total_asset) ? (num(pnl.mv) / num(pnl.total_asset) * 100).toFixed(1) + '%' : '—')
      : num(pnl.pos_pct).toFixed(1) + '%';

    var situation = {
      id: 'S0',
      title: '当前总态势',
      health: { label: rt.healthLabel, critical: rt.healthCritical, confirmed: rt.healthConfirmed },
      trade: { allowed: tradeAllowed },
      connection: { status: quoteStatus },
      sentiment: { value: num(sentiment['情绪值']), text: sentiment['情绪值'] == null ? '—' : Math.round(num(sentiment['情绪值'])) + '%' },
      pnl: {
        total_asset_text: moneyWan(pnl.total_asset),
        cash_text: moneyWan(pnl.cash),
        position_pct_text: positionPctText,
        pnl_pct_text: signedPct(pnl.pnl_pct),
        pnl_amount_text: moneyWan(pnl.pnl_amount)
      }
    };

    var evidence = [];
    if (core) {
      var corePct = core.today_pnl_pct != null ? core.today_pnl_pct : core.total_pnl_pct;
      evidence.push({
        id: 'E1',
        title: text(core['标的'] || core.name, '核心持仓'),
        value: signedPct(corePct),
        detail: text(core['代码'] || core.code, '') + ' 市值 ' + moneyWan(core['市值'] || core.market_value) + ' 成本 ' + text(core['成本'] || core['成本价'], '—'),
        source: 'W15',
        tone: toneForPct(corePct)
      });
    } else {
      evidence.push({ id: 'E1', title: '当前空仓或持仓不可用', value: '—', detail: '未从 pnl_live.positions 读到活动持仓', source: 'W15', tone: 'neutral' });
    }
    evidence.push({ id: 'E2', title: '交易票据闭环', value: counts.done + '/' + counts.total, detail: '待确认 ' + counts.pending + '，可执行 ' + counts.executable + '，阻断 ' + counts.blocked, source: 'W24', tone: counts.blocked > 0 ? 'warn' : 'neutral' });
    evidence.push({ id: 'E3', title: '市场情绪', value: situation.sentiment.text, detail: '涨停 ' + text(iw['涨停家数'], '—') + '，跌停 ' + text(iw['跌停家数'], '—'), source: 'W04/W05', tone: num(sentiment['情绪值']) < 20 ? 'danger' : num(sentiment['情绪值']) < 40 ? 'warn' : 'neutral' });
    evidence.push({ id: 'E4', title: '账户收益', value: situation.pnl.pnl_pct_text, detail: '总资产 ' + situation.pnl.total_asset_text + '，可用 ' + situation.pnl.cash_text + '，仓位 ' + situation.pnl.position_pct_text, source: 'W22', tone: toneForPct(pnl.pnl_pct) });

    var alerts = [];
    if (rt.healthLabel === '降级' || rt.healthCritical) alerts.push({ id: 'A1', title: '系统健康' + rt.healthLabel, detail: '健康状态来自 /api/health 顶栏语义', source: 'topbar', tone: rt.healthCritical ? 'danger' : 'warn' });
    if (quoteStatus === 'close_snapshot') alerts.push({ id: 'A' + (alerts.length + 1), title: '收盘快照', detail: '行情为非实时快照，可用于复盘，不等同于行情 dead', source: 'W15/W22', tone: 'neutral' });
    if (!valuationComplete) alerts.push({ id: 'A' + (alerts.length + 1), title: '估值不完整', detail: text(pnl.block_reason, 'valuation_complete=false'), source: 'pnl_live', tone: 'warn' });
    var iwFresh = iw._freshness || {};
    if (iwFresh.level === 'stale' || iwFresh.level === 'dead' || iwFresh.level === 'delayed') alerts.push({ id: 'A' + (alerts.length + 1), title: 'iwencai 数据' + iwFresh.level, detail: '情绪源新鲜度降级', source: 'W04', tone: iwFresh.level === 'dead' ? 'danger' : 'warn' });
    if (!alerts.length) alerts.push({ id: 'A1', title: '暂无关键异常', detail: '未发现需要外部 AI 对话优先处理的异常', source: 'EvidenceSummary', tone: 'neutral' });

    var risks = [];
    var blocks = Array.isArray(rule.blocks) ? rule.blocks : [];
    if (!tradeAllowed || blocks.length) {
      risks.push({ id: 'R1', title: '交易阻断', detail: blocks.length ? text(blocks[0].message || blocks[0].code, '规则阻断') : '交易入口被健康门禁关闭', source: 'rule_state/api_health', tone: 'danger' });
    } else {
      risks.push({ id: 'R1', title: '交易入口允许', detail: '未发现 critical 阻断', source: 'rule_state/api_health', tone: 'neutral' });
    }
    var cap = rule.caps && rule.caps.total_pct;
    risks.push({ id: 'R2', title: '仓位上限', detail: cap == null ? '仓位上限不可用' : 'total_pct=' + cap + '%', source: 'rule_state', tone: cap === 0 ? 'danger' : 'neutral' });

    return { generated_at: rt.now, situation: situation, evidence: evidence, alerts: alerts, risks: risks };
  }

  var api = { build: build };
  root.EvidenceSummary = api;
  if (root.window) root.window.EvidenceSummary = api;
  if (typeof globalThis !== 'undefined') globalThis.EvidenceSummary = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
```

- [ ] **Step 3: Run tests**

Run:

```bash
pytest tests/test_evidence_summary.py -q
```

Expected: PASS.

## Task 3: W25 Widget Render Test

**Files:**
- Modify: `tests/test_frontend_rule_state.py`
- Test target: `widgets/evidence-board.js`

- [ ] **Step 1: Add W25 smoke test**

Append to `tests/test_frontend_rule_state.py`:

```python
class EvidenceBoardWidgetTest(unittest.TestCase):
    """W25 renders stable references for external AI workflows"""

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
        self.assertIn("S0", html)
        self.assertIn("E1", html)
        self.assertIn("A1", html)
        self.assertIn("R1", html)
        self.assertIn("光讯科技", html)
        self.assertIn("收盘快照", html)
```

- [ ] **Step 2: Verify failing state**

Run:

```bash
pytest tests/test_frontend_rule_state.py::EvidenceBoardWidgetTest -q
```

Expected: FAIL with `file not found: evidence-board.js`.

## Task 4: W25 Widget Implementation

**Files:**
- Create: `widgets/evidence-board.js`
- Modify: `css/theme.css`
- Test: `tests/test_frontend_rule_state.py::EvidenceBoardWidgetTest`

- [ ] **Step 1: Add W25 styles**

Add to `css/theme.css`:

```css
/* ===== Evidence Board (W25) ===== */
.evidence-board{display:flex;flex-direction:column;gap:8px;height:100%;min-width:0}
.evidence-situation{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:6px}
.evidence-kpi{background:var(--bg-base);border:1px solid var(--border-light);border-radius:var(--radius-md);padding:7px 8px;min-width:0}
.evidence-kpi-label{display:flex;align-items:center;gap:4px;font-size:var(--fs-label);color:var(--text-disabled);white-space:nowrap}
.evidence-kpi-value{font-family:var(--font-mono);font-size:15px;font-weight:800;line-height:1.2;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.evidence-section-grid{display:grid;grid-template-columns:1.35fr 1fr 1fr;gap:8px;min-height:0;flex:1}
.evidence-section{min-width:0;overflow:hidden}
.evidence-section-title{display:flex;align-items:center;justify-content:space-between;margin-bottom:5px;font-size:var(--fs-label);font-weight:700;color:var(--text-secondary);text-transform:uppercase;letter-spacing:var(--ls-label)}
.evidence-card{border:1px solid var(--border-light);border-radius:var(--radius-md);background:var(--bg-card);padding:7px 8px;margin-bottom:6px;min-width:0}
.evidence-card-title{display:flex;align-items:center;gap:6px;font-size:12px;font-weight:700;color:var(--text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.evidence-card-value{font-family:var(--font-mono);font-size:15px;font-weight:800;margin-top:3px}
.evidence-card-detail{font-size:11px;color:var(--text-secondary);line-height:1.35;margin-top:3px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.evidence-ref{display:inline-flex;align-items:center;justify-content:center;min-width:24px;padding:1px 5px;border-radius:4px;background:var(--info-bg);color:var(--info);font-family:var(--font-mono);font-size:10px;font-weight:800;line-height:16px;flex:0 0 auto}
.evidence-source{font-size:9px;color:var(--text-disabled);font-family:var(--font-mono);margin-left:auto}
.evidence-tone-up .evidence-card-value{color:var(--up)}
.evidence-tone-down .evidence-card-value{color:var(--down)}
.evidence-tone-warn{border-color:rgba(217,119,6,.35);background:var(--warn-bg)}
.evidence-tone-danger{border-color:rgba(220,38,38,.35);background:var(--danger-bg)}
.evidence-tone-danger .evidence-ref{background:var(--danger-bg);color:var(--danger)}
.evidence-tone-warn .evidence-ref{background:var(--warn-bg);color:var(--warn)}
@media (max-width:900px){.evidence-situation{grid-template-columns:repeat(2,minmax(0,1fr))}.evidence-section-grid{grid-template-columns:1fr}}
```

- [ ] **Step 2: Create widget file**

Create `widgets/evidence-board.js`:

```javascript
// widgets/evidence-board.js — W25 态势证据屏
'use strict';

function _evEsc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function _evToneClass(tone) {
  if (tone === 'up') return ' evidence-tone-up';
  if (tone === 'down') return ' evidence-tone-down';
  if (tone === 'warn') return ' evidence-tone-warn';
  if (tone === 'danger') return ' evidence-tone-danger';
  return '';
}

class EvidenceBoardWidget extends YiMuWidget {
  _runtime() {
    return {
      healthLabel: (typeof document !== 'undefined' && document.getElementById('healthLabel')) ? document.getElementById('healthLabel').textContent : '',
      healthCritical: typeof window !== 'undefined' && window._healthCritical === true,
      healthConfirmed: typeof window !== 'undefined' && window._healthConfirmed === true,
      tradeEntryAllowed: !(typeof window !== 'undefined' && window._tradeEntryAllowed === false),
      connectionStatus: (typeof DataStore !== 'undefined' && DataStore.getConnectionStatus) ? DataStore.getConnectionStatus() : '',
      quoteHealthStatus: typeof window !== 'undefined' ? window._quoteHealthStatus : ''
    };
  }

  _card(item) {
    return '<div class="evidence-card' + _evToneClass(item.tone) + '" data-evidence-id="' + _evEsc(item.id) + '">' +
      '<div class="evidence-card-title"><span class="evidence-ref">' + _evEsc(item.id) + '</span><span>' + _evEsc(item.title) + '</span><span class="evidence-source">' + _evEsc(item.source || '') + '</span></div>' +
      '<div class="evidence-card-value">' + _evEsc(item.value || '') + '</div>' +
      '<div class="evidence-card-detail">' + _evEsc(item.detail || '') + '</div>' +
    '</div>';
  }

  _section(title, items) {
    var html = '<div class="evidence-section"><div class="evidence-section-title"><span>' + _evEsc(title) + '</span><span>' + items.length + '</span></div>';
    items.forEach(function(item) { html += this._card(item); }, this);
    return html + '</div>';
  }

  render(data) {
    var body = this.getBody();
    if (!body) return;
    if (typeof EvidenceSummary === 'undefined' || !EvidenceSummary.build) {
      body.innerHTML = '<div class="widget-error">EvidenceSummary 不可用</div>';
      return;
    }
    var snapshot = EvidenceSummary.build(data || {}, this._runtime());
    var s = snapshot.situation || {};
    var pnl = s.pnl || {};
    var health = s.health || {};
    var trade = s.trade || {};
    var connection = s.connection || {};
    var sentiment = s.sentiment || {};
    var pnlCls = String(pnl.pnl_pct_text || '').charAt(0) === '+' ? 'up' : String(pnl.pnl_pct_text || '').charAt(0) === '-' ? 'down' : '';

    body.innerHTML = '<div class="evidence-board">' +
      '<div class="evidence-situation">' +
        '<div class="evidence-kpi"><div class="evidence-kpi-label"><span class="evidence-ref">S0</span>健康</div><div class="evidence-kpi-value">' + _evEsc(health.label || '—') + '</div></div>' +
        '<div class="evidence-kpi"><div class="evidence-kpi-label">连接</div><div class="evidence-kpi-value">' + _evEsc(connection.status || '—') + '</div></div>' +
        '<div class="evidence-kpi"><div class="evidence-kpi-label">情绪</div><div class="evidence-kpi-value">' + _evEsc(sentiment.text || '—') + '</div></div>' +
        '<div class="evidence-kpi"><div class="evidence-kpi-label">盈亏</div><div class="evidence-kpi-value ' + pnlCls + '">' + _evEsc(pnl.pnl_pct_text || '—') + '</div></div>' +
        '<div class="evidence-kpi"><div class="evidence-kpi-label">仓位</div><div class="evidence-kpi-value">' + _evEsc(pnl.position_pct_text || '—') + '</div></div>' +
        '<div class="evidence-kpi"><div class="evidence-kpi-label">交易</div><div class="evidence-kpi-value ' + (trade.allowed ? '' : 'danger') + '">' + (trade.allowed ? '允许' : '阻断') + '</div></div>' +
      '</div>' +
      '<div class="evidence-section-grid">' +
        this._section('Evidence', snapshot.evidence || []) +
        this._section('Alerts', snapshot.alerts || []) +
        this._section('Risks', snapshot.risks || []) +
      '</div>' +
    '</div>';
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W25', EvidenceBoardWidget);
```

- [ ] **Step 3: Verify W25 test**

Run:

```bash
pytest tests/test_frontend_rule_state.py::EvidenceBoardWidgetTest -q
```

Expected: PASS.

## Task 5: Register and Load W25

**Files:**
- Modify: `index.html`
- Modify: `widget-registry.js`

- [ ] **Step 1: Load scripts in `index.html`**

Add after `widget-registry.js`:

```html
<script src="evidence-summary.js?v=20260606-evidence"></script>
```

Add near widget scripts:

```html
<script src="widgets/evidence-board.js?v=20260606-evidence"></script>
```

- [ ] **Step 2: Register metadata**

In `widget-registry.js`, append to `widgets`:

```javascript
{ id:'W25', type:'evidence-board', title:'态势证据屏', category:'decision', tier:'tick', defaultSize:{w:12,h:5}, dataPaths:['pnl_live','trade_tickets','sentiment','iwencai','rule_state','live_index'], priority:'P0' },
```

- [ ] **Step 3: Include in core mode**

In `index.html`, update:

```javascript
var CORE_IDS = ['W25','W04','W07','W08','W09','W14','W24','W15','W22'];
```

Only force it into `REQUIRED_LAYOUT_WIDGETS` if the user wants W25 always present:

```javascript
var REQUIRED_LAYOUT_WIDGETS = ['W25', 'W24'];
```

- [ ] **Step 4: Syntax checks**

Run:

```bash
node --check evidence-summary.js
node --check widgets/evidence-board.js
node --check widget-registry.js
```

Expected: all exit 0.

## Task 6: Place W25 at Top When Added

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Use explicit GridStack position for W25**

In `_addWidgetToGrid(widgetId)`, replace the direct `grid.addWidget` call:

```javascript
var gsItem = grid.addWidget({ w: meta.defaultSize.w, h: meta.defaultSize.h, id: widgetId });
```

with:

```javascript
var addConfig = { w: meta.defaultSize.w, h: meta.defaultSize.h, id: widgetId };
if (widgetId === 'W25') {
  addConfig.x = 0;
  addConfig.y = 0;
}
var gsItem = grid.addWidget(addConfig);
```

- [ ] **Step 2: Manual verify layout behavior**

Open `http://localhost:18088`, add W25 from component panel. Expected: W25 appears at the top when possible and does not delete existing widgets.

## Task 7: Core Component Evidence Markers

**Files:**
- Modify: `css/theme.css`
- Modify: `widgets/positions.js`
- Modify: `widgets/trade-tickets.js`
- Modify: `widgets/market-overview.js`
- Modify: `widgets/pnl-curve.js`

- [ ] **Step 1: Add inline marker style**

Add to `css/theme.css`:

```css
.evidence-inline-ref{display:inline-flex;align-items:center;justify-content:center;min-width:22px;padding:0 5px;margin-right:4px;border-radius:4px;background:var(--info-bg);color:var(--info);font-family:var(--font-mono);font-size:10px;font-weight:800;line-height:16px;vertical-align:middle}
```

- [ ] **Step 2: Mark W15 as E1**

In `widgets/positions.js`, change the active position heading to:

```javascript
html += '<div style="font-size:var(--fs-body);font-weight:600;margin-bottom:var(--sp-xs)"><span class="evidence-inline-ref">E1</span>持仓 <span style="font-weight:400;color:var(--text-disabled)">（由成交流水驱动）</span></div>';
```

- [ ] **Step 3: Mark W24 as E2**

In `widgets/trade-tickets.js`, add `<span class="evidence-inline-ref">E2</span>` to the top summary title rendered by `_renderTicketBody`. The visible heading should read `E2 交易票据` or `E2 票据闭环`.

- [ ] **Step 4: Mark W04 as E3**

In `widgets/market-overview.js`, add `<span class="evidence-inline-ref">E3</span>` before the realtime sentiment row label or first KPI group.

- [ ] **Step 5: Mark W22 as E4**

In `widgets/pnl-curve.js`, change the first KPI label in `_buildLayout()` to:

```html
<div class="pnl-kpi-lbl"><span class="evidence-inline-ref">E4</span>当前资产</div>
```

- [ ] **Step 6: Run regression tests**

Run:

```bash
pytest tests/test_frontend_rule_state.py -q
```

Expected: PASS.

## Task 8: Documentation

**Files:**
- Modify: `README.md`
- Create: `docs/ops/2026-06-06-ai-evidence-cockpit-runbook.md`

- [ ] **Step 1: Add README section**

Add:

```markdown
## AI 协同作战屏

`W25 态势证据屏` 是只读组件，用于 CodexIDE / 终端 / 洋米会话中的事实引用。编号语义：

- `S0`：当前总态势
- `E1-E9`：关键证据
- `A1-A9`：异常/注意项
- `R1-R9`：风险/规则状态

AI 交互不在仪表板内完成；仪表板负责半屏常亮、快速扫读和证据对齐。
```

- [ ] **Step 2: Add runbook**

Create `docs/ops/2026-06-06-ai-evidence-cockpit-runbook.md`:

```markdown
# AI Evidence Cockpit Runbook

## 使用方式

左侧打开 `http://localhost:8088` 或只读预览 `http://localhost:18088`，右侧使用 CodexIDE / 终端 / 洋米对话。对话中引用 `W25` 的稳定编号，例如：

- “看 `S0`，现在是否可交易？”
- “看 `E1` 和 `R2`，判断核心持仓是否继续观察。”
- “看 `A1/A2`，区分数据降级和收盘快照。”

## 边界

- `W25` 只读，不发起交易写入。
- 手工录入仍使用现有 W16/W24/W15 降级路径。
- `S/E/A/R` 编号是沟通协议，不代表交易建议本身。

## 故障排查

- W25 显示 `EvidenceSummary 不可用`：检查 `index.html` 是否在 `widgets/evidence-board.js` 前加载 `evidence-summary.js`。
- W25 空白：打开浏览器 console，检查 `widgets/evidence-board.js` 是否加载失败。
- 编号和原组件不一致：先以 `W25` 为外部 AI 对话引用源，再检查对应 W15/W24/W04/W22 的 inline marker。
```

## Task 9: Final Verification

**Files:**
- No new files.

- [ ] **Step 1: Run automated checks**

Run:

```bash
pytest tests/test_evidence_summary.py tests/test_frontend_rule_state.py -q
node --check evidence-summary.js
node --check widgets/evidence-board.js
```

Expected: all pass.

- [ ] **Step 2: Browser verify desktop and half-screen**

Open `http://localhost:18088`. Expected:

- Topbar loads.
- W25 appears or can be added from component panel.
- W25 shows `S0`, `E1`, `E2`, `E3`, `E4`, `A`, and `R` sections.
- No POST requests are made by W25.
- Half-screen width has no text overlap.
- `close_snapshot` is shown as non-real-time snapshot, not critical dead.

## Self-Review Checklist

- Spec coverage: implements the no-chat/no-DOM-read constraint through pure summary plus read-only W25.
- Placeholder scan: no unfinished placeholder markers and no missing verification command.
- Type consistency: public API is consistently `EvidenceSummary.build(data, runtime)`.
- Risk: W25 runtime health reads existing globals. If globals are absent, it degrades to `—` and does not crash.

## Execution Options

After this plan is approved:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints.
