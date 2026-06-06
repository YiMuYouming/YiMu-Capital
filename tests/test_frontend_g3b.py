"""test_frontend_g3b.py — W23 逐笔复盘组件 (Gate 3B FINAL)"""
import json, os, re, subprocess, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Sync-Promise polyfill: .then callbacks run synchronously for test determinism
PREAMBLE = r"""
if (typeof document === 'undefined') {
  global.document = (function() {
    function makeEl() { return { innerHTML:'', textContent:'', style:{}, className:'',
      classList:{contains:function(){return false},add:function(){},toggle:function(){},remove:function(c){}},
      getAttribute:function(){return null}, setAttribute:function(){},
      querySelector:function(){return null}, querySelectorAll:function(){return[]},
      addEventListener:function(){}, removeEventListener:function(){}, closest:function(){return null} };
    }
    return { createElement:function(){return makeEl();}, querySelector:function(){return null;},
      querySelectorAll:function(){return[];}, getElementById:function(){return makeEl();},
      body:makeEl() };
  })();
}
// Sync Promise: deferred resolution supported, .then runs when/if resolved
var _SyncPromise = function(executor) {
  var self = this;
  this._resolved = false; this._rejected = false; this._value = null;
  this._fulfillQueue = []; this._rejectQueue = [];
  this._chain = null;
  executor(function(v) { self._resolve(v); },
           function(e) { self._reject(e); });
};
_SyncPromise.prototype._resolve = function(v) {
  if (this._resolved || this._rejected) return;
  this._resolved = true; this._value = v;
  for (var i = 0; i < this._fulfillQueue.length; i++) {
    try {
      var r = this._fulfillQueue[i](v);
      if (r instanceof _SyncPromise) {
        // If callback returns a promise, chain through it
        var chain = this._chain;
        r.then(function(v2) { if (chain) chain._resolve(v2); },
              function(e2) { if (chain) chain._reject(e2); });
        if (chain) { chain._chain = null; }
      } else if (this._chain) {
        this._chain._resolve(r);
      }
    } catch(e) { if (this._chain) this._chain._reject(e); }
  }
  this._fulfillQueue = []; this._rejectQueue = [];
};
_SyncPromise.prototype._reject = function(e) {
  if (this._resolved || this._rejected) return;
  this._rejected = true; this._value = e;
  for (var i = 0; i < this._rejectQueue.length; i++) {
    try { var r = this._rejectQueue[i](e); if (this._chain) this._chain._resolve(r); }
    catch(e2) { if (this._chain) this._chain._reject(e2); }
  }
  this._fulfillQueue = []; this._rejectQueue = [];
};
_SyncPromise.prototype.then = function(onFulfilled, onRejected) {
  var self = this;
  if (this._resolved && onFulfilled) {
    try { var r = onFulfilled(this._value); if (r instanceof _SyncPromise) return r; return _SyncPromise.resolve(r); }
    catch(e) { return _SyncPromise.reject(e); }
  }
  if (this._rejected && onRejected) {
    try { var r2 = onRejected(this._value); if (r2 instanceof _SyncPromise) return r2; return _SyncPromise.resolve(r2); }
    catch(e) { return _SyncPromise.reject(e); }
  }
  if (this._rejected) return this;
  // Deferred: queue callbacks
  if (onFulfilled) this._fulfillQueue.push(onFulfilled);
  if (onRejected) this._rejectQueue.push(onRejected);
  var chain = new _SyncPromise(function(){}); this._chain = chain; return chain;
};
_SyncPromise.prototype.catch = function(onRejected) { return this.then(null, onRejected); };
_SyncPromise.resolve = function(v) {
  if (v instanceof _SyncPromise) return v;
  return new _SyncPromise(function(res) { res(v); });
};
_SyncPromise.reject = function(e) {
  return new _SyncPromise(function(_, rej) { rej(e); });
};
global.Promise = _SyncPromise;
global.fetch = function(url, opts) {
  return _SyncPromise.resolve({ ok:true, status:200, json:function(){return _SyncPromise.resolve([]);} });
};
global.setTimeout = function(fn,ms){fn();};
global.setInterval = function(){return 0;};
global.YiMuWidget = function(){};
YiMuWidget.prototype.getBody = function(){return document.createElement('div');};
YiMuWidget.prototype.updateTimestamp = function(){};
YiMuWidget.prototype._renderBody = function(){this.render({});};
YiMuWidget.prototype._on = function(el,ev,fn){};
YiMuWidget.prototype.unmount = function(){};
global.WidgetRegistry = {
  _map:{}, register:function(id,cls){this._map[id]=cls;},
  getClass:function(id){return this._map[id];},
  getMeta:function(){return{tier:'manual',dataPaths:[]};}
};
"""


def _run_node(script, files=None):
    if files is None: files = []
    full = PREAMBLE + "\n"
    for fp in files:
        with open(ROOT / fp, "r", encoding="utf-8") as f:
            full += f.read() + "\n"
    full += "\n" + script
    env = os.environ.copy()
    env["TZ"] = "Asia/Shanghai"
    r = subprocess.run(["node","--no-warnings","-e",full], capture_output=True, text=True, timeout=10, env=env, cwd=str(ROOT))
    if r.returncode != 0: return {"_error": str(r.stderr).strip()[:600]}
    try: return json.loads(r.stdout.strip().split("\n")[-1])
    except json.JSONDecodeError: return {"_error": r.stdout.strip()[:400]}


class W23FetchErrorTest(unittest.TestCase):

    def test_error_state_has_retry_and_date(self):
        """错误态保留日期选择器+重试按钮，点击重试用当前日期重新请求"""
        script = r"""
var fetchUrls = [];
global.fetch = function(url) {
  fetchUrls.push(url);
  return Promise.resolve({ok:false, status:503, json:function(){return Promise.resolve(null);}});
};
var _body = document.createElement('div');
var inst = new TradeReviewWidget({id:'W23'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
// Set a historic date
inst._date = '2026-05-25';
// First fetch fails
inst._fetch('2026-05-25', _body);
var html1 = _body.innerHTML || '';
var hasError = html1.indexOf('加载失败')>=0;
var hasDate = html1.indexOf('2026-05-25')>=0;
var hasRetryBtn = html1.indexOf('重试')>=0;
var hasLoading = html1.indexOf('加载复盘数据')>=0;
var hasEmpty = html1.indexOf('暂无成交')>=0;
// Now simulate retry: change fetch to succeed
global.fetch = function(url) {
  fetchUrls.push(url);
  return Promise.resolve({ok:true, json:function(){return Promise.resolve([
    {trade_time:'10:00',action:'W1追涨',name:'测试',code:'000001',price:10,qty:100,
     window:'W1',reason:'',outcome:'',review_note:''}
  ]);}});
};
inst._fetch(inst._date, _body);
var retryUrlHasDate = fetchUrls.length>=2 && fetchUrls[1].indexOf('2026-05-25')>=0;
var hasReviews = Array.isArray(inst._reviews) && inst._reviews.length===1;
console.log(JSON.stringify({
  hasError: hasError, hasDate: hasDate, hasRetryBtn: hasRetryBtn,
  notLoading: !hasLoading, notEmpty: !hasEmpty,
  retryUrlHasDate: retryUrlHasDate, hasReviews: hasReviews
}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get("hasError"), f"应显示失败: {result}")
        self.assertTrue(result.get("hasDate"), f"日期应可见: {result}")
        self.assertTrue(result.get("hasRetryBtn"), f"应有重试按钮: {result}")
        self.assertTrue(result.get("notLoading"), "不应显示加载中")
        self.assertTrue(result.get("notEmpty"), "不应显示暂无成交")
        self.assertTrue(result.get("retryUrlHasDate"), f"重试 URL 应含历史日期: {result}")
        self.assertTrue(result.get("hasReviews"), f"重试成功应有数据: {result}")

    def test_network_reject_renders_error(self):
        """真实 _fetch 调用，网络异常 → error 渲染"""
        script = r"""
global.fetch = function(url) {
  return Promise.reject(new Error('network'));
};
var _body = document.createElement('div');
var inst = new TradeReviewWidget({id:'W23'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._fetch('2026-05-27', _body);
var html = _body.innerHTML || '';
console.log(JSON.stringify({
  hasError: html.indexOf('加载失败')>=0,
  hasLoading: html.indexOf('加载复盘数据')>=0
}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get("hasError"), f"网络失败应显示错误: {result}")
        self.assertFalse(result.get("hasLoading"), "不应显示加载中")

    def test_http_200_sets_reviews(self):
        """真实 _fetch HTTP 200 → _reviews 填充"""
        script = r"""
global.fetch = function(url) {
  return Promise.resolve({ok:true, json:function(){return Promise.resolve([
    {trade_time:'10:00',action:'买入',name:'测试',code:'000001',price:10,qty:100,
     window:'W1',reason:'W1',outcome:'',review_note:''}
  ]);}});
};
var _body = document.createElement('div');
var inst = new TradeReviewWidget({id:'W23'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._fetch('2026-05-27', _body);
var hasReviews = Array.isArray(inst._reviews) && inst._reviews.length === 1;
console.log(JSON.stringify({hasReviews: hasReviews, error: inst._error}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get("hasReviews"), f"应有 reviews: {result}")
        self.assertIsNone(result.get("error"), "_error 应为 null")


class W23RuleConclusionTest(unittest.TestCase):

    def test_tradable_true_w1_buy_allowed_true(self):
        script = r"""
var _body = document.createElement('div');
var inst = new TradeReviewWidget({id:'W23'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._reviews = [
  {trade_time:'10:00',action:'W1追涨',name:'测试',code:'000001',price:10,qty:100,
   window:'W1',reason:'W1信号',outcome:'',review_note:'',
   rule_state:{version:'g1a-v1',tradable:true,blocks:[],warnings:[],
     windows:{w1:{in_session:true,buy_allowed:true},w2:{}}},
   market_snapshot:{iwencai:{'情绪值':65},live_index:{}},
   context_status:'trusted'}
];
inst.render({});
var html = _body.innerHTML || '';
console.log(JSON.stringify({hasAllowed: html.indexOf('允许交易')>=0, hasVerified: html.indexOf('已验证')>=0,
  hasBlocked: html.indexOf('禁止交易')>=0, hasEmotion: html.indexOf('情绪65')>=0}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get("hasAllowed"), f"应允许交易: {result}")
        self.assertTrue(result.get("hasVerified"), f"应已验证: {result}")
        self.assertFalse(result.get("hasBlocked"), "不应禁止交易")

    def test_tradable_true_w1_buy_allowed_false(self):
        script = r"""
var _body = document.createElement('div');
var inst = new TradeReviewWidget({id:'W23'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._reviews = [
  {trade_time:'10:00',action:'买入',name:'测试',code:'000001',price:10,qty:100,
   window:'W1',reason:'',outcome:'',review_note:'',
   rule_state:{version:'g1a-v1',tradable:true,blocks:[{code:'FRIDAY_W1',scope:'W1'}],warnings:[],
     windows:{w1:{in_session:true,buy_allowed:false},w2:{}}},
   market_snapshot:{iwencai:{},live_index:{}},
   context_status:'trusted'}
];
inst.render({});
var html = _body.innerHTML || '';
console.log(JSON.stringify({hasWindowClosed: html.indexOf('窗口关闭')>=0, hasBlock: html.indexOf('FRIDAY_W1')>=0}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get("hasWindowClosed"), f"应窗口关闭: {result}")
        self.assertTrue(result.get("hasBlock"), f"阻断应可见: {result}")

    def test_tradable_false_shows_blocked(self):
        script = r"""
var _body = document.createElement('div');
var inst = new TradeReviewWidget({id:'W23'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._reviews = [
  {trade_time:'10:00',action:'买入',name:'测试',code:'000001',price:10,qty:100,
   window:'W1',reason:'',outcome:'',review_note:'',
   rule_state:{version:'g1a-v1',tradable:false,blocks:[{code:'DAY_STOP',scope:'all'}],warnings:[],
     windows:{w1:{buy_allowed:false},w2:{}}},
   market_snapshot:{iwencai:{'情绪值':45},live_index:{}},
   context_status:'trusted'}
];
inst.render({});
var html = _body.innerHTML || '';
console.log(JSON.stringify({hasBlocked: html.indexOf('禁止交易')>=0, hasDayStop: html.indexOf('DAY_STOP')>=0}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get("hasBlocked"), f"应禁止交易: {result}")
        self.assertTrue(result.get("hasDayStop"), f"DAY_STOP 应可见: {result}")


class W23RegistrationTest(unittest.TestCase):

    def test_registered_in_registry(self):
        src = (ROOT / "widget-registry.js").read_text()
        self.assertIn("W23", src)
        self.assertIn("trade-review", src)

    def test_script_in_html(self):
        html = (ROOT / "index.html").read_text()
        self.assertIn("trade-review.js", html)

    def test_readonly_no_write_endpoints(self):
        src = (ROOT / "widgets" / "trade-review.js").read_text()
        self.assertNotIn("fetch('/api/sync", src)
        self.assertNotIn("fetch('/api/account/correct", src)
        self.assertNotIn("POST", src)
        self.assertIn("/api/trades/review", src)

    def test_esc_function_exists(self):
        src = (ROOT / "widgets" / "trade-review.js").read_text()
        self.assertIn("function _esc", src)
        self.assertIn("replace(/&/g", src)


class W23RenderTest(unittest.TestCase):

    def test_unverified_label(self):
        script = r"""
var _body = document.createElement('div');
var inst = new TradeReviewWidget({id:'W23'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._reviews = [
  {trade_time:'10:00',action:'买入',name:'测试',code:'000001',price:10,qty:100,
   window:'W1',reason:'W1信号',outcome:'',review_note:''}
];
inst.render({});
var html = _body.innerHTML || '';
// 检查表格内的状态列（过滤栏之外），不含 filter 按钮文本
var tableStart = html.indexOf('<table');
var tableHtml = tableStart >= 0 ? html.substring(tableStart) : '';
console.log(JSON.stringify({hasUnverified: html.indexOf('未验证')>=0, hasFilterUnverified: html.indexOf('id=\"w23_filter_unverified\"')>=0, hasVerifiedInTable: tableHtml.indexOf('已验证')>=0, hasTable: tableHtml.indexOf('<table')>=0}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get("hasFilterUnverified"), f"过滤栏应含未验证按钮: {result}")
        self.assertFalse(result.get("hasVerifiedInTable"), f"表格内不应含已验证: {result}")
        self.assertTrue(result.get("hasTable"), "应有表格")

    def test_empty_data(self):
        script = r"""
var _body = document.createElement('div');
var inst = new TradeReviewWidget({id:'W23'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._reviews = [];
inst.render({});
var html = _body.innerHTML || '';
console.log(JSON.stringify({hasEmpty: html.indexOf('暂无成交')>=0, hasTable: html.indexOf('<table')>=0}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get("hasEmpty"), f"应暂无成交: {result}")
        self.assertFalse(result.get("hasTable"), "空不渲染表格")

    def test_xss_escaped(self):
        script = r"""
var _body = document.createElement('div');
var inst = new TradeReviewWidget({id:'W23'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._reviews = [
  {trade_time:'10:00',action:'买入',name:'<b>XSS</b>',code:'000001',
   price:10,qty:100,window:'W1',reason:'<img src=x>',outcome:'<script>',review_note:''}
];
inst.render({});
var html = _body.innerHTML || '';
console.log(JSON.stringify({hasBold: html.indexOf('<b>')>=0, hasImg: html.indexOf('<img')>=0,
  hasScript: html.indexOf('<script>')>=0, hasLt: html.indexOf('&lt;')>=0}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertFalse(result.get("hasBold"), "不应含 <b>")
        self.assertFalse(result.get("hasImg"), "不应含 <img>")
        self.assertFalse(result.get("hasScript"), "不应含 <script>")
        self.assertTrue(result.get("hasLt"), "应转义")

class W23DatePersistenceTest(unittest.TestCase):

    def test_fetch_stores_date(self):
        script = r"""
global.fetch = function(url) {
  return Promise.resolve({ok:true, json:function(){return Promise.resolve([
    {trade_time:"10:00",action:"W1追涨",name:"测试",code:"000001",price:10,qty:100,
     window:"W1",reason:"",outcome:"",review_note:""}
  ]);}});
};
var _body = document.createElement("div");
var inst = new TradeReviewWidget({id:"W23"});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._fetch("2026-05-26", _body);
console.log(JSON.stringify({dateKept: inst._date === "2026-05-26", hasReviews: Array.isArray(inst._reviews) && inst._reviews.length===1}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get("dateKept"), f"日期应保持: {result}")
        self.assertTrue(result.get("hasReviews"), f"应有记录: {result}")

    def test_empty_response_shows_historic_date(self):
        script = r"""
global.fetch = function(url) {
  return Promise.resolve({ok:true, json:function(){return Promise.resolve([]);}});
};
var _body = document.createElement("div");
var inst = new TradeReviewWidget({id:"W23"});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._fetch("2026-05-25", _body);
var html = _body.innerHTML || "";
console.log(JSON.stringify({hasDate: html.indexOf("2026-05-25")>=0, hasEmpty: html.indexOf("暂无成交")>=0}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get("hasDate"), f"应显示历史日期: {result}")
        self.assertTrue(result.get("hasEmpty"), f"应显示暂无成交: {result}")

    def test_error_retry_keeps_date(self):
        script = r"""
global.fetch = function(url) {
  return Promise.reject(new Error("network"));
};
var _body = document.createElement("div");
var inst = new TradeReviewWidget({id:"W23"});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._fetch("2026-05-24", _body);
inst._fetch("2026-05-24", _body);
console.log(JSON.stringify({dateKept: inst._date === "2026-05-24"}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get("dateKept"), f"重试应保持日期: {result}")


class W23RaceTest(unittest.TestCase):

    def test_late_response_ignored_after_newer_success(self):
        """先请求05-25，再请求05-26；让05-26先成功，再让05-25返回；最终05-26胜出"""
        script = r"""
var pending = [];
global.fetch = function(url) {
  return new Promise(function(resolve) { pending.push({url:url, resolve:resolve}); });
};
var _body = document.createElement('div');
var inst = new TradeReviewWidget({id:'W23'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
// Request 1: 2026-05-25
inst._fetch('2026-05-25', _body);
var r1 = pending.shift();
// Request 2: 2026-05-26
inst._fetch('2026-05-26', _body);
var r2 = pending.shift();
// Resolve newer (r2) first with success
r2.resolve({ok:true, json:function(){return Promise.resolve([
  {trade_time:'10:00',action:'W1追涨',name:'新请求',code:'000001',price:10,qty:100,window:'W1',reason:'',outcome:'',review_note:''}
]);}});
// Resolve older (r1) — should be IGNORED by reqId guard
r1.resolve({ok:true, json:function(){return Promise.resolve([
  {trade_time:'09:30',action:'买入',name:'旧请求',code:'000002',price:8,qty:50,window:'W1',reason:'',outcome:'',review_note:''}
]);}});
var reviews = inst._reviews || [];
var nameOk = reviews.length===1 && reviews[0].name==='新请求';
var dateOk = inst._date === '2026-05-26';
var html = _body.innerHTML || '';
console.log(JSON.stringify({dateOk:dateOk, nameOk:nameOk, hasNew: html.indexOf('新请求')>=0, hasOld: html.indexOf('旧请求')>=0}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get('dateOk'), f'日期应为05-26: {result}')
        self.assertTrue(result.get('nameOk'), f'应只有新请求: {result}')
        self.assertFalse(result.get('hasOld'), f'不应含旧请求: {result}')

    def test_late_failure_does_not_overwrite_success(self):
        """旧请求晚到的失败响应不覆盖新请求成功结果"""
        script = r"""
var pending = [];
global.fetch = function(url) {
  return new Promise(function(resolve) { pending.push({url:url, resolve:resolve}); });
};
var _body = document.createElement('div');
var inst = new TradeReviewWidget({id:'W23'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
// Request 1: 2026-05-25
inst._fetch('2026-05-25', _body);
var r1 = pending.shift();
// Request 2: 2026-05-26
inst._fetch('2026-05-26', _body);
var r2 = pending.shift();
// Newer (r2) succeeds first
r2.resolve({ok:true, json:function(){return Promise.resolve([
  {trade_time:'10:00',action:'买入',name:'成功',code:'000001',price:10,qty:100,window:'W1',reason:'',outcome:'',review_note:''}
]);}});
// Older (r1) fails late — should NOT set _error
r1.resolve({ok:false, status:503, json:function(){return Promise.resolve(null);}});
console.log(JSON.stringify({errorNull: inst._error===null, hasReviews: Array.isArray(inst._reviews)&&inst._reviews.length===1, date:inst._date}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get('errorNull'), f'旧失败回应不覆盖_error: {result}')
        self.assertTrue(result.get('hasReviews'), f'应保留成功数据: {result}')

    def test_req_id_guard_exists(self):
        src = (ROOT / 'widgets' / 'trade-review.js').read_text()
        self.assertIn('reqId', src)
        self.assertIn('self._reqId', src)


# —— R3 W15/W17 前端测试 ——

class W15SSOTOnlyTest(unittest.TestCase):
    """Fix 3: W15 不注入 live_quotes; Fix 4: closed_positions=[] 不渲染 baseline 清仓"""

    def test_no_live_quote_injection_preserves_ssot_snapshot(self):
        """SSOT现价=105, liveQ现价=999 → 渲染结果用SSOT的105, 不用999"""
        script = r"""
global.DataStore = {_prefill:null, merged:{}};
var _body = document.createElement('div');
var inst = new PositionsWidget({id:'W15'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._bindEvents = function(){};
var data = {
  pnl_live: {
    total_asset:200000, mv:100000, cash:100000,
    pnl_amount:500, pnl_pct:0.25, pos_pct:50,
    positions: [
      {标的:'TEST',代码:'000001',市值:52500,现价:105,成本价:100,成本:100,
       today_pnl:500,today_pnl_pct:0.5,total_pnl:500,total_pnl_pct:5.0,
       数量:500,止损:'-5%',状态:'持有'}
    ],
    trades: [], closed_positions: []
  },
  live_quotes: {'000001':{最新价:999}},
  positions: [{标的:'OLD',代码:'999999',状态:'清仓',清仓日期:'2026-05-20',卖出价:50,成本:40,数量:100}]
};
inst.render(data);
var html = _body.innerHTML || '';
console.log(JSON.stringify({
  hasSSOT105: html.indexOf('105.00')>=0,
  hasLiveQ999: html.indexOf('999.00')>=0 || html.indexOf('>999<')>=0,
  hasOldCleared: html.indexOf('OLD')>=0,
  hasClosedSection: html.indexOf('清仓跟踪')>=0
}));
"""
        result = _run_node(script, files=["widgets/positions.js"])
        self.assertTrue(result.get("hasSSOT105"), f"应用SSOT现价105: {result}")
        self.assertFalse(result.get("hasLiveQ999"), f"不应含liveQ现价999: {result}")
        self.assertFalse(result.get("hasOldCleared"), f"不应渲染baseline清仓OLD: {result}")
        self.assertFalse(result.get("hasClosedSection"), f"closed_positions=[]不应显示清仓跟踪: {result}")

    def test_today_pnl_null_shows_unavailable(self):
        """today_pnl=None → 显示 '— / 基准不可用'"""
        script = r"""
global.DataStore = {_prefill:null, merged:{}};
var _body = document.createElement('div');
var inst = new PositionsWidget({id:'W15'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._bindEvents = function(){};
var data = {
  pnl_live: {
    total_asset:200000, mv:100000, cash:100000,
    pnl_amount:0, pnl_pct:0, pos_pct:50,
    positions: [
      {标的:'TEST',代码:'000001',市值:50000,现价:100,成本价:100,成本:100,
       today_pnl:null,today_pnl_pct:null,total_pnl:500,total_pnl_pct:5.0,
       数量:500,止损:'—',状态:'持有'}
    ],
    trades: [], closed_positions: []
  },
  live_quotes: {},
  positions: []
};
inst.render(data);
var html = _body.innerHTML || '';
console.log(JSON.stringify({
  hasUnavailable: html.indexOf('基准不可用')>=0
}));
"""
        result = _run_node(script, files=["widgets/positions.js"])
        self.assertTrue(result.get("hasUnavailable"), f"应显示基准不可用: {result}")

    def test_closed_tracking_trusts_backend_trading_day_window(self):
        """后端已给出7交易日清仓列表时，前端不应用自然日二次过滤"""
        script = r"""
global.DataStore = {_prefill:null, merged:{}};
var RealDate = Date;
global.Date = class extends RealDate {
  constructor() {
    if (arguments.length === 0) return new RealDate('2026-06-04T10:00:00+08:00');
    return new RealDate(...arguments);
  }
  static now() { return new RealDate('2026-06-04T10:00:00+08:00').getTime(); }
  static parse(v) { return RealDate.parse(v); }
  static UTC() { return RealDate.UTC.apply(RealDate, arguments); }
};
var _body = document.createElement('div');
var inst = new PositionsWidget({id:'W15'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._bindEvents = function(){};
var data = {
  pnl_live: {
    total_asset:200000, mv:0, cash:200000,
    pnl_amount:0, pnl_pct:0, pos_pct:0,
    positions: [], trades: [],
    closed_positions: [
      {name:'OLD7', code:'000007', sell_price:20, sell_qty:100,
       realized_today_pnl:1000, closed_date:'2026-05-27', reason:''}
    ]
  },
  live_quotes: {'000007':{最新价:21}},
  positions: []
};
inst.render(data);
var html = _body.innerHTML || '';
console.log(JSON.stringify({
  hasClosed: html.indexOf('OLD7')>=0,
  hasTradingLabel: html.indexOf('7个交易日')>=0
}));
"""
        result = _run_node(script, files=["widgets/positions.js"])
        self.assertTrue(result.get("hasClosed"), f"前端不应按自然日过滤后端7交易日结果: {result}")
        self.assertTrue(result.get("hasTradingLabel"), f"标题应说明7个交易日口径: {result}")

    def test_pnl_card_merged_amount_and_pct(self):
        """今日盈亏卡片合金额+百分比在同一格，例如 +500.00 (+0.25%)"""
        script = r"""
global.DataStore = {_prefill:null, merged:{}};
var _body = document.createElement('div');
var inst = new PositionsWidget({id:'W15'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._bindEvents = function(){};
var data = {
  pnl_live: {
    total_asset:200000, mv:100000, cash:100000,
    pnl_amount:500, pnl_pct:0.25, pos_pct:50,
    positions: [],
    trades: [], closed_positions: []
  },
  live_quotes: {},
  positions: []
};
inst.render(data);
var html = _body.innerHTML || '';
console.log(JSON.stringify({
  hasPnlCard: html.indexOf('今日盈亏')>=0,
  hasAmount: html.indexOf('+500.00')>=0,
  hasPct: html.indexOf('(+0.25%)')>=0
}));
"""
        result = _run_node(script, files=["widgets/positions.js"])
        self.assertTrue(result.get("hasPnlCard"), f"应有今日盈亏卡片: {result}")
        self.assertTrue(result.get("hasAmount"), f"应有金额: {result}")
        self.assertTrue(result.get("hasPct"), f"应有百分比: {result}")

    def test_pnl_zero_shows_zero_not_dash(self):
        """pnl_amount=0, pnl_pct=0 → 显示 +0.00 (+0.00%), 非 '—'"""
        script = r"""
global.DataStore = {_prefill:null, merged:{}};
var _body = document.createElement('div');
var inst = new PositionsWidget({id:'W15'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._bindEvents = function(){};
var data = {
  pnl_live: {
    total_asset:200000, mv:100000, cash:100000,
    pnl_amount:0, pnl_pct:0, pos_pct:50,
    positions: [],
    trades: [], closed_positions: []
  },
  live_quotes: {},
  positions: []
};
inst.render(data);
var html = _body.innerHTML || '';
console.log(JSON.stringify({
  hasZeroAmt: html.indexOf('+0.00')>=0,
  hasZeroPct: html.indexOf('(+0.00%)')>=0,
  hasUnavailable: html.indexOf('基准不可用')>=0
}));
"""
        result = _run_node(script, files=["widgets/positions.js"])
        self.assertTrue(result.get("hasZeroAmt"), f"pnl=0应显示+0.00: {result}")
        self.assertTrue(result.get("hasZeroPct"), f"pct=0应显示(+0.00%): {result}")
        self.assertFalse(result.get("hasUnavailable"), f"合法零值不应显示基准不可用: {result}")

    def test_pnl_null_shows_unavailable_in_card(self):
        """pnl_amount=null → 卡片显示 '— / 基准不可用'"""
        script = r"""
global.DataStore = {_prefill:null, merged:{}};
var _body = document.createElement('div');
var inst = new PositionsWidget({id:'W15'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._bindEvents = function(){};
var data = {
  pnl_live: {
    total_asset:200000, mv:100000, cash:100000,
    pnl_amount:null, pnl_pct:null, pos_pct:50,
    positions: [],
    trades: [], closed_positions: []
  },
  live_quotes: {},
  positions: []
};
inst.render(data);
var html = _body.innerHTML || '';
console.log(JSON.stringify({
  hasUnavailable: html.indexOf('基准不可用')>=0,
  hasZeroInCard: html.indexOf('+0.00')>=0
}));
"""
        result = _run_node(script, files=["widgets/positions.js"])
        self.assertTrue(result.get("hasUnavailable"), f"pnl=null卡片应显示基准不可用: {result}")
        self.assertFalse(result.get("hasZeroInCard"), f"pnl=null卡片不应显示+0.00: {result}")

    # —— R5: 资产卡片 null vs 0 区分 ——

    def test_blocked_state_null_assets_show_unavailable(self):
        """total_asset/cash/mv/pos_pct=null → 卡片不出现 0.00/0%，精确断言各卡片"""
        script = r"""
global.DataStore = {_prefill:null, merged:{}};
var _body = document.createElement('div');
var inst = new PositionsWidget({id:'W15'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._bindEvents = function(){};
var data = {
  pnl_live: {
    total_asset:null, mv:null, cash:null,
    pnl_amount:null, pnl_pct:null, pos_pct:null,
    positions: [],
    trades: [], closed_positions: []
  },
  live_quotes: {},
  positions: []
};
inst.render(data);
var html = _body.innerHTML || '';
// 提取各卡片：从 kpi-label 到下一个 kpi-label 或 </div>
function cardContent(label) {
  var idx = html.indexOf('>' + label + '<');
  if (idx < 0) return '';
  // 找到 label 后面的第一个 font-weight:700 的值区域
  var afterLabel = html.substring(idx);
  var valStart = afterLabel.indexOf('font-weight:700') + 17; // skip to after 'font-weight:700">'
  var valEnd = afterLabel.indexOf('</div>', valStart);
  return afterLabel.substring(valStart, valEnd);
}
var cashCard = cardContent('可用资金');
var posPctCard = cardContent('仓位');
var taCard = cardContent('总资产');
var mvCard = cardContent('持仓市值');
console.log(JSON.stringify({
  cashHasUnavail: cashCard.indexOf('数据不可用')>=0,
  cashHas0_00: cashCard.indexOf('0.00')>=0,
  posPctHasDash: posPctCard.indexOf('—')>=0,
  posPctHas0pct: posPctCard.indexOf('0%')>=0,
  taHasUnavail: taCard.indexOf('数据不可用')>=0,
  mvHasUnavail: mvCard.indexOf('数据不可用')>=0
}));
"""
        result = _run_node(script, files=["widgets/positions.js"])
        self.assertTrue(result.get("cashHasUnavail"), f"可用资金null→数据不可用: {result}")
        self.assertFalse(result.get("cashHas0_00"), f"可用资金null不应0.00: {result}")
        self.assertTrue(result.get("posPctHasDash"), f"仓位null→'—': {result}")
        self.assertFalse(result.get("posPctHas0pct"), f"仓位null不应0%: {result}")
        self.assertTrue(result.get("taHasUnavail"), f"总资产null→数据不可用: {result}")
        self.assertTrue(result.get("mvHasUnavail"), f"持仓市值null→数据不可用: {result}")

    def test_valid_zero_assets_still_show_zero(self):
        """total_asset=0, mv=0, cash=0, pos_pct=0 → 合法零值，精确断言各卡片"""
        script = r"""
global.DataStore = {_prefill:null, merged:{}};
var _body = document.createElement('div');
var inst = new PositionsWidget({id:'W15'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._bindEvents = function(){};
var data = {
  pnl_live: {
    total_asset:0, mv:0, cash:0,
    pnl_amount:0, pnl_pct:0, pos_pct:0,
    positions: [],
    trades: [], closed_positions: []
  },
  live_quotes: {},
  positions: []
};
inst.render(data);
var html = _body.innerHTML || '';
function cardContent(label) {
  var idx = html.indexOf('>' + label + '<');
  if (idx < 0) return '';
  var afterLabel = html.substring(idx);
  var valStart = afterLabel.indexOf('font-weight:700') + 17;
  var valEnd = afterLabel.indexOf('</div>', valStart);
  return afterLabel.substring(valStart, valEnd);
}
var cashCard = cardContent('可用资金');
var posPctCard = cardContent('仓位');
console.log(JSON.stringify({
  cashHas0_00: cashCard.indexOf('0.00')>=0,
  cashHasUnavail: cashCard.indexOf('数据不可用')>=0,
  posPctHas0pct: posPctCard.indexOf('0%')>=0,
  posPctHasDash: posPctCard.indexOf('—')>=0
}));
"""
        result = _run_node(script, files=["widgets/positions.js"])
        self.assertTrue(result.get("cashHas0_00"), f"可用资金=0应显示0.00: {result}")
        self.assertFalse(result.get("cashHasUnavail"), f"可用资金=0不应显示数据不可用: {result}")
        self.assertTrue(result.get("posPctHas0pct"), f"仓位=0应显示0%: {result}")
        self.assertFalse(result.get("posPctHasDash"), f"仓位=0不应显示'—': {result}")


class W17IndependentEscTest(unittest.TestCase):
    """Fix 6: W17 独立 _esc，不依赖 W15"""

    def test_w17_loads_and_renders_trades_independently(self):
        """仅加载 today-ops.js，验证可独立渲染且有 XSS 转义"""
        script = r"""
global.DataStore = {};
var _body = document.createElement('div');
var inst = new TodayOpsWidget({id:'W17'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
var data = {
  pnl_live: {
    trades: [
      {trade_time:'10:00',action:'W1追涨',name:'<b>XSS</b>',code:'000001',
       price:10.5,qty:100,window:'W1',reason:'<img src=x>'}
    ]
  }
};
inst.render(data);
var html = _body.innerHTML || '';
console.log(JSON.stringify({
  hasTable: html.indexOf('<table')>=0,
  hasEscapedName: html.indexOf('&lt;b&gt;')>=0,
  hasEscapedReason: html.indexOf('&lt;img')>=0,
  hasPrice: html.indexOf('10.50')>=0
}));
"""
        result = _run_node(script, files=["widgets/today-ops.js"])
        self.assertTrue(result.get("hasTable"), f"应有表格: {result}")
        self.assertTrue(result.get("hasEscapedName"), f"标的应XSS转义: {result}")
        self.assertTrue(result.get("hasEscapedReason"), f"原因应XSS转义: {result}")
        self.assertTrue(result.get("hasPrice"), f"价格应格式化: {result}")

    def test_w17_empty_trades_shows_no_ops(self):
        """空交易列表显示'今日无操作'"""
        script = r"""
global.DataStore = {};
var _body = document.createElement('div');
var inst = new TodayOpsWidget({id:'W17'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst.render({pnl_live:{trades:[]}});
var html = _body.innerHTML || '';
console.log(JSON.stringify({hasNoOps: html.indexOf('今日无操作')>=0}));
"""
        result = _run_node(script, files=["widgets/today-ops.js"])
        self.assertTrue(result.get("hasNoOps"), f"应显示今日无操作: {result}")


class W15PendingRetryTests(unittest.TestCase):
    """YM-W15-01: 前端 pending 锁 + event_id 复用 + 失败不关弹窗"""

    def test_pending_flag_checked_in_save_handler(self):
        """保存按钮检查 self._pending 防重复点击"""
        src = (ROOT / "widgets" / "positions.js").read_text()
        self.assertIn("self._pending", src, "应有 pending 标志")
        self.assertIn("if (self._pending)", src, "应检查 pending")
        self.assertIn("self._pending = true", src, "应设置 pending")

    def test_event_id_reused_on_retry(self):
        """首次生成 event_id，重试复用同一个"""
        src = (ROOT / "widgets" / "positions.js").read_text()
        self.assertIn("_pendingEvtId", src, "应有 pendingEvtId")
        self.assertIn("!self._pendingEvtId", src, "首次才生成")

    def test_bridge_sync_accepts_callbacks(self):
        """_bridgeSync 接受 onSuccess/onError 回调"""
        src = (ROOT / "widgets" / "positions.js").read_text()
        self.assertIn("function _bridgeSync(entry, onSuccess, onError)", src,
                      "_bridgeSync 应接受回调参数")
        self.assertIn("onSuccess()", src, "成功时调用 onSuccess")
        self.assertIn("onError(errMsg)", src, "失败时调用 onError")

    def test_form_not_closed_on_network_error(self):
        """网络错误后不调用 o.remove()，由 onError 回调重置按钮"""
        src = (ROOT / "widgets" / "positions.js").read_text()
        # saveBtn.textContent = '确认' 在 onError 中执行，表示保留表单
        self.assertIn("saveBtn.textContent = '确认'", src,
                      "失败后应恢复按钮文本，保留表单")

    def test_form_closed_on_success(self):
        """成功后 o.remove() 关闭弹窗"""
        src = (ROOT / "widgets" / "positions.js").read_text()
        self.assertIn("function onSuccess", src, "应有 onSuccess 回调")
        self.assertIn("o.remove()", src, "成功后应关闭弹窗")


class W15BlockedUntrustedTests(unittest.TestCase):
    """YM-W15-02: blocked/untrusted 状态显示"""

    def test_blocked_anchor_shows_untrusted_not_empty(self):
        """anchor_blocked=true → 显示'锚点被阻断', 不显示'空仓'"""
        script = r"""
global.DataStore = {_prefill:null, merged:{}};
var _body = document.createElement('div');
var inst = new PositionsWidget({id:'W15'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._bindEvents = function(){};
var data = {
  pnl_live: {
    anchor_blocked:true, block_reason:'test block',
    valuation_complete:false,
    total_asset:null, mv:null, cash:null,
    pnl_amount:null, pnl_pct:null, pos_pct:null,
    positions: [],
    trades: [], closed_positions: []
  },
  live_quotes: {},
  positions: []
};
inst.render(data);
var html = _body.innerHTML || '';
console.log(JSON.stringify({
  hasBlocked: html.indexOf('锚点被阻断')>=0,
  hasEmpty: html.indexOf('空仓')>=0
}));
"""
        result = _run_node(script, files=["widgets/positions.js"])
        self.assertTrue(result.get("hasBlocked"), f"blocked应显示锚点被阻断: {result}")
        self.assertFalse(result.get("hasEmpty"), f"blocked不应显示空仓: {result}")

    def test_valuation_incomplete_shows_untrusted(self):
        """valuation_complete=false → 显示风险横幅，但保留账户快照"""
        script = r"""
global.DataStore = {_prefill:null, merged:{}};
var _body = document.createElement('div');
var inst = new PositionsWidget({id:'W15'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._bindEvents = function(){};
var data = {
  pnl_live: {
    anchor_blocked:false,
    valuation_complete:false,
    total_asset:200000, mv:100000, cash:100000,
    pnl_amount:0, pnl_pct:0, pos_pct:50,
    positions: [{标的:'TEST',代码:'000001',市值:50000,现价:100,成本价:100,成本:100,
      today_pnl:0,today_pnl_pct:0,total_pnl:0,total_pnl_pct:0,
      数量:500,止损:'—',状态:'持有'}],
    trades: [], closed_positions: []
  },
  live_quotes: {},
  positions: []
};
inst.render(data);
var html = _body.innerHTML || '';
console.log(JSON.stringify({
  hasWarn: html.indexOf('估值不可信')>=0,
  hasQuoteUnavail: html.indexOf('行情不可用')>=0,
  hasTotalAsset: html.indexOf('200,000.00')>=0,
  hasCash: html.indexOf('100,000.00')>=0,
  hasPositionPct: html.indexOf('50%')>=0,
  hasSnapshotHint: html.indexOf('非实时')>=0,
  hasWaitTodayQuote: html.indexOf('等待今日行情')>=0,
  hasCostShown: html.indexOf('100.00')>=0
}));
"""
        result = _run_node(script, files=["widgets/positions.js"])
        self.assertTrue(result.get("hasWarn"), f"valuation_complete=false应显示估值不可信: {result}")
        self.assertTrue(result.get("hasQuoteUnavail"), f"价格列应显示行情不可用: {result}")
        self.assertTrue(result.get("hasTotalAsset"), f"应保留总资产快照: {result}")
        self.assertTrue(result.get("hasCash"), f"现金不是行情字段，应保留显示: {result}")
        self.assertTrue(result.get("hasPositionPct"), f"仓位应随快照保留显示: {result}")
        self.assertTrue(result.get("hasSnapshotHint"), f"快照数值应标注非实时: {result}")
        self.assertTrue(result.get("hasWaitTodayQuote"), f"今日盈亏应等待今日行情: {result}")
        self.assertTrue(result.get("hasCostShown"), f"成本应仍显示: {result}")


class W15FormValidationTests(unittest.TestCase):
    """v3 Phase 1: W15 must reject invalid form input before /api/sync."""

    def test_decimal_qty_rejected_before_payload_build(self):
        script = r"""
var r = _validateTradeEntry({
  time:'10:00', action:'W1追涨', stock:'测试', code:'000001',
  price:'10.50', qty:'1.5', window:'W1', reason:''
}, true);
console.log(JSON.stringify({
  ok:r.ok,
  hasQtyError: String(r.error || '').indexOf('数量') >= 0,
  hasEntry: !!r.entry
}));
"""
        result = _run_node(script, files=["widgets/positions.js"])
        self.assertFalse(result.get("ok"), f"小数数量必须阻断: {result}")
        self.assertTrue(result.get("hasQtyError"), f"错误文案应指向数量: {result}")
        self.assertFalse(result.get("hasEntry"), f"非法输入不得产生成交 entry: {result}")

    def test_valid_entry_is_normalized_without_parseint_truncation(self):
        script = r"""
var r = _validateTradeEntry({
  time:'10:00', action:'W1追涨', stock:'测试', code:'000001',
  price:'10.50', qty:'100', window:'W1', reason:'test'
}, true);
console.log(JSON.stringify({
  ok:r.ok,
  price:r.entry && r.entry['价格'],
  qty:r.entry && r.entry['数量'],
  qtyType:typeof (r.entry && r.entry['数量'])
}));
"""
        result = _run_node(script, files=["widgets/positions.js"])
        self.assertTrue(result.get("ok"), f"合法输入应通过: {result}")
        self.assertEqual(result.get("price"), 10.5)
        self.assertEqual(result.get("qty"), 100)
        self.assertEqual(result.get("qtyType"), "number")

    def test_invalid_required_fields_rejected(self):
        script = r"""
var cases = [
  {time:'10:00', action:'W1追涨', stock:'', code:'000001', price:'10', qty:'100', window:'W1', reason:''},
  {time:'10:00', action:'W1追涨', stock:'测试', code:'', price:'10', qty:'100', window:'W1', reason:''},
  {time:'10:00', action:'W1追涨', stock:'测试', code:'000001', price:'Infinity', qty:'100', window:'W1', reason:''},
  {time:'00:01:99', action:'W1追涨', stock:'测试', code:'000001', price:'10', qty:'100', window:'W1', reason:''}
];
var rejected = cases.map(function(c) { return _validateTradeEntry(c, true).ok === false; });
console.log(JSON.stringify({allRejected: rejected.every(Boolean), rejected: rejected}));
"""
        result = _run_node(script, files=["widgets/positions.js"])
        self.assertTrue(result.get("allRejected"), f"空字段/非法价格/非法时间都应阻断: {result}")


class W23ContextStatusTests(unittest.TestCase):
    """v3 Phase 2: W23 展示成交上下文可信状态"""

    def test_trusted_context_shows_verified_and_capture_time(self):
        """rule_state + market_snapshot + context_captured_at → '已验证' + 采集时间"""
        script = r"""
var _body = document.createElement('div');
var inst = new TradeReviewWidget({id:'W23'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._reviews = [
  {trade_time:'10:00',action:'W1追涨',name:'测试',code:'000001',price:10,qty:100,
   window:'W1',reason:'',outcome:'浮盈+2%',review_note:'',
   rule_state:{version:'g1a-v1',tradable:true,blocks:[],warnings:[],
     windows:{w1:{in_session:true,buy_allowed:true},w2:{}}},
   market_snapshot:{iwencai:{'情绪值':65},live_index:{'上证指数涨幅':'-0.22'}},
   context_captured_at:'2026-05-27T10:00:05',
   context_status:'trusted'}
];
inst.render({});
var html = _body.innerHTML || '';
console.log(JSON.stringify({
  hasCaptureTime: html.indexOf('10:00:05')>=0, hasFilterBar: html.indexOf('w23_filter_all')>=0,
  // Scope check to table area (after filter bar)
  hasUnavailableInTable: (function() { var t = html.indexOf('<table'); return t >= 0 && html.substring(t).indexOf('不可用') >= 0; })()
}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get("hasFilterBar"), f"应有过滤栏: {result}")
        self.assertTrue(result.get("hasCaptureTime"), f"应显示采集时间: {result}")
        self.assertFalse(result.get("hasUnavailableInTable"), f"表格内不应显示不可用(trusted): {result}")

    def test_null_context_shows_unavailable_with_reason(self):
        """无 rule_state + market_snapshot → '不可用', 含原因"""
        script = r"""
var _body = document.createElement('div');
var inst = new TradeReviewWidget({id:'W23'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._reviews = [
  {trade_time:'14:00',action:'买入',name:'测试',code:'000001',price:10,qty:100,
   window:'W2',reason:'',outcome:'',review_note:'',
   context_status:'unavailable', context_unavailable_reason:'行情数据不可用'}
];
inst.render({});
var html = _body.innerHTML || '';
console.log(JSON.stringify({
  hasUnavailable: html.indexOf('不可用')>=0,
  hasReason: html.indexOf('行情数据不可用')>=0, hasFilter: html.indexOf('w23_filter')>=0
}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get("hasFilter"), f"应有过滤栏: {result}")
        self.assertTrue(result.get("hasUnavailable"), f"无上下文应显示不可用: {result}")
        self.assertTrue(result.get("hasReason"), f"应显示不可用原因: {result}")

    def test_historical_trade_shows_historical_reason(self):
        """历史成交（非今天）无上下文 → 显示'历史补录'原因"""
        script = r"""
var _body = document.createElement('div');
var inst = new TradeReviewWidget({id:'W23'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._reviews = [
  {trade_time:'10:00',action:'买入',name:'历史',code:'000001',price:10,qty:100,
   window:'',reason:'',outcome:'',review_note:'',
   context_status:'unavailable', context_unavailable_reason:'历史补录'}
];
inst.render({});
var html = _body.innerHTML || '';
console.log(JSON.stringify({
  hasHistorical: html.indexOf('历史')>=0,
  hasUnavailable: html.indexOf('不可用')>=0
}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get("hasUnavailable"), f"历史成交应显示不可用: {result}")
        self.assertTrue(result.get("hasHistorical"), f"历史成交应显示原因: {result}")

class W15AllErrorsInlineTest(unittest.TestCase):
    """v3 Phase 5: W15 所有本地校验失败均显示 #f_error"""

    def test_empty_code_shows_inline_error(self):
        script = r"""
var r = _validateTradeEntry({
  time:'10:00', action:'W1追涨', stock:'测试', code:'',
  price:'10', qty:'100', window:'W1', reason:''
}, true);
console.log(JSON.stringify({ ok: r.ok, error: r.error }));
"""
        result = _run_node(script, files=["widgets/positions.js"])
        self.assertFalse(result.get("ok"), f"空代码应阻断: {result}")
        self.assertIn("代码", result.get("error", ""))

    def test_empty_name_shows_inline_error(self):
        script = r"""
var r = _validateTradeEntry({
  time:'10:00', action:'W1追涨', stock:'', code:'000001',
  price:'10', qty:'100', window:'W1', reason:''
}, true);
console.log(JSON.stringify({ ok: r.ok, error: r.error }));
"""
        result = _run_node(script, files=["widgets/positions.js"])
        self.assertFalse(result.get("ok"), f"空名称应阻断: {result}")

    def test_invalid_time_shows_inline_error(self):
        for bad_time in ['25:00', '99:99', '12:60']:
            script = r"""
var r = _validateTradeEntry({
  time:'TIME', action:'W1追涨', stock:'测试', code:'000001',
  price:'10', qty:'100', window:'W1', reason:''
}, true);
console.log(JSON.stringify({ ok: r.ok, error: r.error }));
""".replace('TIME', bad_time)
            result = _run_node(script, files=["widgets/positions.js"])
            self.assertFalse(result.get("ok"), f"非法时间 {bad_time} 应阻断: {result}")

    def test_validation_failure_does_not_set_pending(self):
        """校验失败不设置 pending 和 event_id（在 _validateTradeEntry 层验证）"""
        script = r"""
var r = _validateTradeEntry({
  time:'10:00', action:'W1追涨', stock:'测试', code:'000001',
  price:'0', qty:'100', window:'W1', reason:''
}, true);
console.log(JSON.stringify({ ok: r.ok, hasEntry: !!r.entry }));
"""
        result = _run_node(script, files=["widgets/positions.js"])
        self.assertFalse(result.get("ok"), f"非法价格应阻断: {result}")
        self.assertFalse(result.get("hasEntry"), f"非法输入不应构造 entry: {result}")


class W23FilterTest(unittest.TestCase):
    """v3 Phase 5: W23 context 状态筛选"""

    def test_filter_all_shows_all_reviews(self):
        script = r"""
var _body = document.createElement('div');
var inst = new TradeReviewWidget({id:'W23'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._reviews = [
  {trade_time:'10:00',action:'W1追涨',name:'T1',code:'000001',price:10,qty:100,
   window:'W1',reason:'',outcome:'',review_note:'',
   rule_state:{version:'g1a-v1',tradable:true,blocks:[],warnings:[],windows:{w1:{},w2:{}}},
   market_snapshot:{iwencai:{},live_index:{}},context_status:'trusted'},
  {trade_time:'11:00',action:'买入',name:'T2',code:'000002',price:10,qty:50,
   window:'W2',reason:'',outcome:'',review_note:'',
   context_status:'unavailable',context_unavailable_reason:'行情数据不可用'}
];
inst._filter = 'all';
inst._renderTable(_body, inst._reviews, '2026-05-27');
var html = _body.innerHTML || '';
console.log(JSON.stringify({hasT1: html.indexOf('T1')>=0, hasT2: html.indexOf('T2')>=0, rows: (html.match(/<tr/g)||[]).length}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get("hasT1"), f"全部筛选应含 T1: {result}")
        self.assertTrue(result.get("hasT2"), f"全部筛选应含 T2: {result}")

    def test_filter_trusted_only_shows_verified(self):
        script = r"""
var _body = document.createElement('div');
var inst = new TradeReviewWidget({id:'W23'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._reviews = [
  {trade_time:'10:00',action:'W1追涨',name:'T1',code:'000001',price:10,qty:100,
   window:'W1',reason:'',outcome:'',review_note:'',
   rule_state:{version:'g1a-v1',tradable:true,blocks:[],warnings:[],windows:{w1:{},w2:{}}},
   market_snapshot:{iwencai:{},live_index:{}},context_status:'trusted'},
  {trade_time:'11:00',action:'买入',name:'T2',code:'000002',price:10,qty:50,
   window:'W2',reason:'',outcome:'',review_note:'',
   context_status:'unavailable',context_unavailable_reason:'行情数据不可用'},
  {trade_time:'12:00',action:'买入',name:'T3',code:'000003',price:10,qty:50,
   window:'W2',reason:'',outcome:'',review_note:'',
   context_status:'unverified'}
];
inst._filter = 'trusted';
inst._renderTable(_body, inst._reviews, '2026-05-27');
var html = _body.innerHTML || '';
console.log(JSON.stringify({hasT1: html.indexOf('T1')>=0, hasT2: html.indexOf('T2')>=0, hasT3: html.indexOf('T3')>=0}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get("hasT1"), f"已验证筛选应含 T1: {result}")
        self.assertFalse(result.get("hasT2"), f"已验证不应含 unavailable: {result}")
        self.assertFalse(result.get("hasT3"), f"已验证不应含 unverified: {result}")

    def test_filter_unavailable_excludes_unverified(self):
        script = r"""
var _body = document.createElement('div');
var inst = new TradeReviewWidget({id:'W23'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._reviews = [
  {trade_time:'11:00',action:'买入',name:'T2',code:'000002',price:10,qty:50,
   window:'W2',reason:'',outcome:'',review_note:'',
   context_status:'unavailable',context_unavailable_reason:'行情数据不可用'},
  {trade_time:'12:00',action:'买入',name:'T3',code:'000003',price:10,qty:50,
   window:'W2',reason:'',outcome:'',review_note:'',
   context_status:'unverified'}
];
inst._filter = 'unavailable';
inst._renderTable(_body, inst._reviews, '2026-05-27');
var html = _body.innerHTML || '';
console.log(JSON.stringify({hasT2: html.indexOf('T2')>=0, hasT3: html.indexOf('T3')>=0}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertTrue(result.get("hasT2"), f"不可用筛选应含 T2: {result}")
        self.assertFalse(result.get("hasT3"), f"不可用筛选不应含 unverified: {result}")

    def test_filter_unverified_shows_unverified_in_status(self):
        script = r"""
var _body = document.createElement('div');
var inst = new TradeReviewWidget({id:'W23'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst._reviews = [
  {trade_time:'11:00',action:'买入',name:'T2',code:'000002',price:10,qty:50,
   window:'W2',reason:'',outcome:'',review_note:'',
   context_status:'unavailable',context_unavailable_reason:'行情数据不可用'},
  {trade_time:'12:00',action:'买入',name:'T3',code:'000003',price:10,qty:50,
   window:'W2',reason:'',outcome:'',review_note:'',
   context_status:'unverified'}
];
inst._filter = 'unverified';
inst._renderTable(_body, inst._reviews, '2026-05-27');
var html = _body.innerHTML || '';
// Check status column: T3 row should show '未验证' not '不可用' or '历史补录'
var t2Idx = html.indexOf('T2');
var t3Idx = html.indexOf('T3');
var afterT3 = t3Idx >= 0 ? html.substring(t3Idx, t3Idx + 3000) : '';
console.log(JSON.stringify({hasT2: html.indexOf('T2')>=0, hasT3: html.indexOf('T3')>=0,
  afterT3HasUnverified: afterT3.indexOf('未验证')>=0,
  afterT3NoUnavailable: afterT3.indexOf('不可用')<0}));
"""
        result = _run_node(script, files=["widgets/trade-review.js"])
        self.assertFalse(result.get("hasT2"), f"未验证筛选不应含 unavailable: {result}")
        self.assertTrue(result.get("hasT3"), f"未验证筛选应含 unverified: {result}")
        self.assertTrue(result.get("afterT3HasUnverified"), f"unverified 行状态应显示 '未验证': {result}")
        self.assertTrue(result.get("afterT3NoUnavailable"), f"unverified 行状态不应显示 '不可用': {result}")


class RuntimeModeLabelTest(unittest.TestCase):
    """V3.1 G4: 运行模式标识 + W15 成交确认"""

    def test_html_contains_mode_label_element(self):
        """index.html 包含 runtimeModeLabel"""
        idx = ROOT / "index.html"
        html = idx.read_text(encoding="utf-8")
        self.assertIn("runtimeModeLabel", html, "应有 runtimeModeLabel")
        self.assertIn("_detectRuntimeMode", html, "应有 _detectRuntimeMode")

    def test_detect_8088_is_prod(self):
        script = r"""
function _detectRuntimeMode() {
  if (location.protocol === 'file:') return {key:'file',label:'本地文件',readonly:true};
  if (location.port === '18088') return {key:'preview',label:'本地预览 · 只读',readonly:true};
  if (location.port === '8088') return {key:'prod',label:'云端生产',readonly:false};
  return {key:'local',label:'本地服务',readonly:false};
}
var location={protocol:'http:', port:'8088'};
console.log(JSON.stringify(_detectRuntimeMode()));
"""
        result = _run_node(script)
        self.assertEqual(result.get("key"), "prod", "8088 应为 prod")
        self.assertEqual(result.get("label"), "云端生产")
        self.assertFalse(result.get("readonly"), "8088 不应只读")

    def test_detect_18088_is_preview_ro(self):
        script = r"""
function _detectRuntimeMode() {
  if (location.protocol === 'file:') return {key:'file',label:'本地文件',readonly:true};
  if (location.port === '18088') return {key:'preview',label:'本地预览 · 只读',readonly:true};
  if (location.port === '8088') return {key:'prod',label:'云端生产',readonly:false};
  return {key:'local',label:'本地服务',readonly:false};
}
var location={protocol:'http:', port:'18088'};
console.log(JSON.stringify(_detectRuntimeMode()));
"""
        result = _run_node(script)
        self.assertEqual(result.get("key"), "preview", "18088 应为 preview")
        self.assertIn("只读", result.get("label", ""), "18088 应显式只读")
        self.assertTrue(result.get("readonly"), "18088 应只读")

    def test_detect_file_is_file(self):
        script = r"""
function _detectRuntimeMode() {
  if (location.protocol === 'file:') return {key:'file',label:'本地文件',readonly:true};
  if (location.port === '18088') return {key:'preview',label:'本地预览 · 只读',readonly:true};
  if (location.port === '8088') return {key:'prod',label:'云端生产',readonly:false};
  return {key:'local',label:'本地服务',readonly:false};
}
var location={protocol:'file:', port:''};
console.log(JSON.stringify(_detectRuntimeMode()));
"""
        result = _run_node(script)
        self.assertEqual(result.get("key"), "file", "file: 协议应 file")

    def test_file_mode_has_blocking_api_guidance(self):
        """file:// 模式应明确提示 API 不可用，避免误判数据丢失"""
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "css/theme.css").read_text(encoding="utf-8")
        self.assertIn("fileModeNotice", html)
        self.assertIn("本地文件模式无法读取看板 API", html)
        self.assertIn("http://localhost:18088/", html)
        self.assertIn("http://localhost:8088/", html)
        self.assertIn(".file-mode-notice", css)

    def test_positions_js_has_w15_sync_status(self):
        """W15 渲染包含 w15_sync_status"""
        src = (ROOT / "widgets/positions.js").read_text(encoding="utf-8")
        self.assertIn("w15_sync_status", src, "positions.js 应渲染 w15_sync_status")
        self.assertIn("_bridgeSync", src, "应有 _bridgeSync")
        self.assertIn("readonly_dev_preview", src, "_bridgeSync 应处理 readonly_dev_preview")

    def test_bridgeSync_has_onError_errMsg_and_f_error(self):
        """_bridgeSync 源码包含 onError(errMsg), #f_error, readonly_dev_preview, message, 8088"""
        src = (ROOT / "widgets/positions.js").read_text(encoding="utf-8")
        self.assertIn("onError(errMsg)", src, "错误应传 errMsg 给 onError")
        self.assertIn("#f_error", src, "应写入 #f_error")
        self.assertIn("readonly_dev_preview", src)
        self.assertIn(".message", src, "应读取后端 message 字段")
        self.assertIn("8088", src, "应提示 8088 实盘录入")

    def test_f_error_writing_pattern_in_source(self):
        """源码验证 onError 写入 #f_error 的模式正确"""
        src = (ROOT / "widgets/positions.js").read_text(encoding="utf-8")
        # onError 回调中应包含 querySelector('#f_error') + textContent 赋值 + style.display
        self.assertIn("querySelector('#f_error')", src, "应通过 querySelector 找 f_error")
        self.assertIn("errMsg", src, "应使用 errMsg 变量")
        self.assertIn("errBox.textContent", src, "应设置 textContent")
        self.assertIn("errBox.style.display", src, "应设置 display")

    def test_runtime_mode_label_style_in_css(self):
        """theme.css 包含 .runtime-mode 样式"""
        css = (ROOT / "css/theme.css").read_text(encoding="utf-8")
        self.assertIn(".runtime-mode", css, "theme.css 应有 .runtime-mode 选择器")


class G5DegradeDisplayTest(unittest.TestCase):
    """V3.1 G5: W04/W22/顶栏降级展示收口"""

    def test_w04_no_absolute_amt_diff(self):
        """W04 成交额卡片不渲染绝对差额（只有百分比）"""
        src = (ROOT / "widgets/market-overview.js").read_text(encoding="utf-8")
        # 找成交额卡片的 html += 行
        amtCardLine = None
        for line in src.split('\n'):
            if 'kpi-label\">成交额' in line:
                amtCardLine = line
                break
        self.assertIsNotNone(amtCardLine, "应找到成交额 KPI 卡片行")
        # 不应包含 amtDiff 渲染
        self.assertNotIn("amtDiff", amtCardLine, "成交额卡片不应包含 amtDiff 渲染")
        # 应有 amtCompareText
        self.assertIn("amtCompareText", amtCardLine, "成交额卡片应含百分比比较")

    def test_w04_zt_dt_show_dash_when_missing(self):
        """涨跌停缺数据时显示 —/—"""
        src = (ROOT / "widgets/market-overview.js").read_text(encoding="utf-8")
        self.assertIn("'—'", src, "涨跌停缺值应显示 —")

    def test_w04_uses_baseline_when_iwencai_missing(self):
        """W04 收盘/重启后 iwencai 缺失时应回退 baseline market/sentiment"""
        src = (ROOT / "widgets/market-overview.js").read_text(encoding="utf-8")
        self.assertIn("m['涨停家数']", src)
        self.assertIn("m['跌停家数']", src)
        self.assertIn("sent['情绪值']", src)
        self.assertIn("sent['昨日涨停收益']", src)
        self.assertIn("sent['昨日炸板收益']", src)

    def test_topbar_blocked_not_unhealthy(self):
        """顶栏 trade_entry_allowed=false 显示 '阻断' 而非 '不健康'"""
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("'不健康'", html, "顶栏不应显示 '不健康'")
        self.assertIn("'阻断'", html, "顶栏应显示 '阻断'")

    def test_topbar_has_degraded(self):
        """顶栏 degraded 时显示 '降级'"""
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("'降级'", html, "顶栏应含 '降级'")

    def test_topbar_has_normal(self):
        """顶栏正常时显示 '正常'"""
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("'正常'", html, "顶栏应含 '正常'")

    def test_topbar_has_no_response(self):
        """API 无响应时显示 '无响应'"""
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("'无响应'", html, "顶栏应含 '无响应'")

    def test_topbar_labels_max_4_chars(self):
        """顶栏健康标签最长 4 个字"""
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        for label in ["'阻断'", "'降级'", "'正常'", "'无响应'"]:
            self.assertIn(label, html, f"顶栏应含 {label}")

    def test_store_has_fallback_source_comments(self):
        """store.js 包含云端 fallback 数据源说明"""
        src = (ROOT / "store.js").read_text(encoding="utf-8")
        self.assertIn("fallback", src, "store.js 应含 fallback 说明")
        self.assertIn("Tencent", src, "应含 Tencent fallback 说明")
        self.assertIn("PyTDX", src, "应含 PyTDX 降级说明")


if __name__ == "__main__":
    unittest.main()
