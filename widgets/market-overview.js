// widgets/market-overview.js — W04 市场全景
'use strict';

class MarketOverviewWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var d = data || {};
    var li = d.live_index || {};
    var m = d.market || {};

    var closeData = DataStore.getInitialBase();
    var closeIdx = closeData && closeData.market ? closeData.market['上证指数'] : '—';

    var html = '<div style="display:flex;gap:var(--sp-md);flex-wrap:wrap">';

    // Three index cards
    [{name:'上证',price:li['上证指数']||'—',chg:li['上证涨幅']||'—'},
     {name:'深证',price:li['深证指数']||'—',chg:li['深证涨幅']||'—'},
     {name:'创业',price:li['创业指数']||'—',chg:li['创业涨幅']||'—'}]
    .forEach(function(idx) {
      var dir = String(idx.chg).charAt(0) === '+' ? 'up' : String(idx.chg).charAt(0) === '-' ? 'down' : '';
      html += '<div class="kpi-card" style="flex:1;min-width:100px">' +
        '<div class="kpi-label">' + idx.name + '</div>' +
        '<div class="kpi-value ' + dir + '" style="font-size:18px">' + idx.price + '</div>' +
        '<div class="kpi-verdict ' + dir + '">' + idx.chg + '</div>' +
        '</div>';
    });
    html += '</div>';

    // Bottom row
    html += '<div style="display:flex;gap:var(--sp-md);margin-top:var(--sp-sm);flex-wrap:wrap">';
    html += '<div class="kpi-card" style="flex:1;min-width:80px"><div class="kpi-label">成交额</div><div class="kpi-value" style="font-size:14px">'+(li['成交额']||'—')+'</div><div class="kpi-verdict">'+(li['成交额差']||'')+'</div></div>';
    html += '<div class="kpi-card" style="flex:1;min-width:80px"><div class="kpi-label">涨跌比</div><div class="kpi-value" style="font-size:14px">'+(m['涨跌比']||'—')+'</div></div>';
    html += '<div class="kpi-card" style="flex:1;min-width:60px"><div class="kpi-label">涨停</div><div class="kpi-value up" style="font-size:14px">'+(m['涨停家数']||'—')+'</div></div>';
    html += '<div class="kpi-card" style="flex:1;min-width:60px"><div class="kpi-label">跌停</div><div class="kpi-value down" style="font-size:14px">'+(m['跌停家数']||'—')+'</div></div>';
    html += '</div>';

    // Yesterday close baseline
    html += '<div style="margin-top:var(--sp-sm);font-size:var(--fs-label);color:var(--text-disabled)">昨日收盘基线: 上证 ' + closeIdx + '</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W04', MarketOverviewWidget);
