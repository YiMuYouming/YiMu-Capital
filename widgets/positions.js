// widgets/positions.js — W15 持仓明细
'use strict';

class PositionsWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var P = (data && data.positions) || [];

    var active = [], cleared = [];
    P.forEach(function(p) {
      var s = p['状态'] || '';
      if (s.indexOf('清仓') >= 0 || s.indexOf('卖出') >= 0 || s.indexOf('已清') >= 0) {
        cleared.push(p);
      } else {
        active.push(p);
      }
    });

    // 自动计算：市值 = 现价 × 数量, 盈亏 = (现价 − 成本) × 数量
    active.forEach(function(p) {
      var qty = parseFloat(p['数量']) || 1;
      p['_市值'] = Math.round((parseFloat(p['现价']) || 0) * qty);
      p['_持仓'] = Math.round((parseFloat(p['成本']) || 0) * qty);
      p['_盈亏'] = Math.round(((parseFloat(p['现价']) || 0) - (parseFloat(p['成本']) || 0)) * qty);
    });

    var html = '';

    // 汇总卡片
    var manual = DataStore.manualData.getAll();
    var totalAssetWan = parseFloat(manual['总资产']) || 0;
    var totalAsset = totalAssetWan * 10000;

    var posValue = 0, posCost = 0;
    active.forEach(function(p) { posValue += p['_市值'] || 0; posCost += p['_持仓'] || 0; });
    var totalPnl = posValue - posCost;
    var pnlCls = totalPnl > 0 ? 'up' : totalPnl < 0 ? 'down' : '';
    var pnlPct = posCost > 0 ? (totalPnl / posCost * 100) : 0;
    var availFund = totalAsset - posValue;
    var positionRatio = totalAsset > 0 ? Math.round(posValue / totalAsset * 100) : 0;

    if (totalAsset > 0) {
      html += '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:var(--sp-sm);margin-bottom:var(--sp-md);padding:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md)">' +
        '<div style="text-align:center"><div class="kpi-label">总资产</div><div style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700">'+(totalAsset).toLocaleString()+'</div></div>' +
        '<div style="text-align:center"><div class="kpi-label">持仓市值</div><div style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700">'+posValue.toLocaleString()+'</div></div>' +
        '<div style="text-align:center"><div class="kpi-label">总盈亏</div><div style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700;color:var(--'+pnlCls+')">'+(totalPnl>=0?'+':'')+totalPnl.toLocaleString()+'</div></div>' +
        '<div style="text-align:center"><div class="kpi-label">总盈亏%</div><div style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700;color:var(--'+pnlCls+')">'+(pnlPct>=0?'+':'')+pnlPct.toFixed(2)+'%</div></div>' +
        '<div style="text-align:center"><div class="kpi-label">可用资金</div><div style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700">'+availFund.toLocaleString()+'</div></div>' +
        '<div style="text-align:center"><div class="kpi-label">仓位</div><div style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700;color:'+(positionRatio>80?'var(--danger)':positionRatio>50?'var(--warn)':'var(--info)')+'">'+positionRatio+'%</div></div>' +
        '</div>';
    }

    if (!active.length && !cleared.length) {
      html += '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-secondary)">当前空仓</div>';
      body.innerHTML = html;
      this.updateTimestamp();
      return;
    }

    // 活跃持仓表格
    if (active.length) {
      html += '<table class="data-table"><thead><tr>' +
        '<th>标的</th><th>市值</th><th>持仓</th><th>盈亏</th><th>现价</th><th>成本</th><th>止损</th><th>状态</th>' +
        '</tr></thead><tbody>';
      active.forEach(function(p) {
        var pnlC = (p['_盈亏']||0) > 0 ? 'up' : (p['_盈亏']||0) < 0 ? 'down' : '';
        var fp = parseFloat(p['浮盈']) || 0;
        var fpC = fp > 0 ? 'up' : fp < 0 ? 'down' : '';
        html += '<tr>' +
          '<td><strong>'+(p['标的']||'—')+'</strong> <span style="font-size:var(--fs-label);color:var(--text-disabled)">'+(p['代码']||'')+'</span></td>' +
          '<td style="font-weight:600">'+(p['_市值']||0).toLocaleString()+'</td>' +
          '<td style="color:var(--text-secondary)">'+(p['_持仓']||0).toLocaleString()+'</td>' +
          '<td class="'+pnlC+'" style="font-weight:600">'+(p['_盈亏']>=0?'+':'')+(p['_盈亏']||0).toLocaleString()+'</td>' +
          '<td>'+(p['现价']||'—')+'</td>' +
          '<td style="color:var(--text-secondary)">'+(p['成本']||'—')+'</td>' +
          '<td>'+(p['止损']||'—')+'</td>' +
          '<td><span class="tag '+(p['状态']==='持有'?'info':'')+'">'+(p['状态']||'持有')+'</span></td>' +
          '</tr>';
      });
      html += '</tbody></table>';
    }

    // 清仓记录
    if (cleared.length) {
      html += '<div style="margin-top:var(--sp-md);padding-top:var(--sp-sm);border-top:1px solid var(--border-light)">' +
        '<div class="kpi-label" style="margin-bottom:var(--sp-sm)">清仓记录</div>';
      cleared.forEach(function(p) {
        var pl = parseFloat(p['盈亏']) || 0;
        var plCls = pl > 0 ? 'up' : pl < 0 ? 'down' : '';
        html += '<div style="padding:var(--sp-sm);margin-bottom:var(--sp-xs);background:var(--bg-base);border-radius:var(--radius-sm);font-size:var(--fs-body)">' +
          '<strong>'+(p['标的']||'')+'</strong> <span class="tag" style="background:var(--danger-bg);color:var(--danger)">'+(p['状态']||'已清')+'</span> ' +
          '<span style="color:var(--text-secondary)">成本 '+(p['成本']||'—')+' → 卖出 '+(p['卖出价']||'—')+'</span> ' +
          '<span class="'+plCls+'" style="font-weight:600">'+(pl!==0?(pl>0?'+':'')+pl.toFixed(2)+'%':'0.00%')+'</span>' +
          (p['清仓原因']?'<div style="color:var(--text-secondary);font-size:var(--fs-label);margin-top:2px">'+p['清仓原因']+'</div>':'') +
          '</div>';
      });
      html += '</div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W15', PositionsWidget);
