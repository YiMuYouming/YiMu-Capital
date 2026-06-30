"""test_frontend_w22.py — W22 行为测试：不可信/回退 _updateKPI + _drawChart 不崩溃"""
import json, os, subprocess, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PREAMBLE = r"""
if (typeof document === 'undefined') {
  global.document = (function() {
    var els = {};
    var parentMock = { querySelector:function(sel){return els[sel]||null;}, querySelectorAll:function(){return[];} };
    function makeEl(id) {
      var self = { innerHTML:'', textContent:'', style:{}, className:'', id:id||'',
        parentElement: parentMock,
        classList:{contains:function(){return false},add:function(){},toggle:function(){},remove:function(c){}},
        getAttribute:function(){return null}, setAttribute:function(){},
        querySelector:function(sel){return els[sel]||null;},
        querySelectorAll:function(){return[];},
        addEventListener:function(){}, removeEventListener:function(){}, closest:function(){return null},
        getBoundingClientRect:function(){return {left:0,top:0,width:800,height:300};},
        getContext:function(ty) {
          return { beginPath:function(){}, moveTo:function(){}, lineTo:function(){},
            stroke:function(){}, fill:function(){}, fillText:function(){}, fillRect:function(){},
            setLineDash:function(){}, arc:function(){}, restore:function(){}, save:function(){}, closePath:function(){},
            measureText:function(){return {width:50};}, strokeText:function(){},
            clearRect:function(){}, translate:function(){}, scale:function(){},
            createLinearGradient:function(){return {addColorStop:function(){}};},
            setTransform:function(){}, canvas:{width:800,height:300} };
        },
      };
      if (id) els[id] = self;
      return self;
    }
    function getById(id) { return els[id] || makeEl(id); }
    return {
      createElement:function(t){var e=makeEl();e.tagName=t;return e;},
      querySelector:function(){return null;}, querySelectorAll:function(){return[];},
      getElementById:getById, body:makeEl()
    };
  })();
}
var _SyncPromise = function(executor) {
  var self = this;
  this._resolved = false; this._value = null;
  this._fulfillQueue = [];
  executor(function(v) { self._resolve(v); }, function(e) { self._reject(e); });
};
_SyncPromise.prototype._resolve = function(v) {
  if (this._resolved) return;
  this._resolved = true; this._value = v;
  for (var i = 0; i < this._fulfillQueue.length; i++) {
    try { var r = this._fulfillQueue[i](v); if (this._chain) this._chain._resolve(r); } catch(e) { if (this._chain) this._chain._reject(e); }
  }
  this._fulfillQueue = [];
};
_SyncPromise.prototype._reject = function(e) {
  if (this._rejected || this._resolved) return;
  this._rejected = true; this._value = e;
  for (var i = 0; i < this._rejectQueue.length; i++) {
    try { this._rejectQueue[i](e); } catch(e2) {}
  }
};
_SyncPromise.prototype.then = function(onFulfilled, onRejected) {
  if (this._resolved && onFulfilled) { try { var r = onFulfilled(this._value); return _SyncPromise.resolve(r); } catch(e) { return _SyncPromise.reject(e); } }
  if (this._rejected && onRejected) { try { var r2 = onRejected(this._value); return _SyncPromise.resolve(r2); } catch(e) { return _SyncPromise.reject(e); } }
  if (this._rejected) return this;
  if (onFulfilled) this._fulfillQueue.push(onFulfilled);
  if (onRejected) (this._rejectQueue||[]).push(onRejected);
  var chain = new _SyncPromise(function(){}); this._chain = chain; return chain;
};
_SyncPromise.prototype.catch = function(onRejected) { return this.then(null, onRejected); };
_SyncPromise.resolve = function(v) { return new _SyncPromise(function(res) { res(v); }); };
_SyncPromise.reject = function(e) { return new _SyncPromise(function(_, rej) { rej(e); }); };
global.Promise = _SyncPromise;
global.fetch = function(url, opts) { return _SyncPromise.resolve({ ok:true, status:200, json:function(){return _SyncPromise.resolve({});} }); };
global.setTimeout = function(fn,ms){fn();};
global.setInterval = function(){return 0;};
global.YiMuWidget = function(){};
YiMuWidget.prototype.getBody = function(){return document.createElement('div');};
YiMuWidget.prototype.updateTimestamp = function(){};
YiMuWidget.prototype._renderBody = function(){this.render({});};
YiMuWidget.prototype._on = function(el,ev,fn){};
YiMuWidget.prototype.unmount = function(){};
global.WidgetRegistry = { _map:{}, register:function(id,cls){this._map[id]=cls;}, getClass:function(id){return this._map[id];}, getMeta:function(){return{tier:'manual',dataPaths:[]};} };
global.DataStore = { _prefill:null, merged:{}, manualData:{getAll:function(){return{};}} };
global.window = global;
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


class W22UpdateKpiBehaviorTests(unittest.TestCase):
    """_updateKPI 行为测试：不可信 & 回退 实际调用验证"""

    def test_w22_labels_index_as_reference_not_strict_benchmark(self):
        src = (ROOT / "widgets" / "pnl-curve.js").read_text()
        self.assertIn("指数参考", src)
        self.assertIn("相对指数", src)
        self.assertNotIn("累计超额 α", src)
        self.assertNotIn("TWR−基准", src)

    def _run_kpi_test(self, state_overrides, chartData_overrides=None):
        script = r"""
var inst = new PnLCurveWidget({id:'W22'});
inst.id = 'W22';
inst._allDailyData = null;
var state = {
  period:'today', index:'sh', totalAsset:200000, totalDeposit:200000,
  liveQ:{}, positions:[], pnlLive:{}
};
""" + "Object.assign(state, " + json.dumps(state_overrides) + ");\n" + r"""
inst._state = state;
var cd = { type:'intraday', labels:['09:30','09:35'], portfolio:[0.5, 0.8], benchmark:[0.2, 0.3], position:[50.0, 50.0], nav:[1.0, 1.0] };
""" + ("Object.assign(cd, " + json.dumps(chartData_overrides) + ");" if chartData_overrides else "") + r"""
try {
  inst._updateKPI(cd);
  var periodVal = document.getElementById('pnl_period_val');
  var periodSub = document.getElementById('pnl_period_sub');
  var ddVal = document.getElementById('pnl_dd_val');
  var alphaEl = document.getElementById('pnl_today_alpha');
  var alphaSub = document.getElementById('pnl_today_alpha_sub');
  console.log(JSON.stringify({
    asset: document.getElementById('pnl_asset').textContent,
    assetSub: document.getElementById('pnl_asset_sub').textContent,
    pnl: document.getElementById('pnl_pnl').textContent,
    pnlSub: document.getElementById('pnl_pnl_sub').textContent,
    pos: document.getElementById('pnl_pos').textContent,
    periodVal: periodVal ? periodVal.textContent : '',
    periodSub: periodSub ? periodSub.textContent : '',
    ddVal: ddVal ? ddVal.textContent : '',
    alpha: alphaEl ? alphaEl.textContent : '',
    alphaSub: alphaSub ? alphaSub.textContent : '',
    ok:true
  }));
} catch(e) {
  console.log(JSON.stringify({ok:false, err: e.message}));
}
"""
        return _run_node(script, files=["widgets/pnl-curve.js"])

    def test_valuation_incomplete_shows_unavailable(self):
        """valuation_complete=false → 实时估值字段不可用，总资产快照仍展示"""
        result = self._run_kpi_test(
            {"pnlLive": {"valuation_complete": False, "anchor_blocked": False}})
        self.assertTrue(result.get("ok"), f"不应崩溃: {result}")
        self.assertNotEqual(result.get("asset"), "—")
        self.assertIn("非实时", result.get("assetSub", ""))
        self.assertEqual(result.get("pnl"), "—")
        self.assertIn("不可信", result.get("pnlSub", ""))
        self.assertEqual(result.get("pos"), "—")
        # 今日 TWR / 回撤 / 超额 不可用
        self.assertEqual(result.get("periodVal"), "—",
            f"valuationBad 时 periodVal 应为'—': {result}")
        self.assertIn("不可信", result.get("periodSub", ""),
            f"periodSub 应标注不可信: {result}")
        self.assertEqual(result.get("ddVal"), "—",
            f"valuationBad 时 ddVal 应为'—': {result}")
        self.assertEqual(result.get("alpha"), "—",
            f"valuationBad 时 alpha 应为'—': {result}")

    def test_valuation_incomplete_does_not_clear_historical_kpis(self):
        """valuation_complete=false 不应清空历史累计 TWR/相对指数"""
        script = r"""
var inst = new PnLCurveWidget({id:'W22'});
inst.id = 'W22';
inst._state = {
  period:'today', index:'sh', totalAsset:200000, totalDeposit:200000,
  liveQ:{}, positions:[], pnlLive:{valuation_complete:false}
};
document.getElementById('pnl_twr').textContent = '+2.78%';
document.getElementById('pnl_alpha').textContent = '+3.33%';
inst._updateKPI({ type:'intraday', labels:['09:30','09:35'], portfolio:[0.5, 0.8], benchmark:[0.2, 0.3], position:[50.0, 50.0] });
console.log(JSON.stringify({
  twr: document.getElementById('pnl_twr').textContent,
  alpha: document.getElementById('pnl_alpha').textContent
}));
"""
        result = _run_node(script, files=["widgets/pnl-curve.js"])
        self.assertEqual(result.get("twr"), "+2.78%", f"历史 TWR 不应被实时估值分支清空: {result}")
        self.assertEqual(result.get("alpha"), "+3.33%", f"历史相对指数不应被实时估值分支清空: {result}")

    def test_fallback_shows_date_not_realtime(self):
        """is_fallback=true → 显示 data_date + 回退，无'实时收益'"""
        result = self._run_kpi_test(
            {"pnlLive": {"valuation_complete": True}},
            {"is_fallback": True, "data_date": "2026-05-26"})
        self.assertTrue(result.get("ok"), f"不应崩溃: {result}")
        self.assertIn("2026-05-26", result.get("assetSub", ""))
        self.assertIn("非今日实时", result.get("assetSub", ""))
        self.assertIn("2026-05-26", result.get("periodSub", ""),
            f"periodSub 应含回退日期: {result}")
        self.assertIn("回退", result.get("periodSub", ""),
            f"periodSub 应标注回退: {result}")
        self.assertNotIn("实时收益", result.get("periodSub", ""),
            f"fallback 不得显示'实时收益': {result}")
        self.assertIn("2026-05-26", result.get("alphaSub", ""),
            f"alphaSub 应含回退日期: {result}")

    def test_normal_live_shows_values(self):
        """正常状态显示实际数值 + '实时收益'"""
        result = self._run_kpi_test(
            {"pnlLive": {"valuation_complete": True, "pnl_amount": 500, "pnl_pct": 0.25, "pos_pct": 50, "mv": 100000}})
        self.assertTrue(result.get("ok"), f"不应崩溃: {result}")
        self.assertNotEqual(result.get("asset"), "—")
        self.assertIn("实时收益", result.get("periodSub", ""),
            f"正常应显示'实时收益': {result}")

    def test_period_switch_updates_primary_return_and_average_position_kpis(self):
        """周/月切换后，前两个动态 KPI 展示周期收益与平均仓位"""
        script = r"""
var inst = new PnLCurveWidget({id:'W22'});
inst.id = 'W22';
inst._state = {
  period:'week', index:'sh', totalAsset:200000, totalDeposit:200000,
  liveQ:{}, positions:[], pnlLive:{valuation_complete:true, pnl_amount:100, pnl_pct:0.1, pos_pct:80}
};
inst._updateKPI({
  type:'daily',
  labels:['06-15','06-16','06-17'],
  portfolio:[0.5, 1.25, 3.0],
  benchmark:[0.2, 0.4, 1.0],
  position:[20, 40, 60],
  nav:[1.0, 1.01, 1.03]
});
var week = {
  pnlLabel: document.getElementById('pnl_pnl_label').textContent,
  pnl: document.getElementById('pnl_pnl').textContent,
  pnlSub: document.getElementById('pnl_pnl_sub').textContent,
  posLabel: document.getElementById('pnl_pos_label').textContent,
  pos: document.getElementById('pnl_pos').textContent,
  posSub: document.getElementById('pnl_pos_sub').textContent
};
inst._state.period = 'month';
inst._updateKPI({
  type:'daily',
  labels:['06-01','06-10','06-19'],
  portfolio:[-1.0, 0.0, 2.5],
  benchmark:[-0.5, 0.1, 0.5],
  position:[10, null, 50],
  nav:[1.0, 1.0, 1.025]
});
var month = {
  pnlLabel: document.getElementById('pnl_pnl_label').textContent,
  pnl: document.getElementById('pnl_pnl').textContent,
  pnlSub: document.getElementById('pnl_pnl_sub').textContent,
  posLabel: document.getElementById('pnl_pos_label').textContent,
  pos: document.getElementById('pnl_pos').textContent,
  posSub: document.getElementById('pnl_pos_sub').textContent
};
console.log(JSON.stringify({week:week, month:month}));
"""
        result = _run_node(script, files=["widgets/pnl-curve.js"])
        self.assertEqual(result["week"]["pnlLabel"], "近一周收益", result)
        self.assertEqual(result["week"]["pnl"], "+3.00%", result)
        self.assertIn("TWR", result["week"]["pnlSub"], result)
        self.assertEqual(result["week"]["posLabel"], "近一周平均仓位", result)
        self.assertEqual(result["week"]["pos"], "40%", result)
        self.assertIn("3 个采样", result["week"]["posSub"], result)
        self.assertEqual(result["month"]["pnlLabel"], "近一月收益", result)
        self.assertEqual(result["month"]["pnl"], "+2.50%", result)
        self.assertEqual(result["month"]["posLabel"], "近一月平均仓位", result)
        self.assertEqual(result["month"]["pos"], "30%", result)
        self.assertIn("2 个采样", result["month"]["posSub"], result)

    def test_period_average_position_uses_only_valid_curve_samples(self):
        """周期平均仓位只按收益曲线有效点计数，曲线空点不进分母"""
        script = r"""
var inst = new PnLCurveWidget({id:'W22'});
inst.id = 'W22';
inst._state = {
  period:'week', index:'sh', totalAsset:200000, totalDeposit:200000,
  liveQ:{}, positions:[], pnlLive:{valuation_complete:true, pnl_amount:100, pnl_pct:0.1, pos_pct:80}
};
inst._updateKPI({
  type:'daily',
  labels:['06-15','06-16','06-17'],
  portfolio:[0.5, null, 3.0],
  benchmark:[0.2, null, 1.0],
  position:[10, 90, 30],
  nav:[1.0, null, 1.03]
});
console.log(JSON.stringify({
  pos: document.getElementById('pnl_pos').textContent,
  posSub: document.getElementById('pnl_pos_sub').textContent
}));
"""
        result = _run_node(script, files=["widgets/pnl-curve.js"])
        self.assertEqual(result.get("pos"), "20%", result)
        self.assertIn("2 个采样", result.get("posSub", ""), result)

    def test_period_kpi_all_daily_fallback_compounds_daily_returns(self):
        """周期接口未返回时，用 all 日线缓存兜底并按 TWR 连乘"""
        script = r"""
var inst = new PnLCurveWidget({id:'W22'});
inst.id = 'W22';
inst._state = {
  period:'week', index:'sh', totalAsset:200000, totalDeposit:200000,
  liveQ:{}, positions:[], pnlLive:{valuation_complete:true}
};
inst._allDailyData = {
  portfolio:[1.0, 2.0, -1.0],
  benchmark:[0.0, 0.0, 0.0],
  position:[10, 30, 50],
  dates:['2026-06-17','2026-06-18','2026-06-19']
};
inst._updateKPI(null);
console.log(JSON.stringify({
  pnlLabel: document.getElementById('pnl_pnl_label').textContent,
  pnl: document.getElementById('pnl_pnl').textContent,
  pos: document.getElementById('pnl_pos').textContent
}));
"""
        result = _run_node(script, files=["widgets/pnl-curve.js"])
        self.assertEqual(result.get("pnlLabel"), "近一周收益", result)
        self.assertEqual(result.get("pnl"), "+1.99%", result)
        self.assertEqual(result.get("pos"), "30%", result)

    def test_period_kpi_prefers_chart_window_twr_over_all_daily_fallback(self):
        """月主图已是周期累计TWR时，KPI 不应被 all 缓存的兜底计算覆盖"""
        script = r"""
var inst = new PnLCurveWidget({id:'W22'});
inst.id = 'W22';
inst._state = {
  period:'month', index:'sh', totalAsset:200000, totalDeposit:200000,
  liveQ:{}, positions:[], pnlLive:{valuation_complete:true}
};
inst._allDailyData = {
  dates:['2026-05-26','2026-06-01','2026-06-24'],
  portfolio:[-0.33, -0.10, 3.59],
  benchmark:[-0.17, -0.27, 0.05],
  position:[67, 0, 50]
};
inst._updateKPI({
  type:'daily',
  labels:['05-26','06-24'],
  dates:['2026-05-26','2026-06-24'],
  portfolio:[4.89, 2.94],
  benchmark:[-0.55, -0.33],
  position:[67, 50],
  nav:[1.04893, 1.029445]
});
console.log(JSON.stringify({
  periodVal: document.getElementById('pnl_period_val').textContent,
  periodSub: document.getElementById('pnl_period_sub').textContent,
  alpha: document.getElementById('pnl_today_alpha').textContent
}));
"""
        result = _run_node(script, files=["widgets/pnl-curve.js"])
        self.assertEqual(result.get("periodVal"), "+2.94%", result)
        self.assertIn("相对指数 +3.27%", result.get("periodSub", ""), result)
        self.assertEqual(result.get("alpha"), "+3.27%", result)

    def test_today_fallback_uses_last_trading_day_return_not_summary_zero(self):
        """非交易日 today fallback 时，主收益 KPI 显示最近交易日收益，不显示 summary 0"""
        script = r"""
var inst = new PnLCurveWidget({id:'W22'});
inst.id = 'W22';
inst._state = {
  period:'today', index:'sh', totalAsset:200000, totalDeposit:200000,
  liveQ:{}, positions:[], pnlLive:{valuation_complete:true, pnl_amount:0, pnl_pct:0, pos_pct:42}
};
inst._updateKPI({
  type:'intraday',
  data_date:'2026-06-19',
  is_fallback:true,
  labels:['09:30','14:55'],
  portfolio:[0.0, -0.73],
  benchmark:[0.0, -0.43],
  position:[42, 42],
  nav:[1.0, 0.9927]
});
console.log(JSON.stringify({
  pnlLabel: document.getElementById('pnl_pnl_label').textContent,
  pnl: document.getElementById('pnl_pnl').textContent,
  pnlSub: document.getElementById('pnl_pnl_sub').textContent,
  posLabel: document.getElementById('pnl_pos_label').textContent,
  pos: document.getElementById('pnl_pos').textContent
}));
"""
        result = _run_node(script, files=["widgets/pnl-curve.js"])
        self.assertEqual(result.get("pnlLabel"), "最近交易日收益", result)
        self.assertEqual(result.get("pnl"), "-0.73%", result)
        self.assertIn("2026-06-19", result.get("pnlSub", ""), result)
        self.assertEqual(result.get("posLabel"), "最近交易日仓位", result)
        self.assertEqual(result.get("pos"), "42%", result)

    def test_missing_day_start_price_shows_baseline_missing_not_zero(self):
        """_day_start_price=null 且无 SSOT 今日盈亏 → 今日盈亏不显示 0"""
        result = self._run_kpi_test({
            "liveQ": {"000001": {"最新价": 10, "涨幅": "1.0%"}},
            "positions": [{"状态": "持有", "代码": "000001", "数量": "100股", "_day_start_price": None, "today_pnl": None}],
            "pnlLive": {"valuation_complete": True}
        })
        self.assertTrue(result.get("ok"), f"不应崩溃: {result}")
        self.assertEqual(result.get("pnl"), "—", f"缺基线时今日盈亏 value 不应伪装为 0: {result}")
        self.assertIn("基线缺失", result.get("pnlSub", ""), f"缺基线时 sub 应明确说明: {result}")
        self.assertNotEqual(result.get("asset"), "—", f"缺分项基线不应影响总资产展示: {result}")

    def test_closed_missing_realized_shows_today_baseline_missing(self):
        """清仓 realized_today_pnl=null 且无 SSOT 今日盈亏 → 显示今日收益基线缺失"""
        result = self._run_kpi_test({
            "positions": [{"状态": "已清仓", "代码": "000001", "数量": "0股", "realized_today_pnl": None, "today_pnl": None}],
            "pnlLive": {"valuation_complete": True}
        })
        self.assertTrue(result.get("ok"), f"不应崩溃: {result}")
        self.assertEqual(result.get("pnl"), "—", f"清仓收益基线缺失时不应显示 0: {result}")
        self.assertIn("今日收益基线缺失", result.get("pnlSub", ""), f"清仓缺 realized 应明确说明: {result}")
        self.assertNotEqual(result.get("asset"), "—", f"缺清仓分项基线不应影响总资产展示: {result}")

    def test_close_snapshot_shows_values_with_label(self):
        """R3: quote_status=close_snapshot + valuation_complete=true → asset≠'—', 标注收盘"""
        result = self._run_kpi_test(
            {"pnlLive": {"valuation_complete": True, "quote_status": "close_snapshot",
                         "pnl_amount": 500, "pnl_pct": 0.25, "pos_pct": 50, "mv": 100000}})
        self.assertTrue(result.get("ok"), f"不应崩溃: {result}")
        self.assertNotEqual(result.get("asset"), "—",
            f"close_snapshot时asset应显示数值: {result}")
        self.assertIn("收盘", result.get("assetSub", ""),
            f"assetSub应标注收盘: {result}")
        self.assertIn("收盘", result.get("pnlSub", ""),
            f"P&L副标题应标注收盘: {result}")
        self.assertNotEqual(result.get("pnl"), "—",
            f"close_snapshot应显示P&L数值: {result}")
        self.assertNotEqual(result.get("pos"), "—",
            f"close_snapshot应显示仓位: {result}")

    def test_blocked_anchor_shows_unavailable(self):
        """anchor_blocked=true → 全部不可用"""
        result = self._run_kpi_test(
            {"pnlLive": {"anchor_blocked": True, "valuation_complete": False, "quote_status": "stale"}})
        self.assertTrue(result.get("ok"), f"不应崩溃: {result}")
        self.assertEqual(result.get("asset"), "—")
        self.assertIn("不可信", result.get("assetSub", ""))
        self.assertEqual(result.get("periodVal"), "—")
        self.assertEqual(result.get("ddVal"), "—")

    def test_render_respects_null_ssot_asset_over_baseline_pnl(self):
        """pnl_live.total_asset=null 时不得回退显示 baseline.pnl.总资产/累计入金"""
        script = r"""
var inst = new PnLCurveWidget({id:'W22'});
inst.id = 'W22';
inst.getBody = function(){ return document.createElement('div'); };
inst._layoutBuilt = true;
global.location = { protocol:'file:' };
inst.render({
  pnl:{'总资产':210477,'累计入金':'200000'},
  pnl_live:{
    total_asset:null,
    anchor_blocked:true,
    valuation_complete:false,
    quote_status:'missing'
  },
  live_quotes:{}
});
console.log(JSON.stringify({
  asset: document.getElementById('pnl_asset').textContent,
  assetSub: document.getElementById('pnl_asset_sub').textContent,
  totalAsset: inst._state.totalAsset,
  totalDeposit: inst._state.totalDeposit
}));
"""
        result = _run_node(script, files=["widgets/pnl-curve.js"])
        self.assertEqual(result.get("asset"), "—", f"SSOT null 不得显示旧资产: {result}")
        self.assertIn("锚点阻断", result.get("assetSub", ""), f"应说明锚点阻断: {result}")
        self.assertIsNone(result.get("totalAsset"), f"state.totalAsset 应保留 null: {result}")
        self.assertIsNone(result.get("totalDeposit"), f"state.totalDeposit 不应回退旧累计入金: {result}")


class W22DrawChartBehaviorTests(unittest.TestCase):
    """_drawChart 行为测试：null slot + 全零曲线 实际调用不崩溃"""

    def test_draw_chart_with_null_slots(self):
        script = r"""
var inst = new PnLCurveWidget({id:'W22_D1'});
inst.id = 'W22_D1';
inst._state = { period:'today', index:'sh', totalAsset:200000, totalDeposit:200000, liveQ:{}, positions:[], pnlLive:{} };
inst._lastChartData = {
  type:'intraday', labels:['09:30','09:35','09:40'],
  portfolio:[0.0, null, null], benchmark:[0.0, null, null],
  position:[50.0, null, null], nav:[1.0, null, null]
};
try {
  inst._drawChart(inst._lastChartData);
  console.log(JSON.stringify({ok:true}));
} catch(e) {
  console.log(JSON.stringify({ok:false, err: e.message.substring(0,100)}));
}
"""
        result = _run_node(script, files=["widgets/pnl-curve.js"])
        self.assertTrue(result.get("ok"), f"null slot draw 不应崩溃: {result}")

    def test_draw_chart_with_single_valid_sample_marks_points(self):
        script = r"""
var inst = new PnLCurveWidget({id:'W22_SINGLE'});
inst.id = 'W22_SINGLE';
inst._state = { period:'today', index:'sh', totalAsset:200000, totalDeposit:200000, liveQ:{}, positions:[], pnlLive:{} };
var calls = { arc:0, redStrokeLineTo:0, blueStrokeLineTo:0, emptyVisible:null, labels:[] };
var canvas = document.getElementById('pnl_canvas_W22_SINGLE');
canvas.getBoundingClientRect = function(){ return { left:0, top:0, width:800, height:300 }; };
canvas.getContext = function() {
  var currentStroke = '';
  var pathLineTo = 0;
  return new Proxy({
    measureText:function(){ return { width:50 }; },
    createLinearGradient:function(){ return { addColorStop:function(){} }; }
  }, {
    get:function(target, prop) {
      if (prop in target) return target[prop];
      if (prop === 'beginPath') return function(){ pathLineTo = 0; };
      if (prop === 'arc') return function(){ calls.arc += 1; };
      if (prop === 'lineTo') return function(){ pathLineTo += 1; };
      if (prop === 'stroke') return function(){
        if (currentStroke === '#DC2626') calls.redStrokeLineTo += pathLineTo;
        if (currentStroke === '#2563EB') calls.blueStrokeLineTo += pathLineTo;
      };
      if (prop === 'fillText') return function(txt){ calls.labels.push(String(txt)); };
      return function(){};
    },
    set:function(target, prop, value) {
      if (prop === 'strokeStyle') currentStroke = value;
      target[prop] = value;
      return true;
    }
  });
};
var empty = document.getElementById('pnl_empty_W22_SINGLE');
empty.classList = { toggle:function(cls, visible){ calls.emptyVisible = visible; } };
empty.querySelector = function(){ return { textContent:'' }; };
inst._drawChart({
  type:'intraday', labels:['09:30','09:35','09:40'],
  portfolio:[0.83, null, null], benchmark:[-0.19, null, null],
  position:[49.5, null, null], nav:[1.043841, null, null]
});
console.log(JSON.stringify(calls));
"""
        result = _run_node(script, files=["widgets/pnl-curve.js"])
        self.assertEqual(result.get("emptyVisible"), False, f"单点有效曲线不应显示空态: {result}")
        self.assertGreaterEqual(result.get("arc", 0), 2, f"单点有效曲线应画账户点和指数点: {result}")
        self.assertGreaterEqual(result.get("redStrokeLineTo", 0), 1, f"单点账户收益应画短线而不只是点: {result}")
        self.assertGreaterEqual(result.get("blueStrokeLineTo", 0), 1, f"单点指数参考应画短线而不只是点: {result}")
        self.assertTrue(any("+0.83%" in s for s in result.get("labels", [])),
            f"单点有效曲线应显示账户收益标签: {result}")

    def test_draw_chart_all_zero(self):
        script = r"""
var inst = new PnLCurveWidget({id:'W22_D2'});
inst.id = 'W22_D2';
inst._state = { period:'today', index:'sh', totalAsset:0, totalDeposit:0, liveQ:{}, positions:[], pnlLive:{} };
inst._lastChartData = {
  type:'intraday', labels:['09:30','09:35'],
  portfolio:[0.0, 0.0], benchmark:[0.0, 0.0],
  position:[0.0, 0.0], nav:[1.0, 1.0]
};
try {
  inst._drawChart(inst._lastChartData);
  console.log(JSON.stringify({ok:true}));
} catch(e) {
  console.log(JSON.stringify({ok:false, err: e.message.substring(0,100)}));
}
"""
        result = _run_node(script, files=["widgets/pnl-curve.js"])
        self.assertTrue(result.get("ok"), f"全零曲线 draw 不应崩溃: {result}")


class W22ChartFetchBehaviorTests(unittest.TestCase):
    """W22 图表请求节流，避免高频刷新导致 canvas 闪烁"""

    def test_fetch_chart_data_reuses_inflight_request(self):
        script = r"""
global.location = { protocol:'http:' };
var calls = 0;
var pending = new Promise(function(resolve) { global._resolveFetch = resolve; });
global.fetch = function(url) { calls++; return pending; };
var inst = new PnLCurveWidget({id:'W22'});
inst.id = 'W22';
inst._state = { period:'today', index:'sh' };
inst._fetchChartData(function(){});
inst._fetchChartData(function(){});
console.log(JSON.stringify({ calls:calls }));
"""
        result = _run_node(script, files=["widgets/pnl-curve.js"])
        self.assertEqual(result.get("calls"), 1, f"同一图表请求 in-flight 时应复用: {result}")


class W22CodeStructureTests(unittest.TestCase):
    """W22 源码结构补充验证"""

    def test_total_asset_not_null_check(self):
        src = (ROOT / "widgets" / "pnl-curve.js").read_text()
        self.assertIn("!= null", src, "应使用 != null 判断存在性")

    def test_valuation_complete_consumed(self):
        src = (ROOT / "widgets" / "pnl-curve.js").read_text()
        self.assertIn("valuation_complete", src, "应消费 valuation_complete")

    def test_data_date_consumed(self):
        src = (ROOT / "widgets" / "pnl-curve.js").read_text()
        self.assertIn("data_date", src, "应消费 data_date")

    def test_absmax_zero_guard(self):
        src = (ROOT / "widgets" / "pnl-curve.js").read_text()
        self.assertIn("absMax === 0", src, "应有全零保护")

    def test_w22_styles_live_in_theme_not_inline_injection(self):
        src = (ROOT / "widgets" / "pnl-curve.js").read_text()
        theme = (ROOT / "css" / "theme.css").read_text()
        self.assertNotIn("pnl-curve-style", src)
        self.assertNotIn("document.head.appendChild(style)", src)
        self.assertIn(".pnl-root", theme)
        self.assertIn(".pnl-kpi-sub{font-size:10px;color:var(--text-disabled);margin-top:2px;line-height:1.25", theme)
        self.assertIn(".pnl-chart-empty.ui-empty", theme)
        self.assertIn(".pnl-tooltip", theme)
        self.assertLess(theme.index(".pnl-chart-empty.ui-empty"), theme.index(".ui-empty{"))

    def test_w22_layout_has_dom_empty_state_and_stable_legend_classes(self):
        script = r"""
var inst = new PnLCurveWidget({id:'W22'});
inst.id = 'W22';
var html = inst._buildLayout();
console.log(JSON.stringify({
  hasEmpty: html.indexOf('ui-empty pnl-chart-empty') >= 0,
  hasCanvasClass: html.indexOf('<canvas class="pnl-chart"') >= 0,
  hasEmptyTitle: html.indexOf('收益曲线暂无数据') >= 0,
  hasPortfolioLegend: html.indexOf('pnl-leg-line pnl-leg-portfolio') >= 0,
  hasBenchmarkLegend: html.indexOf('pnl-leg-line pnl-leg-benchmark') >= 0,
  hasInlineLegendColor: html.indexOf('style="background:#DC2626"') >= 0
}));
"""
        result = _run_node(script, files=["widgets/pnl-curve.js"])
        self.assertTrue(result.get("hasEmpty"), f"W22 图表应有 DOM 空态: {result}")
        self.assertTrue(result.get("hasCanvasClass"), f"W22 canvas 应有稳定 class: {result}")
        self.assertTrue(result.get("hasEmptyTitle"), f"W22 空态应有稳定标题: {result}")
        self.assertTrue(result.get("hasPortfolioLegend"), f"W22 图例应使用 class: {result}")
        self.assertTrue(result.get("hasBenchmarkLegend"), f"W22 图例应使用 class: {result}")
        self.assertFalse(result.get("hasInlineLegendColor"), f"W22 图例不应保留内联颜色: {result}")



class W22Phase5CodeCheckTests(unittest.TestCase):
    """Phase 5: W22 _updateKPI 在估值不可信时标记所有动态 KPI"""

    def test_isquoteunavailable_block_exists_and_covers_dyn_kpis(self):
        """_updateKPI 使用 isQuoteUnavailable 来标记 period/dd/alpha/twr 不可用"""
        src = (ROOT / "widgets" / "pnl-curve.js").read_text()
        self.assertIn("isQuoteUnavailable", src, "W22 应有 isQuoteUnavailable 检查")
        # 验证动态 KPI 被标记不可用
        self.assertIn("pnl_period_val", src)
        self.assertIn("pnl_dd_val", src)
        self.assertIn("估值不可信", src)


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()


class W22Phase5CodeCheckTests(unittest.TestCase):
    """Phase 5: W22 _updateKPI 在估值不可信时标记所有动态 KPI"""

    def test_isquoteunavailable_block_exists_and_covers_dyn_kpis(self):
        """_updateKPI 使用 isQuoteUnavailable 来标记 period/dd/alpha/twr 不可用"""
        src = (ROOT / "widgets" / "pnl-curve.js").read_text()
        self.assertIn("isQuoteUnavailable", src, "W22 应有 isQuoteUnavailable 检查")
        # 验证动态 KPI 被标记不可用
        self.assertIn("pnl_period_val", src)
        self.assertIn("pnl_dd_val", src)
        self.assertIn("估值不可信", src)


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
