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

    // 自动计算
    active.forEach(function(p) {
      var qty = parseFloat(p['数量']) || 0;
      var price = parseFloat(p['现价']) || 0;
      var cost = parseFloat(p['成本']) || 0;
      p['_市值'] = Math.round(price * qty);
      p['_持仓'] = qty;  // 持仓 = 股数
      p['_盈亏'] = Math.round((price - cost) * qty);
      p['_盈亏pct'] = cost > 0 ? ((price - cost) / cost * 100) : 0;
    });

    var html = '';

    // 汇总卡片
    var manual = DataStore.manualData.getAll();
    var totalAssetWan = parseFloat(manual['总资产']) || 0;
    var totalAsset = totalAssetWan * 10000;

    var posValue = 0, posCost = 0;
    active.forEach(function(p) {
      posValue += p['_市值'] || 0;
      posCost += Math.round((parseFloat(p['成本']) || 0) * (parseFloat(p['数量']) || 0));
    });
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
        '<th>标的</th><th>市值</th><th>持仓</th><th>盈亏</th><th>盈亏%</th><th>现价</th><th>成本</th><th>止损</th><th>状态</th>' +
        '</tr></thead><tbody>';
      active.forEach(function(p) {
        var pnlC = (p['_盈亏']||0) > 0 ? 'up' : (p['_盈亏']||0) < 0 ? 'down' : '';
        var pctC = (p['_盈亏pct']||0) > 0 ? 'up' : (p['_盈亏pct']||0) < 0 ? 'down' : '';
        html += '<tr>' +
          '<td><strong>'+(p['标的']||'—')+'</strong> <span style="font-size:var(--fs-label);color:var(--text-disabled)">'+(p['代码']||'')+'</span></td>' +
          '<td style="font-weight:600">'+(p['_市值']||0).toLocaleString()+'</td>' +
          '<td>'+(p['_持仓']||0).toLocaleString()+'</td>' +
          '<td class="'+pnlC+'" style="font-weight:600">'+(p['_盈亏']>=0?'+':'')+(p['_盈亏']||0).toLocaleString()+'</td>' +
          '<td class="'+pctC+'">'+(p['_盈亏pct']>=0?'+':'')+(p['_盈亏pct']||0).toFixed(2)+'%</td>' +
          '<td>'+(p['现价']||'—')+'</td>' +
          '<td style="color:var(--text-secondary)">'+(p['成本']||'—')+'</td>' +
          '<td>'+(p['止损']||'—')+'</td>' +
          '<td><span class="tag '+(p['状态']==='持有'?'info':'')+'">'+(p['状态']||'持有')+'</span></td>' +
          '</tr>';
      });
      html += '</tbody></table>';
    }

    // 清仓记录（追踪一周）
    if (cleared.length) {
      var now = new Date();
      var tracked = cleared.filter(function(p) {
        var d = p['清仓日期'];
        if (!d) return true;  // 无日期则始终显示
        try {
          var sold = new Date(d);
          return (now - sold) / (1000*60*60*24) <= 7;
        } catch(e) { return true; }
      });

      if (tracked.length) {
        html += '<div style="margin-top:var(--sp-md);padding-top:var(--sp-sm);border-top:1px solid var(--border-light)">' +
          '<div class="kpi-label" style="margin-bottom:var(--sp-sm)">清仓记录（7日内）</div>';
        html += '<table class="data-table"><thead><tr>' +
          '<th>标的</th><th>成本</th><th>卖出价</th><th>盈亏%</th><th>现价</th><th>卖出后涨跌</th><th>原因</th>' +
          '</tr></thead><tbody>';

        tracked.forEach(function(p) {
          var sellPrice = parseFloat(p['卖出价']) || 0;
          var costPrice = parseFloat(p['成本']) || 0;
          var curPrice = parseFloat(p['最新价'] || p['现价']) || 0;
          var plPct = parseFloat(p['浮盈'] || p['盈亏']) || 0;
          var plCls = plPct > 0 ? 'up' : plPct < 0 ? 'down' : '';
          // 卖出后涨跌幅 = (现价 - 卖出价) / 卖出价
          var afterPct = sellPrice > 0 ? ((curPrice - sellPrice) / sellPrice * 100) : 0;
          var afterCls = afterPct > 0 ? 'up' : afterPct < 0 ? 'down' : '';
          // 现价从 live_quotes 取
          var liveQ = (data && data.live_quotes && data.live_quotes[p['代码']]) || {};
          var displayPrice = liveQ['最新价'] || curPrice || '—';

          html += '<tr>' +
            '<td><strong>'+(p['标的']||'—')+'</strong> <span style="font-size:var(--fs-label);color:var(--text-disabled)">'+(p['代码']||'')+'</span></td>' +
            '<td>'+(costPrice||'—')+'</td>' +
            '<td>'+(sellPrice||'—')+'</td>' +
            '<td class="'+plCls+'" style="font-weight:600">'+(plPct>=0?'+':'')+plPct.toFixed(2)+'%</td>' +
            '<td>'+(curPrice > 0 ? curPrice : '—')+'</td>' +
            '<td class="'+afterCls+'" style="font-weight:600">'+(afterPct>=0?'+':'')+afterPct.toFixed(2)+'%</td>' +
            '<td style="font-size:var(--fs-label);color:var(--text-secondary);max-width:100px;white-space:normal">'+(p['清仓原因']||'')+'</td>' +
            '</tr>';
        });
        html += '</tbody></table></div>';
      }
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W15', PositionsWidget);
