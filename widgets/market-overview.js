// widgets/market-overview.js — W04 市场全景 (v2.1 补昨日收盘基线)
'use strict';

class MarketOverviewWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var d = data || {};
    var li = d.live_index || {};
    var m = d.market || {};

    var initBase = DataStore.getInitialBase();
    var closeM = (initBase && initBase.market) || {};
    var closeS = (initBase && initBase.sentiment) || {};

    var html = '<div style="display:flex;gap:var(--sp-md);flex-wrap:wrap">';

    [{name:'上证',price:li['上证指数']||'—',chg:String(li['上证涨幅']||'—')},
     {name:'深证',price:li['深证指数']||'—',chg:String(li['深证涨幅']||'—')},
     {name:'创业',price:li['创业指数']||'—',chg:String(li['创业涨幅']||'—')}]
    .forEach(function(idx) {
      var dir = idx.chg.charAt(0) === '+' ? 'up' : idx.chg.charAt(0) === '-' ? 'down' : '';
      html += '<div class="kpi-card" style="flex:1;min-width:100px">' +
        '<div class="kpi-label">' + idx.name + '</div>' +
        '<div class="kpi-value ' + dir + '" style="font-size:18px">' + idx.price + '</div>' +
        '<div class="kpi-verdict ' + dir + '">' + idx.chg + '</div>' +
        '</div>';
    });
    html += '</div>';

    html += '<div style="display:flex;gap:var(--sp-md);margin-top:var(--sp-sm);flex-wrap:wrap">';
    html += '<div class="kpi-card" style="flex:1;min-width:80px"><div class="kpi-label">成交额</div><div class="kpi-value" style="font-size:14px">'+(li['成交额']||'—')+'</div><div class="kpi-verdict">'+(li['成交额差']||'')+'</div></div>';
    html += '<div class="kpi-card" style="flex:1;min-width:80px"><div class="kpi-label">涨跌比</div><div class="kpi-value" style="font-size:14px">'+(m['涨跌比']||'—')+'</div></div>';
    html += '<div class="kpi-card" style="flex:1;min-width:60px"><div class="kpi-label">涨停</div><div class="kpi-value up" style="font-size:14px">'+(m['涨停家数']||'—')+'</div></div>';
    html += '<div class="kpi-card" style="flex:1;min-width:60px"><div class="kpi-label">跌停</div><div class="kpi-value down" style="font-size:14px">'+(m['跌停家数']||'—')+'</div></div>';
    html += '</div>';

    // 昨日收盘基线 (来自 DataStore.initialBase)
    html += '<div style="margin-top:var(--sp-md);padding-top:var(--sp-sm);border-top:1px solid var(--border-light)">' +
      '<div class="kpi-label" style="margin-bottom:var(--sp-xs);color:var(--text-secondary)">昨日收盘基线</div>';
    html += '<div style="display:flex;flex-wrap:wrap;gap:var(--sp-xs) var(--sp-lg);font-size:var(--fs-body)">';
    html += '<span style="color:var(--text-secondary);font-size:var(--fs-label)">情绪 <strong style="color:var(--text-primary)">' + (closeS['情绪值'] != null ? closeS['情绪值'] + '%' : '—') + '</strong> <span style="color:var(--text-disabled)">' + (closeS['情绪区间'] || '') + '</span></span>';
    html += '<span style="color:var(--text-secondary);font-size:var(--fs-label)">赚钱 <strong style="color:var(--text-primary)">' + (closeS['赚钱效应'] || '—') + '</strong></span>';
    var zsClose = parseFloat(closeS['昨日涨停收益']) || 0;
    html += '<span style="color:var(--text-secondary);font-size:var(--fs-label)">涨停收益 <strong style="color:' + (zsClose > 0 ? 'var(--up)' : zsClose < 0 ? 'var(--down)' : 'var(--text-primary)') + '">' + (closeS['昨日涨停收益'] || '—') + '</strong></span>';
    html += '<span style="color:var(--text-secondary);font-size:var(--fs-label)">晋级率 <strong style="color:var(--info)">' + (closeS['晋级率'] || '—') + '</strong></span>';
    html += '<span style="color:var(--text-secondary);font-size:var(--fs-label)">涨停 <strong style="color:var(--up)">' + (closeM['涨停家数'] || '—') + '</strong>/跌停 <strong style="color:var(--down)">' + (closeM['跌停家数'] || '—') + '</strong></span>';
    html += '<span style="color:var(--text-secondary);font-size:var(--fs-label)">最高板 <strong style="color:var(--text-primary)">' + (closeS['最高板'] || '—') + '</strong></span>';
    html += '</div></div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W04', MarketOverviewWidget);
