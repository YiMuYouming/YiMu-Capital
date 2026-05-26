// widgets/risk-panel.js — W14 账户风控 v3.0 (实时持仓联动)
'use strict';

class RiskPanelWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var R = (data && data.risk) || {};
    var liveQ = (data && data.live_quotes) || {};
    var pnlLive = (data && data.pnl_live) || {};
    var manual = DataStore.manualData.getAll();

    // 持仓（从账户 SSOT 同源数据）
    var hasSsotPositions = Array.isArray(pnlLive.positions);
    var basePos = JSON.parse(JSON.stringify(hasSsotPositions ? pnlLive.positions : ((data && data.positions) || [])));
    var P = basePos;
    try {
      var mp = JSON.parse(manual['_positions'] || 'null');
      if (!hasSsotPositions && mp && mp.length) {
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

    // 账户口径优先使用日内快照，避免过期基线把仓位显示成 100%。
    // pnlLive.cash=0 / mv=0 / total_asset=0 是合法值，用 != null 判断。
    if (pnlLive.mv != null && !isNaN(parseFloat(pnlLive.mv))) {
      totalMV = parseFloat(pnlLive.mv);
    }
    var totalAsset = pnlLive.total_asset != null && !isNaN(parseFloat(pnlLive.total_asset))
                  ? parseFloat(pnlLive.total_asset)
                  : parseFloat(((data && data.pnl) || {})['总资产'] || '0') || totalMV;
    var positionRatio = totalAsset > 0 ? (totalMV / totalAsset * 100) : 0;
    var availFund = pnlLive.cash != null && !isNaN(parseFloat(pnlLive.cash))
                  ? parseFloat(pnlLive.cash)
                  : (totalAsset - totalMV);

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

    // ===== rule_state 实时风控（Gate 1A）=====
    var RS = (data && data.rule_state) || null;
    if (RS) {
      var rsBlocks = RS.blocks || [];
      var rsWarnings = RS.warnings || [];
      var rsCaps = RS.caps || {};
      if (rsBlocks.length || rsWarnings.length) {
        html += '<div style="margin-bottom:var(--sp-sm);padding:var(--sp-xs) var(--sp-sm);background:rgba(220,38,38,0.06);border-radius:var(--radius-md);border-left:3px solid'+(RS.tradable?'var(--warn)':'var(--danger)')+'">';
        html += '<div style="font-size:var(--fs-label);font-weight:700;color:'+(RS.tradable?'var(--warn)':'var(--danger)')+';margin-bottom:2px">'+(RS.tradable?'⚠ 规则约束':'✕ 规则阻断')+'</div>';
        rsBlocks.forEach(function(b){
          html += '<div style="font-size:var(--fs-body);color:var(--'+(b.scope==='all'?'danger':'warn')+');padding:1px 0">'+b.code+': '+b.message+'</div>';
        });
        rsWarnings.forEach(function(w){
          html += '<div style="font-size:var(--fs-body);color:var(--warn)">⚠ '+w.message+'</div>';
        });
        html += '</div>';
      }
      html += '<div style="font-size:var(--fs-body);color:var(--text-disabled);margin-bottom:var(--sp-sm)">总仓位 '+(rsCaps.total_pct!=null?rsCaps.total_pct+'%':'—')+' | 首笔 '+(rsCaps.first_entry_pct!=null?rsCaps.first_entry_pct+'%':'—')+' | '+(RS.tradable?'可交易':'禁止开仓')+'</div>';
    }

    // === 持仓累计浮盈（大字）===
    var pnlCls = realTimePnl > 0 ? 'up' : realTimePnl < 0 ? 'down' : '';
    html += '<div style="text-align:center;padding:var(--sp-sm);margin-bottom:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md)">'+
      '<div style="font-size:var(--fs-label);color:var(--text-disabled)">持仓累计浮盈</div>'+
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

    // === 风控线（实时 rule_state 驱动，旧 daily risk 仅供数值引用）===
    html += '<div style="font-size:var(--fs-label);font-weight:600;color:var(--text-primary);margin-bottom:var(--sp-xs)">风控线</div>';

    if (!RS) {
      html += '<div style="text-align:center;padding:8px;color:var(--danger);font-size:var(--fs-body);font-weight:600">规则状态不可用</div>'+
        '<div style="font-size:10px;color:var(--text-disabled);text-align:center">无法确认实时风控结论</div>';
    } else {
      // 从 rule_state 取实时阻断结论
      var dayStopBlock = rsBlocks.filter(function(b){ return b.code === 'DAY_STOP'; });
      var lossStreakBlock = rsBlocks.filter(function(b){ return b.code === 'LOSS_STREAK'; });
      var dayHit = dayStopBlock.length > 0;
      var streakHit = lossStreakBlock.length > 0;

      html += '<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:var(--fs-body)">'+
        '<span style="color:var(--text-secondary)">单日熔断</span>'+
        '<span style="font-family:var(--font-mono)">阈值 -3%</span>'+
        '<span style="color:'+(dayHit?'var(--danger)':'var(--info)')+'">'+(dayHit?'⚠ 触发':'✓ 未触发')+'</span></div>';

      html += '<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:var(--fs-body)">'+
        '<span style="color:var(--text-secondary)">连亏天数</span>'+
        '<span style="font-family:var(--font-mono)">'+loseDays+'天</span>'+
        '<span style="color:'+(streakHit?'var(--danger)':'var(--info)')+'">'+(streakHit?'⚠ 空仓':'✓ 正常')+'</span></div>';
    }

    // 周回撤（rule_state 不覆盖，保留 baseline 字段 + 数据引用）
    var wCls = weekDD > weekWarnLine ? 'danger' : weekDD > 3 ? 'warn' : 'info';
    html += '<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:var(--fs-body)">'+
      '<span style="color:var(--text-secondary)">周回撤</span>'+
      '<span style="font-family:var(--font-mono)">'+pct(weekDD)+' / '+weekWarnLine+'%</span>'+
      '<span class="'+wCls+'" style="font-weight:600">'+(weekDD>weekWarnLine?'⚠ 触发':'—')+'</span></div>';

    // 月回撤
    var mCls = monthDD > monthWarnLine ? 'danger' : monthDD > 5 ? 'warn' : 'info';
    html += '<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:var(--fs-body)">'+
      '<span style="color:var(--text-secondary)">月回撤</span>'+
      '<span style="font-family:var(--font-mono)">'+pct(monthDD)+' / '+monthWarnLine+'%</span>'+
      '<span class="'+mCls+'" style="font-weight:600">'+(monthDD>monthWarnLine?'⚠ 触发':'—')+'</span></div>';

    // ===== 止损提醒（只读，优先 SSOT 止损字段，规则兜底明确标记）=====
    var slAlerts = [];
    activePos.forEach(function(p) {
      var cost = parseFloat(p['成本']) || 0;
      var price = parseFloat(p['现价']) || parseFloat(p['成本']) || 0;
      var qty = parseFloat(p['数量']) || 0;
      if (!cost || !price || !qty) return;
      var ssotSl = parseFloat(p['止损']);
      var hasSsotSl = !isNaN(ssotSl) && ssotSl > 0;
      var slPrice = hasSsotSl ? ssotSl : (cost * 0.93);
      var slSource = hasSsotSl ? '' : ' (规则推算)';
      var isNearSl = price <= slPrice * 1.02 && price > slPrice;
      var isHitSl = price <= slPrice;
      if (isHitSl || isNearSl) {
        var pnlPct = ((price - cost) / cost * 100);
        slAlerts.push({
          name: p['标的'] || '—', code: p['代码'] || '',
          cost: cost, price: price, sl: slPrice,
          pnlPct: pnlPct, hit: isHitSl, source: slSource
        });
      }
    });
    if (slAlerts.length > 0) {
      html += '<div style="margin-top:var(--sp-sm);border-top:1px solid var(--border-light);padding-top:var(--sp-sm)">' +
        '<div style="font-size:11px;font-weight:700;color:var(--danger);margin-bottom:4px">止损提醒</div>';
      slAlerts.forEach(function(a) {
        html += '<div class="' + (a.hit ? 'sl-alert' : '') + '" style="' + (a.hit ? '' : 'font-size:11px;padding:2px 8px;color:var(--warn);') + '">' +
          (a.hit ? '🔴 ' : '🟡 ') + a.name + ' ' + a.code +
          ' 成本' + a.cost.toFixed(2) + ' 现价' + a.price.toFixed(2) +
          ' 止损' + a.sl.toFixed(2) + a.source + ' 浮亏' + (a.pnlPct >= 0 ? '+' : '') + a.pnlPct.toFixed(2) + '%' +
          '</div>';
      });
      html += '</div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W14', RiskPanelWidget);
