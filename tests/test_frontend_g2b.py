"""test_frontend_g2b.py — DataStore + 组件生命周期 (Gate 2B R3)

TZ=Asia/Shanghai，真实 DataStore 函数，不重写 merge。
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PREAMBLE = r"""
if (typeof document === 'undefined') {
  global.document = (function() {
    var _elMap = {};
    function makeEl(id) {
      return {
        id: id, innerHTML: '', style: { display: '' }, getAttribute: function() { return null; },
        setAttribute: function() {}, querySelector: function(sel) {
          if (sel && sel.charAt(0) === '#' && _elMap[sel.slice(1)]) return _elMap[sel.slice(1)];
          return null;
        },
        querySelectorAll: function() { return []; },
        addEventListener: function() {}, removeEventListener: function() {},
        closest: function() { return null; }, classList: { contains: function() { return false; } }
      };
    }
    return {
      createElement: function(tag) { return makeEl(''); },
      querySelector: function(sel) { return null; },
    };
  })();
}
if (typeof localStorage === 'undefined') {
  global.localStorage = { _store: {}, getItem: function(k) { return this._store[k] || null; },
    setItem: function(k, v) { this._store[k] = String(v); },
    removeItem: function(k) { delete this._store[k]; } };
}
if (typeof EventSource === 'undefined') {
  global.EventSource = function(url) { this.readyState = 0; this.url = url; };
  EventSource.CONNECTING = 0; EventSource.OPEN = 1; EventSource.CLOSED = 2;
}
global._mockFetchResponses = {};
global.fetch = function(url) {
  var u = typeof url === 'string' ? url : (url.url || '');
  for (var key in global._mockFetchResponses) {
    if (u.indexOf(key) >= 0) {
      var resp = global._mockFetchResponses[key];
      return Promise.resolve({ ok: true, json: function() { return Promise.resolve(resp); } });
    }
  }
  return Promise.resolve({ ok: false, json: function() { return Promise.resolve(null); } });
};
if (typeof YiMuWidget === 'undefined') {
  global.YiMuWidget = function() {};
  YiMuWidget.prototype.getBody = function() { return document.createElement('div'); };
  YiMuWidget.prototype.getHeader = function() { return document.createElement('div'); };
  YiMuWidget.prototype.updateTimestamp = function() {};
  YiMuWidget.prototype.refresh = function() {};
  YiMuWidget.prototype._on = function(el, event, fn) {
    if (!el) return;
    el.addEventListener(event, fn);
    if (!this._domListeners) this._domListeners = [];
    this._domListeners.push({ el: el, event: event, fn: fn });
  };
  YiMuWidget.prototype.unmount = function() {
    if (this._domListeners) {
      this._domListeners.forEach(function(d) {
        if (d.el && d.event && d.fn) d.el.removeEventListener(d.event, d.fn);
      });
      this._domListeners = [];
    }
  };
}
global.WidgetRegistry = {
  _map: {}, register: function(id, cls) { this._map[id] = cls; },
  getClass: function(id) { return this._map[id]; },
  getMeta: function() { return { tier: 'manual', dataPaths: [] }; }
};
global.STORAGE_KEYS = { inputs: 'dash_inputs', panelOpen: 'dash_panel_open', layout: 'dash_layout_v2' };
"""

BASE_MOCKS = r"""
global._mockFetchResponses['/api/baseline'] = {
  meta: {}, market: {}, sentiment: {}, lianban_pool: [],
  trend_pool: [], positions: [], sectors: [], risk: {}, style: { '总分': 85 }
};
global._mockFetchResponses['/api/live/quotes'] = {
  live_index: {}, live_quotes: {}, iwencai: {}, _freshness: { level: 'live' }
};
global._mockFetchResponses['/api/pnl/summary'] = { total_asset: 100000 };
var _now = new Date();
var bjToday = _now.getFullYear() + '-' +
  String(_now.getMonth() + 1).padStart(2, '0') + '-' +
  String(_now.getDate()).padStart(2, '0');
var _yest = new Date(Date.now() - 86400000);
var bjYest = _yest.getFullYear() + '-' +
  String(_yest.getMonth() + 1).padStart(2, '0') + '-' +
  String(_yest.getDate()).padStart(2, '0');
function nodeRecent(label) {
  var t = new Date(Date.now() - 60000); // 1 min ago
  return { node: label, '情绪值': 65, time: t.toISOString() };
}
function nodeOld(label) {
  var t = new Date(Date.now() - 7200000); // 2 hours ago
  return { node: label, '情绪值': 45, time: t.toISOString() };
}
"""


def _run_node(script, files=None, cwd=None):
    if files is None:
        files = []
    full_script = PREAMBLE + "\n"
    for fpath in files:
        with open(ROOT / fpath, "r", encoding="utf-8") as ff:
            full_script += ff.read() + "\n"
    full_script += "\n" + script

    env = os.environ.copy()
    env["TZ"] = "Asia/Shanghai"
    result = subprocess.run(
        ["node", "--no-warnings", "-e", full_script],
        capture_output=True, text=True, timeout=10, env=env,
        cwd=str(ROOT) if cwd is None else cwd,
    )
    if result.returncode != 0:
        return {"_error": result.stderr.strip()[:600]}
    try:
        return json.loads(result.stdout.strip().split("\n")[-1])
    except json.JSONDecodeError:
        return {"_error": result.stdout.strip()[:400]}


# ── DataStore 真实函数测试 (TZ=Asia/Shanghai) ──

class DataStoreStaleTest(unittest.TestCase):

    def test_auction_yesterday_is_stale(self):
        script = BASE_MOCKS + r"""
global._mockFetchResponses['auction_snapshot.json'] = {
  fetched: bjYest + 'T09:28:00+08:00',
  '指数竞价': [], '涨跌家数': {}, '高标竞价': [], '自选池竞价': [], '信号灯': {}
};
global._mockFetchResponses['sentiment_auto.json'] = {};
global._mockFetchResponses['sentiment_auto.json'][bjToday] = [{ node: '10:00', '情绪值': 65 }];

DataStore.fetchAll().then(function() {
  var as = (DataStore.merged || {}).auction_snapshot || {};
  console.log(JSON.stringify({ available: as._available, stale: as._stale }));
}).catch(function(e) { console.log(JSON.stringify({ _error: String(e) })); });
"""
        result = _run_node(script, files=["store.js"])
        self.assertTrue(result.get("available"), f"result={result}")
        self.assertTrue(result.get("stale"), "昨日快照应 stale=true")

    def test_auction_today_is_not_stale(self):
        script = BASE_MOCKS + r"""
global._mockFetchResponses['auction_snapshot.json'] = {
  fetched: bjToday + 'T09:28:00+08:00',
  '指数竞价': [], '涨跌家数': {}, '高标竞价': [], '自选池竞价': [], '信号灯': {}
};
global._mockFetchResponses['sentiment_auto.json'] = {};
global._mockFetchResponses['sentiment_auto.json'][bjToday] = [{ node: '10:00', '情绪值': 65 }];

DataStore.fetchAll().then(function() {
  var as = (DataStore.merged || {}).auction_snapshot || {};
  console.log(JSON.stringify({ available: as._available, stale: as._stale }));
}).catch(function(e) { console.log(JSON.stringify({ _error: String(e) })); });
"""
        result = _run_node(script, files=["store.js"])
        self.assertTrue(result.get("available"), f"result={result}")
        self.assertFalse(result.get("stale"), "当天快照应 stale=false")

    def test_sentiment_stale_with_past_nodes_only(self):
        script = BASE_MOCKS + r"""
global._mockFetchResponses['auction_snapshot.json'] = {
  fetched: bjToday + 'T09:28:00+08:00',
  '指数竞价': [], '涨跌家数': {}, '高标竞价': [], '自选池竞价': [], '信号灯': {}
};
global._mockFetchResponses['sentiment_auto.json'] = {};
global._mockFetchResponses['sentiment_auto.json'][bjYest] = [{ node: '14:00', '情绪值': 45 }];

DataStore.fetchAll().then(function() {
  var sn = (DataStore.merged || {}).sentiment_nodes || {};
  console.log(JSON.stringify({ available: sn._available, stale: sn._stale,
    latest: sn._latest_date || '', today: bjToday }));
}).catch(function(e) { console.log(JSON.stringify({ _error: String(e) })); });
"""
        result = _run_node(script, files=["store.js"])
        self.assertTrue(result.get("available"), f"result={result}")
        self.assertTrue(result.get("stale"), f"只有前日节点应 stale=true: {result}")

    def test_sentiment_fresh_with_today_nodes(self):
        script = BASE_MOCKS + r"""
global._mockFetchResponses['auction_snapshot.json'] = {
  fetched: bjToday + 'T09:28:00+08:00',
  '指数竞价': [], '涨跌家数': {}, '高标竞价': [], '自选池竞价': [], '信号灯': {}
};
global._mockFetchResponses['sentiment_auto.json'] = {};
global._mockFetchResponses['sentiment_auto.json'][bjToday] = [nodeRecent('早盘')];

DataStore.fetchAll().then(function() {
  var sn = (DataStore.merged || {}).sentiment_nodes || {};
  console.log(JSON.stringify({ available: sn._available, stale: sn._stale,
    latest: sn._latest_date || '', today: bjToday }));
}).catch(function(e) { console.log(JSON.stringify({ _error: String(e) })); });
"""
        result = _run_node(script, files=["store.js"])
        self.assertTrue(result.get("available"), f"result={result}")
        self.assertFalse(result.get("stale"), f"当天节点应 stale=false: {result}")

    def test_today_recent_node_not_stale(self):
        """当天近期节点（1分钟内）stale=false"""
        script = BASE_MOCKS + r"""
global._mockFetchResponses['auction_snapshot.json'] = {
  fetched: bjToday + 'T09:28:00+08:00',
  '指数竞价': [], '涨跌家数': {}, '高标竞价': [], '自选池竞价': [], '信号灯': {}
};
global._mockFetchResponses['sentiment_auto.json'] = {};
global._mockFetchResponses['sentiment_auto.json'][bjToday] = [nodeRecent('14:30')];

DataStore.fetchAll().then(function() {
  var sn = (DataStore.merged || {}).sentiment_nodes || {};
  console.log(JSON.stringify({ available: sn._available, stale: sn._stale,
    latest: sn._latest_date || '', today: bjToday }));
}).catch(function(e) { console.log(JSON.stringify({ _error: String(e) })); });
"""
        result = _run_node(script, files=["store.js"])
        self.assertTrue(result.get("available"), f"result={result}")
        self.assertFalse(result.get("stale"), f"近期节点应 stale=false: {result}")

    def test_today_old_node_is_stale(self):
        """当天旧节点（2小时前）超过30min窗口应 stale=true"""
        script = BASE_MOCKS + r"""
global._mockFetchResponses['auction_snapshot.json'] = {
  fetched: bjToday + 'T09:28:00+08:00',
  '指数竞价': [], '涨跌家数': {}, '高标竞价': [], '自选池竞价': [], '信号灯': {}
};
global._mockFetchResponses['sentiment_auto.json'] = {};
global._mockFetchResponses['sentiment_auto.json'][bjToday] = [nodeOld('09:25')];

DataStore.fetchAll().then(function() {
  var sn = (DataStore.merged || {}).sentiment_nodes || {};
  console.log(JSON.stringify({ available: sn._available, stale: sn._stale,
    latest: sn._latest_date || '', today: bjToday }));
}).catch(function(e) { console.log(JSON.stringify({ _error: String(e) })); });
"""
        result = _run_node(script, files=["store.js"])
        self.assertTrue(result.get("available"), f"result={result}")
        self.assertTrue(result.get("stale"), f"超时节点应 stale=true: {result}")

    def test_reload_old_content_remains_stale(self):
        """文件周期重读旧内容后仍 stale=true（不以 _loaded 时间刷新）"""
        script = BASE_MOCKS + r"""
global._mockFetchResponses['auction_snapshot.json'] = {
  fetched: bjToday + 'T09:28:00+08:00',
  '指数竞价': [], '涨跌家数': {}, '高标竞价': [], '自选池竞价': [], '信号灯': {}
};
global._mockFetchResponses['sentiment_auto.json'] = {};
global._mockFetchResponses['sentiment_auto.json'][bjYest] = [{ node: '14:00', '情绪值': 45 }];

DataStore.fetchAll().then(function() {
  var sn = (DataStore.merged || {}).sentiment_nodes || {};
  var stale1 = sn._stale;
  var latest1 = sn._latest_date || '';
  // Simulate reload: merge again (same data, different merge time)
  DataStore.merge();
  var sn2 = (DataStore.merged || {}).sentiment_nodes || {};
  var stale2 = sn2._stale;
  console.log(JSON.stringify({
    staleAfterFirst: stale1,
    staleAfterSecond: stale2,
    latest: latest1,
    today: bjToday
  }));
}).catch(function(e) { console.log(JSON.stringify({ _error: String(e) })); });
"""
        result = _run_node(script, files=["store.js"])
        self.assertTrue(result.get("staleAfterFirst"), f"首次应为 stale: {result}")
        self.assertTrue(result.get("staleAfterSecond"),
                        f"二次 merge 仍应 stale: {result}")


class DataStoreRefreshTest(unittest.TestCase):

    def test_dead_quote_freshness_not_reported_as_live_connection(self):
        """行情接口可达但 _freshness=dead 时，连接状态不能显示为 live"""
        script = BASE_MOCKS + r"""
global._mockFetchResponses['/api/live/quotes'] = {
  live_index: {}, live_quotes: {}, iwencai: {},
  _freshness: { level: 'dead', type: 'live_quote', age_seconds: 18000 }
};
global._mockFetchResponses['auction_snapshot.json'] = {
  fetched: bjToday + 'T09:28:00+08:00', '指数竞价': [],
  '涨跌家数': {}, '高标竞价': [], '自选池竞价': [], '信号灯': {}
};
global._mockFetchResponses['sentiment_auto.json'] = {};
global._mockFetchResponses['sentiment_auto.json'][bjToday] = [{ node: '10:00', '情绪值': 65 }];

DataStore.fetchAll().then(function() {
  console.log(JSON.stringify({
    status: DataStore.getConnectionStatus(),
    freshness: (DataStore.merged || {})._freshness || null
  }));
}).catch(function(e) { console.log(JSON.stringify({ _error: String(e).slice(0,200) })); });
"""
        result = _run_node(script, files=["store.js"])
        self.assertEqual(result.get("freshness", {}).get("level"), "dead", f"result={result}")
        self.assertNotEqual(result.get("status"), "live", f"过期行情不应显示实时: {result}")

    def test_stale_iwencai_payload_clears_baseline_values(self):
        """stale iwencai 只保留元信息，不沿用旧情绪数值"""
        script = BASE_MOCKS + r"""
global._mockFetchResponses['/api/baseline'].iwencai = { '情绪值': 59, '涨停家数': 42 };
global._mockFetchResponses['/api/live/quotes'] = {
  live_index: {}, live_quotes: {},
  iwencai: {
    _updated: '2020-01-01T11:26:00+08:00',
    _freshness: { level: 'stale', type: 'iwencai', age_seconds: 999999 },
    _stale: true,
    _available: false
  },
  _freshness: { level: 'live' }
};
DataStore.fetchAll().then(function() {
  var iw = (DataStore.merged || {}).iwencai || {};
  console.log(JSON.stringify({
    emotion: iw['情绪值'],
    limitUp: iw['涨停家数'],
    level: iw._freshness && iw._freshness.level,
    stale: iw._stale === true
  }));
}).catch(function(e) { console.log(JSON.stringify({ _error: String(e).slice(0,200) })); });
"""
        result = _run_node(script, files=["store.js"])
        self.assertIsNone(result.get("emotion"), f"stale iwencai 不应保留旧情绪值: {result}")
        self.assertIsNone(result.get("limitUp"), f"stale iwencai 不应保留旧涨停家数: {result}")
        self.assertEqual(result.get("level"), "stale", f"stale 元信息应保留: {result}")
        self.assertTrue(result.get("stale"), f"stale 标记应保留: {result}")

    def test_sse_tick_refreshes_account_and_trade_tickets(self):
        """SSE 打开时 tick 仍应刷新 W15/W24 的账户与票据数据"""
        script = BASE_MOCKS + r"""
var pnlAsset = 100000;
var ticketId = 'T-OLD';
var calls = [];
global.fetch = function(url) {
  var u = String(url);
  calls.push(u);
  if (u.indexOf('/api/baseline') >= 0) {
    return Promise.resolve({ ok: true, json: function() { return Promise.resolve({
      meta: {}, market: {}, sentiment: {}, lianban_pool: [], trend_pool: [],
      positions: [], sectors: [], risk: {}, style: { '总分': 85 }
    }); } });
  }
  if (u.indexOf('/api/live/quotes') >= 0) {
    return Promise.resolve({ ok: true, json: function() { return Promise.resolve({
      live_index: {}, live_quotes: {}, iwencai: {}, _freshness: { level: 'live' }
    }); } });
  }
  if (u.indexOf('/api/pnl/summary') >= 0) {
    return Promise.resolve({ ok: true, json: function() { return Promise.resolve({ total_asset: pnlAsset }); } });
  }
  if (u.indexOf('/api/trade/tickets') >= 0) {
    return Promise.resolve({ ok: true, json: function() { return Promise.resolve({ tickets: [{ ticket_id: ticketId, status: 'filled' }] }); } });
  }
  return Promise.resolve({ ok: false, json: function() { return Promise.resolve(null); } });
};
global.EventSource = function(url) { this.url = url; this.readyState = EventSource.OPEN; };
EventSource.CONNECTING = 0; EventSource.OPEN = 1; EventSource.CLOSED = 2;

DataStore.fetchAll().then(function() {
  DataStore.init();
  pnlAsset = 712022.47;
  ticketId = 'TICKET-20260610-301488-0001';
  DataStore.refresh('tick');
  setTimeout(function() {
    var m = DataStore.merged || {};
    console.log(JSON.stringify({
      totalAsset: m.pnl_live && m.pnl_live.total_asset,
      ticketId: m.trade_tickets && m.trade_tickets[0] && m.trade_tickets[0].ticket_id,
      pnlCalls: calls.filter(function(u){ return u.indexOf('/api/pnl/summary') >= 0; }).length,
      ticketCalls: calls.filter(function(u){ return u.indexOf('/api/trade/tickets') >= 0; }).length
    }));
  }, 30);
}).catch(function(e) { console.log(JSON.stringify({ _error: String(e).slice(0,200) })); });
"""
        result = _run_node(script, files=["store.js"])
        self.assertEqual(result.get("totalAsset"), 712022.47, f"SSE tick 应刷新账户摘要: {result}")
        self.assertEqual(result.get("ticketId"), "TICKET-20260610-301488-0001", f"SSE tick 应刷新票据: {result}")
        self.assertGreaterEqual(result.get("pnlCalls", 0), 2, f"fetchAll + tick 都应拉 pnl: {result}")
        self.assertGreaterEqual(result.get("ticketCalls", 0), 2, f"fetchAll + tick 都应拉 tickets: {result}")

    def test_refresh_tick_preserves_domains(self):
        script = BASE_MOCKS + r"""
global._mockFetchResponses['auction_snapshot.json'] = {
  fetched: bjToday + 'T09:28:00+08:00', '指数竞价': [],
  '涨跌家数': {}, '高标竞价': [], '自选池竞价': [], '信号灯': {}
};
global._mockFetchResponses['sentiment_auto.json'] = {};
global._mockFetchResponses['sentiment_auto.json'][bjToday] = [{ node: '10:00', '情绪值': 65 }];

DataStore.fetchAll().then(function() {
  for (var i = 0; i < 60; i++) { DataStore.refresh('tick'); }
  var m = DataStore.merged || {};
  console.log(JSON.stringify({ hasAuction: !!(m.auction_snapshot), hasNodes: !!(m.sentiment_nodes) }));
}).catch(function(e) { console.log(JSON.stringify({ _error: String(e).slice(0,200) })); });
"""
        result = _run_node(script, files=["store.js"])
        self.assertTrue(result.get("hasAuction"), f"result={result}")
        self.assertTrue(result.get("hasNodes"), f"result={result}")


# ── W05 stale + no fetch tests ──

class W05StaleTest(unittest.TestCase):

    def test_w05_stale_banner_in_html(self):
        script = r"""
var _body = document.createElement('div'); _body.id = 'body_W05';
var inst = new SentimentDashWidget({id: 'W05'});
inst.getBody = function() { return _body; };
inst.updateTimestamp = function() {};
inst.render({ sentiment_nodes: {
  _available: true, _stale: true,
  '2026-05-27': [{ node: '10:00', time: '2026-05-27T11:26:00+08:00', '情绪值': 65 }]
} });
var html = (_body.innerHTML || '').replace(/\s+/g, ' ');
console.log(JSON.stringify({
  hasStale: html.indexOf('数据过期') >= 0,
  hasTime: html.indexOf('11:26') >= 0,
  hasDashed: html.indexOf('border-style:dashed') >= 0,
  leaksOldEmotion: html.indexOf('65%') >= 0,
  hasTable: html.indexOf('<table') >= 0
}));
"""
        result = _run_node(script, files=["widgets/sentiment-dash.js"])
        self.assertTrue(result.get("hasStale"), "stale 横幅应在 HTML 中")
        self.assertTrue(result.get("hasTime"), f"stale 横幅应显示数据时间: {result}")
        self.assertTrue(result.get("hasDashed"), f"stale 态应有虚线视觉区分: {result}")
        self.assertFalse(result.get("leaksOldEmotion"), f"stale 时不应展示旧情绪百分比: {result}")
        self.assertTrue(result.get("hasTable"), "表格应渲染")

    def test_w05_picks_latest_date_key(self):
        """同时存在前日和今日节点时，W05 必须用最新日期 key 显示今日节点"""
        script = r"""
var _body = document.createElement('div'); _body.id = 'body_W05';
var inst = new SentimentDashWidget({id: 'W05'});
inst.getBody = function() { return _body; };
inst.updateTimestamp = function() {};
// Today + yesterday: today has data, yesterday also has data
var nodes = {
  _available: true, _stale: false,
  '2026-05-25': [{ node: '午盘', '情绪值': 30, '上证指数': 4100 }],
  '2026-05-26': [{ node: '早盘', '情绪值': 65, '上证指数': 4200 }]
};
inst.render({ sentiment_nodes: nodes });
var html = (_body.innerHTML || '').replace(/\s+/g, ' ');
// Should contain today's data (4200), not yesterday's (4100)
console.log(JSON.stringify({
  hasToday: html.indexOf('4200') >= 0,
  hasYesterday: html.indexOf('4100') >= 0,
  hasTable: html.indexOf('<table') >= 0
}));
"""
        result = _run_node(script, files=["widgets/sentiment-dash.js"])
        self.assertTrue(result.get("hasToday"), f"应显示今日节点: {result}")
        self.assertFalse(result.get("hasYesterday"), f"不应显示前日节点: {result}")

    def test_w05_no_llm_fetch_in_source(self):
        src = (ROOT / "widgets" / "sentiment-dash.js").read_text()
        self.assertNotIn("llm_insights.json", src)
        self.assertNotIn("_loadLLM", src)


class W06Test(unittest.TestCase):

    def test_w06_no_auction_fetch(self):
        src = (ROOT / "widgets" / "auction-5d.js").read_text()
        self.assertNotIn("auction_snapshot.json", src)

    def test_w06_renders_unavailable(self):
        script = r"""
var _body = document.createElement('div'); _body.id = 'body_W06';
var inst = new Auction5DWidget({id: 'W06'});
inst.getBody = function() { return _body; };
inst.updateTimestamp = function() {};
inst.render({ auction_snapshot: { _available: false, _stale: true } });
var html = (_body.innerHTML || '').replace(/\s+/g, ' ');
console.log(JSON.stringify({hasUnavail: html.indexOf('不可用') >= 0}));
"""
        result = _run_node(script, files=["widgets/auction-5d.js"])
        self.assertTrue(result.get("hasUnavail"))


# ── W11 hover after re-render ──

class W11HoverTest(unittest.TestCase):

    def test_w11_tooltip_after_rerender(self):
        script = r"""
var _body = document.createElement('div'); _body.id = 'body_W11';
var _tipEl = document.createElement('div'); _tipEl.id = 'w11tip';
_tipEl.style = { display: 'none' }; _tipEl.textContent = '';
var origQS = _body.querySelector;
_body.querySelector = function(sel) {
  if (sel === '#w11tip') return _tipEl;
  return origQS.call(_body, sel);
};
_body.insertAdjacentHTML = function() {};

var inst = new VolumeBarsWidget({id: 'W11'});
inst.getBody = function() { return _body; };
inst.updateTimestamp = function() {};

var testData = {
  '上证15min': [{ t: '10:00', chg: 1.5, volRatio: 1.2, amount: 100000000 }],
  '深证15min': [], '创业15min': [], live_index: {}
};

inst.render(testData);
var l1 = inst._domListeners.length;
inst.render(testData);
var l2 = inst._domListeners.length;

// Simulate hover
var barEl = { classList: { contains: function(c) { return c === 'w11b'; } },
              getAttribute: function() { return '上证 10:00'; }, style: {} };
var me = { target: barEl, clientX: 100, clientY: 200 };
inst._domListeners.filter(function(d) { return d.event === 'mouseover'; }).forEach(function(d) { d.fn(me); });
var shown = _tipEl.style.display === 'block';
inst._domListeners.filter(function(d) { return d.event === 'mouseout'; }).forEach(function(d) { d.fn(me); });
var hidden = _tipEl.style.display === 'none';

inst.unmount();
var l0 = inst._domListeners.length;
inst.render(testData);
var l3 = inst._domListeners.length;

console.log(JSON.stringify({
  sameAfterRerender: l1 === l2 && l1 > 0,
  tipShown: shown, tipHidden: hidden,
  clearedOnUnmount: l0 === 0,
  rebindsAfterRemount: l3 === l1
}));
"""
        result = _run_node(script, files=["widgets/volume-bars.js"])
        self.assertTrue(result.get("sameAfterRerender"), f"result={result}")
        self.assertTrue(result.get("tipShown"), f"hover 应显示 tooltip: {result}")
        self.assertTrue(result.get("tipHidden"), f"mouseout 应隐藏 tooltip: {result}")
        self.assertTrue(result.get("clearedOnUnmount"), f"unmount 应清理: {result}")
        self.assertTrue(result.get("rebindsAfterRemount"), f"remount 应重绑定: {result}")

    def test_w11_uses_on_delegation(self):
        src = (ROOT / "widgets" / "volume-bars.js").read_text()
        self.assertIn("this._on(body", src)
        self.assertIn("_hoverBound", src)

    def test_w11_empty_today_data_shows_waiting_state(self):
        script = r"""
var _body = document.createElement('div'); _body.id = 'body_W11';
var inst = new VolumeBarsWidget({id: 'W11'});
inst.getBody = function() { return _body; };
inst.updateTimestamp = function() {};
inst.render({'上证15min': [], '深证15min': [], '创业15min': [], live_index: {}});
console.log(JSON.stringify({html: _body.innerHTML}));
"""
        result = _run_node(script, files=["widgets/volume-bars.js"])
        self.assertIn("等待今日15min数据", result.get("html", ""))


class W12W13W16LifecycleTest(unittest.TestCase):

    def test_w12_uses_on(self):
        src = (ROOT / "widgets" / "lianban-pool.js").read_text()
        self.assertIn("this._on(body", src)
        self.assertIn("_sortBound", src)

    def test_w13_uses_on(self):
        src = (ROOT / "widgets" / "trend-pool.js").read_text()
        self.assertIn("this._on(body", src)
        self.assertIn("_sortBound", src)

    def test_w16_uses_on(self):
        src = (ROOT / "widgets" / "input-panel.js").read_text()
        self.assertIn("this._on(body", src)
        self.assertIn("_delegatedBound", src)


if __name__ == "__main__":
    unittest.main()
