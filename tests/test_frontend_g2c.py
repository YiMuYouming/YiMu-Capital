"""test_frontend_g2c.py — health + prefill + z-index (Gate 2C R7)"""
import json, os, re, subprocess, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Extract production inline JS from index.html
_IDX = (ROOT / "index.html").read_text()
assert _IDX.startswith("<!DOCTYPE html>"), "index.html must start with DOCTYPE"
_m = re.search(r'<script>\s*\n(.*?)</script>', _IDX, re.DOTALL)
_PROD_SCRIPT = _m.group(1) if _m else ""
assert _PROD_SCRIPT, "failed to extract inline script"
assert _PROD_SCRIPT.count("function _updateHealth()") == 1, "only one _updateHealth"

# Syntax check
with open("/tmp/_prod_idx.js", "w") as f:
    f.write(_PROD_SCRIPT)
r = subprocess.run(["node", "--check", "/tmp/_prod_idx.js"], capture_output=True, text=True)
assert r.returncode == 0, f"syntax error: {r.stderr[:200]}"

# Extract functions
def _extract_func(text, name):
    i = text.find("function " + name + "(")
    if i < 0: return ""
    depth = 0; started = False; end = 0
    for j, c in enumerate(text[i:]):
        if c == '{': depth += 1; started = True
        elif c == '}':
            depth -= 1
            if started and depth == 0: end = j + 1; break
    return text[i:i+end]

_PROD_PREFILL_FN = _extract_func(_PROD_SCRIPT, "_prefillW15")

PREAMBLE = r"""
(function() {
  global._elMap = {};
  function _m(id) { return { id:id||'', innerHTML:'', style:{}, textContent:'', className:'',
    classList:{contains:function(){return false},add:function(){},toggle:function(){},remove:function(c){}},
    getAttribute:function(a){return a==='gs-id'?this._gsId:null}, setAttribute:function(){},
    querySelector:function(s){return global._elMap[s]||_m(s)},
    querySelectorAll:function(){return[]}, addEventListener:function(){}, removeEventListener:function(){},
    closest:function(s){return this._gsId?{getAttribute:function(){return this._gsId}}:null},
    scrollIntoView:function(){}, value:'', options:[{value:'W1',selected:false},{value:'W2',selected:false}]
  };}
  var doc = {
    createElement:function(){return _m('');},
    querySelector:function(sel){return global._elMap[sel]||_m(sel);},
    querySelectorAll:function(){return[];},
    getElementById:function(id){return global._elMap['#'+id]||(global._elMap['#'+id]=_m(id));},
    body:_m('body'),
  };
  doc.body.classList={contains:function(){return false},add:function(){},toggle:function(){}};
  doc.body.closest=function(){return null;};
  doc.body._appended = [];
  doc.body.appendChild = function(el) { doc.body._appended.push(el); };
  global.document=doc;
})();
global.window=global;
global.location={protocol:'http:'};
global.localStorage={_store:{},getItem:function(k){return this._store[k]||null},
  setItem:function(k,v){this._store[k]=String(v)},removeItem:function(k){delete this._store[k]}};
global._fetchCalls=[];
global.fetch = function(url, opts) {
  global._fetchCalls.push({url:typeof url==='string'?url:(url.url||''), opts:opts});
  return Promise.resolve({ok:true, json:function(){return Promise.resolve(
    {status:'healthy',bridge:{status:'ok'},db:{status:'ok'},quotes:{status:'live'},
     account:{status:'ok'},pnl:{status:'ok'},iwencai:{status:'live'},auction:{status:'ok'}
  });}});
};
global.Promise=Promise;
global.setTimeout=function(fn,ms){fn();};
global.setInterval=function(){return 0;};
global.EventSource=function(){this.readyState=0;};
EventSource.CONNECTING=0;EventSource.OPEN=1;EventSource.CLOSED=2;
global.DataStore = {
  merged:{}, _prefill:null,
  get:function(p){var ps=p.split('.');var v=this.merged;for(var i=0;i<ps.length;i++){if(v==null)return;v=v[ps[i]];}return v;},
  getInitialBase:function(){return null;},
  subscribe:function(){return function(){};},
  merge:function(){}, notifyAll:function(){},
  manualData:{getAll:function(){return{};},set:function(){},load:function(){}},
  onConnChange:function(){}, init:function(){}, fetchAll:function(){},
  tiers:{tick:{interval:5000}}
};
global.widgetInstances = {};
global._addWidgetToGrid = function(id){widgetInstances[id]={id:id};};
global.showToast = function(){};
global.STORAGE_KEYS = {inputs:'dash_inputs',layout:'dash_layout_v2'};
global.YiMuWidget = function(){};
YiMuWidget.prototype.getBody = function(){return document.createElement('div');};
YiMuWidget.prototype.updateTimestamp = function(){};
YiMuWidget.prototype._on = function(el,ev,fn){
  if(!this._domListeners)this._domListeners=[];
  this._domListeners.push({el:el,event:ev,fn:fn});
};
YiMuWidget.prototype.unmount = function(){this._domListeners=[];};
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


class DOCTYPETest(unittest.TestCase):
    def test_html_starts_with_doctype(self):
        self.assertTrue((ROOT / "index.html").read_text().startswith("<!DOCTYPE html>"))

    def test_single_health_function(self):
        src = (ROOT / "index.html").read_text()
        self.assertEqual(src.count("function _updateHealth()"), 1,
                         "index.html 只应有一份 _updateHealth 实现")

    def test_inline_js_syntax_ok(self):
        r = subprocess.run(["node","--check","/tmp/_prod_idx.js"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, f"syntax error: {r.stderr[:200]}")

    def test_compact_button_uses_clear_core_copy(self):
        src = (ROOT / "index.html").read_text()
        self.assertIn('id="compactBtn"', src)
        self.assertIn('只看核心', src)
        self.assertIn('显示全部', src)
        self.assertNotIn('title="精简模式"', src)

    def test_topbar_uses_transparent_mark_logo(self):
        src = (ROOT / "index.html").read_text()
        logo = ROOT / "assets" / "logo-yi.png"
        self.assertTrue(logo.exists(), "顶栏应使用无黑底的弈 PNG 标识")
        self.assertIn('href="assets/logo-yi.png"', src)
        self.assertIn('src="assets/logo-yi.png"', src)
        self.assertIn('alt="弈"', src)
        self.assertNotIn('src="assets/logo.png"', src)


class HealthDegradeTest(unittest.TestCase):

    def test_health_critical_blocks_w08_entry(self):
        script = r"""
window._healthCritical = true; window._healthConfirmed = false;
var _body = document.createElement('div');
var inst = new W1CheckWidget({id:'W08'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst.render({
  sentiment:{'情绪值':65,'昨日涨停收益':4},market:{},iwencai:{},live_index:{},live_quotes:{},
  lianban_pool:[{标的:'测试',代码:'000001',涨幅:'+5',窗口:'W1'}],
  trend_pool:[],sectors:[],
  rule_state:{version:'v1',tradable:true,windows:{w1:{in_session:true,buy_allowed:true},w2:{}},blocks:[],caps:{base_total_pct:50}}
});
console.log(JSON.stringify({hasBtn:_body.innerHTML.indexOf('录入')>=0}));
"""
        result = _run_node(script, files=["widgets/w1-check.js"])
        self.assertFalse(result.get("hasBtn"), "health critical 应无录入")

    def test_health_degrade_paths_exist(self):
        """HTTP 非 2xx / catch / null response 路径均存在"""
        self.assertIn("!r.ok", _PROD_SCRIPT, "缺 HTTP 非 2xx 路径")
        self.assertIn(".catch(function", _PROD_SCRIPT, "缺 fetch reject 路径")
        self.assertIn("if (!h)", _PROD_SCRIPT, "缺空响应路径")
        self.assertIn("DataStore.notifyAll", _PROD_SCRIPT, "缺 notifyAll")

    def test_close_snapshot_has_topbar_connection_mapping(self):
        """健康接口 quotes.status=close_snapshot 时顶栏应显示收盘快照"""
        self.assertIn("close_snapshot", _PROD_SCRIPT, "缺收盘快照连接状态映射")
        self.assertIn("收盘快照", _PROD_SCRIPT, "顶栏应显示收盘快照文案")

    def test_health_degrade_sets_critical_confirmed(self):
        """所有降级路径统一清除 confirmed + 设置 critical"""
        degrade_blocks = _PROD_SCRIPT.split("_healthCritical = true")
        self.assertGreaterEqual(len(degrade_blocks), 3, "至少 3 处降级路径设 critical=true")
        for block in degrade_blocks[1:]:
            self.assertIn("_healthConfirmed = false", block[:200],
                          "降级路径需同时设 confirmed=false")


class PrefillTest(unittest.TestCase):


    def test_prefill_opens_real_modal(self):
        """生产 _prefillW15 → modal append + code/name 字段 + 零写 + 生产代码含 prefills"""
        script = _PROD_PREFILL_FN + r"""
global._fetchCalls = [];
window._healthConfirmed = true;
window._healthCritical = false;
window._tradeEntryAllowed = true;
DataStore._prefill = null;
DataStore.merged = { pnl_live: { positions: [{标的:'测试标的',代码:'000001',数量:100,成本:10,现价:12,状态:'持有'}],
    total_asset: 100000, cash: 90000, mv: 1000 }, positions: [] };
var inst = new PositionsWidget({id:'W15'});
inst.getBody = function() { return document.createElement('div'); };
inst.updateTimestamp = function() {};
inst.render(DataStore.merged);
widgetInstances['W15'] = inst;
_prefillW15('测试标的','000001','W1','MA10回踩');
var appended = document.body._appended || [];
var modal = appended.length > 0 ? appended[appended.length-1] : null;
var inner = modal ? (modal.innerHTML || '') : '';
var pf = DataStore._prefill;
console.log(JSON.stringify({
  hasModal: !!modal,
  codeOk: inner.indexOf('000001') >= 0,
  nameOk: inner.indexOf('测试标的') >= 0,
  innerLen: inner.length,
  prefillSet: !!(pf && pf.code && pf.window === 'W1' && pf.evidence && pf.evidence.indexOf('MA10') >= 0),
  hasSync: global._fetchCalls.some(function(c){return(c.url||'').indexOf('/api/sync')>=0}),
  fetchCalls: global._fetchCalls.length
}));
"""
        result = _run_node(script, files=["widgets/positions.js"])
        self.assertTrue(result.get("hasModal"), f"应 append modal: {result}")
        self.assertTrue(result.get("codeOk"), f"modal 含代码 000001: {result}")
        self.assertTrue(result.get("nameOk"), f"modal 含标的名称: {result}")
        self.assertTrue(result.get("prefillSet"), f"prefill 4 字段完整: {result}")
        self.assertGreater(result.get("innerLen", 0), 100, f"modal 应有完整表单内容: {result}")
        self.assertFalse(result.get("hasSync"), "sync call")
        self.assertEqual(result.get("fetchCalls"), 0, f"fetch: {result}")

    def test_prefill_production_code_has_all_fields(self):
        """生产代码: _prefillW15 calls _showForm; positions.js reads DataStore._prefill"""
        src_idx = (ROOT / "index.html").read_text()
        src_pos = (ROOT / "widgets" / "positions.js").read_text()
        self.assertIn("_showForm(active)", src_idx, "_prefillW15 应调用 _showForm")
        self.assertIn("DataStore._prefill", src_pos, "_showForm 应读 DataStore._prefill")
        # Check prefill fields in positions.js
        for field in ["pf.code", "pf.name", "pf.window", "pf.evidence"]:
            self.assertIn(field, src_pos, f"positions.js 预填应含 {field}")

    def test_showform_reads_prefill(self):
        """positions.js _showForm 从 DataStore._prefill 读取预填"""
        src = (ROOT / "widgets" / "positions.js").read_text()
        self.assertIn("DataStore._prefill", src, "_showForm 应读取 DataStore._prefill")
        self.assertIn("pf.code", src)
        self.assertIn("pf.name", src)
        self.assertIn("pf.window", src)


class ZIndexTest(unittest.TestCase):

    def test_no_numeric_z_over_100(self):
        for fp in list(ROOT.glob("widgets/*.js")) + ["css/theme.css", "index.html"]:
            src = (ROOT / fp).read_text() if isinstance(fp, str) else fp.read_text()
            fn = fp if isinstance(fp, str) else fp.name
            for m in re.finditer(r'z-index:\s*(\d+)', src):
                val = int(m.group(1))
                self.assertLess(val, 100, f"{fn} z-index:{val} 应改用 CSS 变量")


class W14StopLossTest(unittest.TestCase):

    def test_ssot_sl_99_price_98_must_alert(self):
        script = r"""
var _body = document.createElement('div');
var inst = new RiskPanelWidget({id:'W14'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst.render({risk:{},live_quotes:{},
  pnl_live:{total_asset:100000,cash:90000,mv:1000,
    positions:[{标的:'测试',代码:'000001',数量:100,成本:100,止损:99,现价:98}], valuation_complete:true}
});
console.log(JSON.stringify({hasAlert:_body.innerHTML.indexOf('sl-alert')>=0}));
"""
        result = _run_node(script, files=["widgets/risk-panel.js"])
        self.assertTrue(result.get("hasAlert"), f"止损99现价98应报警: {result}")

    def test_sl_80_price_92_no_false_alert(self):
        script = r"""
var _body = document.createElement('div');
var inst = new RiskPanelWidget({id:'W14'});
inst.getBody = function(){return _body;};
inst.updateTimestamp = function(){};
inst.render({risk:{},live_quotes:{},
  pnl_live:{total_asset:100000,cash:90000,mv:1000,
    positions:[{标的:'安全',代码:'000002',数量:100,成本:100,止损:80,现价:92}], valuation_complete:true}
});
console.log(JSON.stringify({hasAlert:_body.innerHTML.indexOf('sl-alert')>=0}));
"""
        result = _run_node(script, files=["widgets/risk-panel.js"])
        self.assertFalse(result.get("hasAlert"), f"止损80现价92不应报警: {result}")


if __name__ == "__main__":
    unittest.main()
