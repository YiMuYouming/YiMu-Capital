// widgets/market-overview.js — W04 市场全景 (v2.2 实时涨幅/涨跌家数/成交额差)
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

    // 三大指数卡片
    var html = '<div style="display:flex;gap:var(--sp-md);flex-wrap:wrap">';
    [
      {name:'上证', price:li['上证指数']||'—', chg:String(li['上证指数涨幅']||'—')},
      {name:'深证', price:li['深证指数']||'—', chg:String(li['深证指数涨幅']||'—')},
      {name:'创业', price:li['创业指数']||'—', chg:String(li['创业指数涨幅']||'—')}
    ].forEach(function(idx) {
      var dir = idx.chg.charAt(0) === '+' ? 'up' : idx.chg.charAt(0) === '-' ? 'down' : '';
      html += '<div class="kpi-card" style="flex:1;min-width:100px">' +
        '<div class="kpi-label" style="font-size:12px">' + idx.name + '</div>' +
        '<div class="kpi-value ' + dir + '" style="font-size:18px">' + idx.price + '</div>' +
        '<div class="kpi-verdict ' + dir + '" style="font-size:13px">' + idx.chg + '</div>' +
        '</div>';
    });
    html += '</div>';

    // 成交额 / 涨跌比 / 涨停 / 跌停
    var amtDiff = li['成交额差'] || '';
    var amtDir = amtDiff.charAt(0) === '+' ? 'up' : amtDiff.charAt(0) === '-' ? 'down' : '';
    var upCnt = li['上涨家数'];
    var dnCnt = li['下跌家数'];
    var udHtml = (upCnt != null && dnCnt != null)
      ? '<span style="color:var(--up);font-weight:600">' + upCnt + '</span>/<span style="color:var(--down);font-weight:600">' + dnCnt + '</span>'
      : (m['涨跌比'] || '—');

    html += '<div style="display:flex;gap:var(--sp-md);margin-top:var(--sp-sm);flex-wrap:wrap;font-size:12px">';
    html += '<div class="kpi-card" style="flex:1;min-width:80px"><div class="kpi-label" style="font-size:12px">成交额</div><div class="kpi-value" style="font-size:15px">'+(li['成交额']||'—')+'</div><div class="kpi-verdict ' + amtDir + '" style="font-size:12px">'+(amtDiff||'')+'</div></div>';
    html += '<div class="kpi-card" style="flex:1;min-width:80px"><div class="kpi-label" style="font-size:12px">涨跌比</div><div class="kpi-value" style="font-size:15px">'+udHtml+'</div></div>';
    var amp = li['上证指数振幅'] || '—';
    html += '<div class="kpi-card" style="flex:1;min-width:60px"><div class="kpi-label" style="font-size:12px">振幅</div><div class="kpi-value" style="font-size:15px;color:var(--warn)">'+amp+'</div></div>';
    var vr = li['量比'];
    var vrStr = vr != null ? vr.toFixed(2) + 'x' : '—';
    var vrColor = vr != null ? (vr >= 1 ? 'var(--up)' : 'var(--down)') : '';
    html += '<div class="kpi-card" style="flex:1;min-width:60px"><div class="kpi-label" style="font-size:12px">量比</div><div class="kpi-value" style="font-size:15px;color:'+vrColor+'">'+vrStr+'</div></div>';
    html += '</div>';

    // 涨跌分布
    var br = d.live_breadth || {};
    var bt = br['_total'] || 0;
    if (bt > 0) {
      var upCats = ['涨停', '>7%', '5~7%', '3~5%', '0~3%'];
      var dnCats = ['-0~-3%', '-3~-5%', '-5~-7%', '<-7%', '跌停'];
      var upColors = ['#ff2d55', '#ff3b30', '#ff6b6b', '#ff8a80', '#ffcdd2'];
      var dnColors = ['#b9f5d8', '#7bed9f', '#2ed573', '#1abc4e', '#0a8f32'];
      var allCats = upCats.concat(dnCats);
      var allColors = upColors.concat(dnColors);
      html += '<div style="margin-top:var(--sp-sm);display:flex;align-items:center;gap:2px;height:14px">';
      allCats.forEach(function(cat, i) {
        var n = br[cat] || 0;
        var pct = (n / bt * 100);
        if (pct > 0.5) {
          html += '<div title="' + cat + ': ' + n + '只 (' + pct.toFixed(1) + '%)" style="width:' + pct.toFixed(1) + '%;height:100%;background:' + allColors[i] + ';border-radius:1px;cursor:pointer;min-width:2px"></div>';
        }
      });
      html += '</div>';
      html += '<div style="display:flex;justify-content:space-between;font-size:8px;color:var(--text-disabled);margin-top:1px">';
      upCats.forEach(function(c) { html += '<span>' + (br[c]||0) + '</span>'; });
      html += '<span style="width:4px"></span>';
      dnCats.forEach(function(c) { html += '<span>' + (br[c]||0) + '</span>'; });
      html += '<span style="color:var(--text-secondary);font-weight:600">共' + bt + '只</span>';
      html += '</div>';
    }

    // 昨日收盘基线（来自TDX日线）
    var yb = d.yesterday_baseline || {};
    var yestIndexes = [
      {name:'上证', chg:yb['上证昨涨幅']||'—', amt:yb['上证昨成交额']||'—', up:yb['上证昨上涨'], dn:yb['上证昨下跌']},
      {name:'深证', chg:yb['深证昨涨幅']||'—', amt:yb['深证昨成交额']||'—', up:yb['深证昨上涨'], dn:yb['深证昨下跌']},
      {name:'创业', chg:yb['创业昨涨幅']||'—', amt:yb['创业昨成交额']||'—', up:yb['创业昨上涨'], dn:yb['创业昨下跌']}
    ];
    html += '<div style="margin-top:var(--sp-md);padding-top:var(--sp-sm);border-top:1px solid var(--border-light)">' +
      '<div class="kpi-label" style="margin-bottom:var(--sp-xs);color:var(--text-secondary);font-size:12px">昨日收盘基线</div>';
    html += '<div style="display:flex;flex-wrap:wrap;gap:var(--sp-xs) var(--sp-lg);font-size:12px">';
    yestIndexes.forEach(function(yi) {
      var ydir = yi.chg.charAt(0) === '+' ? 'up' : yi.chg.charAt(0) === '-' ? 'down' : '';
      html += '<span><strong style="color:var(--text-primary)">' + yi.name + '</strong> <span style="color:var(--' + ydir + ')">' + yi.chg + '</span> <span style="color:var(--text-secondary)">成交' + yi.amt + '</span>';
      if (yi.up != null && yi.dn != null) {
        html += ' <span style="color:var(--up)">' + yi.up + '</span>/<span style="color:var(--down)">' + yi.dn + '</span>';
      }
      html += '</span>';
    });
    html += '</div></div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W04', MarketOverviewWidget);
