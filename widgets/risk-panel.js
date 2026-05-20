// widgets/risk-panel.js — W14 账户风控 v3.0 (实时持仓联动)
'use strict';

class RiskPanelWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var R = (data && data.risk) || {};
    var liveQ = (data && data.live_quotes) || {};
    var manual = DataStore.manualData.getAll();

    // 持仓（从W15同源数据）
    var basePos = JSON.parse(JSON.stringify((data && data.positions) || []));
    var P = basePos;
    try {
      var mp = JSON.parse(manual['_positions'] || 'null');
      if (mp && mp.length) {
        mp.forEach(function(m) {
          var idx = P.findIndex(function(p) { return p['标的'] === m['标的']; });
          if (idx >= 0) P[idx] = m; else P.push(m);
        });
      }
    } catch(e) {}

    // 注入实时现价
    P.forEach(function(p) {
      var q = liveQ[p['代码']] || {};
      var lp = parseFloat(q['最新价']) || 0;
      if (lp > 0) p['现价'] = lp;
    });

    // 计算实时盈亏
    var totalMV = 0, totalCost = 0;
    var activePos = P.filter(function(p) { var s=p['状态']||''; return s.indexOf('清')<0 && s.indexOf('删')<0; });
    activePos.forEach(function(p) {
      var qty = parseFloat(p['数量']) || 0;
      var cost = parseFloat(p['成本']) || 0;
      var price = parseFloat(p['现价']) || parseFloat(p['成本']) || 0;
      totalMV += price * qty;
      totalCost += cost * qty;
    });
    var realTimePnl = totalMV - totalCost;
    var realTimePnlPct = totalCost > 0 ? (realTimePnl / totalCost * 100) : 0;

    // 总资产（从W16报数）
    var totalAsset = parseFloat(manual['总资产']) || (totalMV + parseFloat(manual['可用资金']||0)) || totalMV;
    var positionRatio = totalAsset > 0 ? (totalMV / totalAsset * 100) : 0;
    var availFund = parseFloat(manual['可用资金']) || (totalAsset - totalMV);

    // 风控基线
    var meltdownLine = parseFloat(R['单日熔断线']) || -3;
    var weekWarnLine = parseFloat(R['周回撤预警']) || 6;
    var monthWarnLine = parseFloat(R['月回撤预警']) || 10;
    var loseDays = parseInt(R['连亏天数']) || 0;
    var meltdown = R['熔断触发'];
    var weekDD = parseFloat(R['周累计回撤']) || 0;
    var monthDD = parseFloat(R['月累计回撤']) || 0;

    function money(v) {
      if (Math.abs(v) >= 1e4) return (v/1e4).toFixed(1)+'万';
      return v.toFixed(0);
    }
    function pct(v, plus) {
      if (v == null) return '—';
      return (plus && v>0?'+':'')+v.toFixed(2)+'%';
    }

    var html = '';

    // === 实时盈亏（大字）===
    var pnlCls = realTimePnl > 0 ? 'up' : realTimePnl < 0 ? 'down' : '';
    html += '<div style="text-align:center;padding:var(--sp-sm);margin-bottom:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md)">'+
      '<div style="font-size:var(--fs-label);color:var(--text-disabled)">实时盈亏 ⚡</div>'+
      '<div class="'+pnlCls+'" style="font-family:var(--font-mono);font-size:22px;font-weight:700">'+(realTimePnl>=0?'+':'')+money(realTimePnl)+'</div>'+
      '<div class="'+pnlCls+'" style="font-size:var(--fs-body)">'+pct(realTimePnlPct, true)+'</div>'+
      '</div>';

    // === 持仓概况 ===
    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-xs) var(--sp-sm);margin-bottom:var(--sp-sm)">'+
      '<div class="kpi-card"><div class="kpi-label">持仓市值</div>'+
        '<div class="kpi-value" style="font-size:14px">'+money(totalMV)+'</div></div>'+
      '<div class="kpi-card"><div class="kpi-label">可用资金</div>'+
        '<div class="kpi-value" style="font-size:14px">'+money(availFund)+'</div></div>'+
      '<div class="kpi-card"><div class="kpi-label">仓位</div>'+
        '<div class="kpi-value" style="font-size:14px;color:'+(positionRatio>80?'var(--danger)':positionRatio>50?'var(--warn)':'var(--info)')+'">'+positionRatio.toFixed(0)+'%</div></div>'+
      '<div class="kpi-card"><div class="kpi-label">持仓数</div>'+
        '<div class="kpi-value" style="font-size:14px">'+activePos.length+'只</div></div>'+
      '</div>';

    // === 风控线 ===
    html += '<div style="font-size:var(--fs-label);font-weight:600;color:var(--text-primary);margin-bottom:var(--sp-xs)">风控线</div>';

    // 单日熔断（用实时盈亏判断）
    var dayHit = realTimePnlPct <= meltdownLine && totalCost > 0;
    html += '<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:var(--fs-body)">'+
      '<span style="color:var(--text-secondary)">单日熔断</span>'+
      '<span style="font-family:var(--font-mono)">阈值 '+meltdownLine+'%</span>'+
      '<span style="color:'+(dayHit?'var(--danger)':'var(--info)')+'">'+(dayHit?'⚠️触发':'✅安全')+'</span></div>';

    // 连亏
    html += '<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:var(--fs-body)">'+
      '<span style="color:var(--text-secondary)">连亏天数</span>'+
      '<span style="font-family:var(--font-mono)">'+loseDays+'天</span>'+
      '<span style="color:'+(loseDays>=2?'var(--danger)':'var(--info)')+'">'+(loseDays>=2?'⚠️空仓':'✅正常')+'</span></div>';

    // 周回撤
    var wCls = weekDD > weekWarnLine ? 'danger' : weekDD > 3 ? 'warn' : 'info';
    html += '<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:var(--fs-body)">'+
      '<span style="color:var(--text-secondary)">周回撤</span>'+
      '<span style="font-family:var(--font-mono)">'+pct(weekDD)+' / '+weekWarnLine+'%</span>'+
      '<span class="'+wCls+'" style="font-weight:600">'+(weekDD>weekWarnLine?'⚠️触发':'✅安全')+'</span></div>';

    // 月回撤
    var mCls = monthDD > monthWarnLine ? 'danger' : monthDD > 5 ? 'warn' : 'info';
    html += '<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:var(--fs-body)">'+
      '<span style="color:var(--text-secondary)">月回撤</span>'+
      '<span style="font-family:var(--font-mono)">'+pct(monthDD)+' / '+monthWarnLine+'%</span>'+
      '<span class="'+mCls+'" style="font-weight:600">'+(monthDD>monthWarnLine?'⚠️触发':'✅安全')+'</span></div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W14', RiskPanelWidget);
