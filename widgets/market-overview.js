// widgets/market-overview.js — W04 市场全景 v2.5 (品牌级视觉升级)
'use strict';

function _w04Esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

class MarketOverviewWidget extends YiMuWidget {
  constructor(config) {
    super(config);
    this._baselineOpen = false;
  }

  render(data) {
    var body = this.getBody();
    if (!body) return;
    var d = data || {};
    var li = d.live_index || {};
    var m = d.market || {};
    var yb = d.yesterday_baseline || {};

    var html = '<div class="w04-board">';

    // === E3 Evidence anchor ===
    html += '<div class="w04-title"><span class="evidence-inline-ref">E3</span>市场全景</div>';

    // === 顶层行：三大指数 KPI (紧凑，视觉吸睛) ===
    html += '<div class="w04-index-grid">';
    [
      {name:'上证', price:li['上证指数']||'—', chg:String(li['上证指数涨幅']||'—')},
      {name:'深证', price:li['深证指数']||'—', chg:String(li['深证指数涨幅']||'—')},
      {name:'创业', price:li['创业指数']||'—', chg:String(li['创业指数涨幅']||'—')}
    ].forEach(function(idx) {
      var dir = idx.chg.charAt(0) === '+' ? 'up' : idx.chg.charAt(0) === '-' ? 'down' : '';
      var pctNum = parseFloat(idx.chg.replace('+','').replace('%',''));
      var arrow = pctNum > 0 ? '▲' : pctNum < 0 ? '▼' : '—';
      html += '<div class="kpi-card w04-index-card">' +
        '<div class="kpi-label">' + _w04Esc(idx.name) + '</div>' +
        '<div class="kpi-value ' + dir + '">' + _w04Esc(idx.price) + '</div>' +
        '<div class="kpi-verdict ' + dir + '">' + _w04Esc(arrow + ' ' + idx.chg) + '</div>' +
        '</div>';
    });
    html += '</div>';

    // === 第二行：关键指标 (4 个紧凑卡片) ===
    var amtCompare = buildW04AmountCompare(li, yb, new Date());
    var amtCompareText = amtCompare.text;
    var amtDir = amtCompare.dir;
    var upCnt = li['上涨家数'];
    var dnCnt = li['下跌家数'];
    var udHtml = (upCnt != null && dnCnt != null)
      ? '<span class="up">' + _w04Esc(upCnt) + '</span>/<span class="down">' + _w04Esc(dnCnt) + '</span>'
      : _w04Esc(m['涨跌比'] || '—');
    var amp = li['上证指数振幅'] || '—';
    var iw = d.iwencai || {};
    var iwUsable = isW04IwencaiUsable(iw);
    var sent = d.sentiment || {};
    var br = d.live_breadth || d.breadth || {};
    var limitCounts = buildW04LimitCounts(iw, iwUsable, d.limit_counts || {}, d.hot_list || {}, br);
    var zt = limitCounts.zt;
    var dt = limitCounts.dt;

    html += '<div class="w04-metric-grid">';
    html += '<div class="kpi-card w04-metric-card"><div class="kpi-label">成交额</div><div class="kpi-value">'+_w04Esc(li['成交额']||'—')+'</div>'+(amtCompareText?'<div class="kpi-verdict ' + amtDir + '">' + _w04Esc(amtCompareText) + '</div>':'')+'</div>';
    html += '<div class="kpi-card w04-metric-card"><div class="kpi-label">涨跌比</div><div class="kpi-value">'+udHtml+'</div></div>';
    html += '<div class="kpi-card w04-metric-card"><div class="kpi-label">振幅</div><div class="kpi-value warn">'+_w04Esc(amp)+'</div></div>';
    html += '<div class="kpi-card w04-metric-card"><div class="kpi-label">涨跌停</div><div class="kpi-value"><span class="up">'+_w04Esc(zt!=null?zt:'—')+'</span>/<span class="down">'+_w04Esc(dt!=null?dt:'—')+'</span></div></div>';
    html += '</div>';

    // === 涨跌分布条 (更宽，更醒目) ===
    var bt = br['_total'] || 0;
    if (bt > 0) {
      var isCoarseBreadth = br['_source'] === 'live_index_fallback';
      var upCats = ['涨停', '>7%', '5~7%', '3~5%', '0~3%'];
      var dnCats = ['-0~-3%', '-3~-5%', '-5~-7%', '<-7%', '跌停'];
      var upColors = ['#DC2626', '#EF4444', '#F87171', '#FCA5A5', '#FEE2E2'];
      var dnColors = ['#D1FAE5', '#A7F3D0', '#6EE7B7', '#34D399', '#059669'];
      var allCats = upCats.concat(dnCats);
      var allColors = upColors.concat(dnColors);
      html += '<div class="w04-breadth">';
      if (isCoarseBreadth) {
        var coarseUp = li['上涨家数'] != null ? li['上涨家数'] : (br['0~3%'] || 0);
        var coarseDn = li['下跌家数'] != null ? li['下跌家数'] : (br['-0~-3%'] || 0);
        var coarseTotal = Math.max(coarseUp + coarseDn, 1);
        var upPct = coarseUp / coarseTotal * 100;
        var dnPct = coarseDn / coarseTotal * 100;
        html += '<div class="w04-breadth-bar">';
        if (upPct > 0) html += '<div class="w04-breadth-seg w04-breadth-up" title="上涨: '+_w04Esc(coarseUp)+'" style="width:'+upPct.toFixed(1)+'%"></div>';
        if (dnPct > 0) html += '<div class="w04-breadth-seg w04-breadth-down" title="下跌: '+_w04Esc(coarseDn)+'" style="width:'+dnPct.toFixed(1)+'%"></div>';
        html += '</div>';
        html += '<div class="w04-breadth-labels w04-breadth-labels-compact">'+
          '<span class="up">涨 '+_w04Esc(coarseUp)+'</span>'+
          '<span class="down">跌 '+_w04Esc(coarseDn)+'</span>'+
          '</div>';
      } else {
        // 色条
        html += '<div class="w04-breadth-bar w04-breadth-bar-full">';
        allCats.forEach(function(cat, i) {
          var n = br[cat] || 0;
          var pct = (n / bt * 100);
          if (pct > 0.3) {
            html += '<div class="w04-breadth-seg" title="' + _w04Esc(cat + ': ' + n + ' (' + pct.toFixed(1) + '%)') + '" style="width:' + pct.toFixed(1) + '%;background:' + allColors[i] + '"></div>';
          }
        });
        html += '</div>';
        // 计数标签
        html += '<div class="w04-breadth-labels">';
        upCats.forEach(function(c) { html += '<span>' + _w04Esc(br[c]||0) + '</span>'; });
        html += '<span class="w04-breadth-gap"></span>';
        dnCats.forEach(function(c) { html += '<span>' + _w04Esc(br[c]||0) + '</span>'; });
        html += '<span class="w04-breadth-total">' + _w04Esc(bt) + '只</span>';
        html += '</div>';
      }
      html += '</div>';
    }

    // === 第三行：实时情绪（iwencai 2min 轮询）===
    var iw = d.iwencai || {};
    var hasLiveIwencai = !!iw['_updated'] && isW04IwencaiUsable(iw);
    var upCnt2 = li['上涨家数'];
    var dnCnt2 = li['下跌家数'];
    var emotionVal = (upCnt2 != null && dnCnt2 != null && upCnt2 + dnCnt2 > 0)
      ? Math.round(upCnt2 / (upCnt2 + dnCnt2) * 100) : null;
    html += '<div class="w04-metric-grid">';
    var emotionDisplay = emotionVal != null ? emotionVal + '%' : (sent['情绪值'] != null ? sent['情绪值'] + '%' : '—');
    html += '<div class="kpi-card w04-metric-card"><div class="kpi-label">情绪值</div><div class="kpi-value">'+ _w04Esc(emotionDisplay) +'</div></div>';
    var ztVal = pickW04Return(iw, '昨日涨停收益', sent['昨日涨停收益'], hasLiveIwencai);
    var ztCls = (ztVal != null && !isNaN(parseFloat(ztVal)) && parseFloat(ztVal) > 0) ? 'up' : (ztVal != null && !isNaN(parseFloat(ztVal)) && parseFloat(ztVal) < 0) ? 'down' : '';
    html += '<div class="kpi-card w04-metric-card"><div class="kpi-label">昨停今日</div><div class="kpi-value'+(ztCls?' '+ztCls:'')+'">'+ _w04Esc(formatW04Pct(ztVal)) +'</div></div>';
    var lbVal = pickW04Return(iw, '连板收益', sent['连板收益'], hasLiveIwencai);
    var lbCls = (lbVal != null && !isNaN(parseFloat(lbVal)) && parseFloat(lbVal) > 0) ? 'up' : (lbVal != null && !isNaN(parseFloat(lbVal)) && parseFloat(lbVal) < 0) ? 'down' : '';
    html += '<div class="kpi-card w04-metric-card"><div class="kpi-label">连板今日</div><div class="kpi-value'+(lbCls?' '+lbCls:'')+'">'+ _w04Esc(formatW04Pct(lbVal)) +'</div></div>';
    var zbVal = pickW04Return(iw, '炸板收益', sent['昨日炸板收益'], hasLiveIwencai);
    var zbCls = (zbVal != null && !isNaN(parseFloat(zbVal)) && parseFloat(zbVal) > 0) ? 'up' : (zbVal != null && !isNaN(parseFloat(zbVal)) && parseFloat(zbVal) < 0) ? 'down' : '';
    html += '<div class="kpi-card w04-metric-card"><div class="kpi-label">炸板今日</div><div class="kpi-value'+(zbCls?' '+zbCls:'')+'">'+ _w04Esc(formatW04Pct(zbVal)) +'</div></div>';
    html += '</div>';

    // === 北向资金 (60s 实时) ===
    var nb = d.northbound || {};
    if (nb.hgt_yi != null || nb.sgt_yi != null) {
      var hgt = nb.hgt_yi || 0;
      var sgt = nb.sgt_yi || 0;
      var total_nb = hgt + sgt;
      var nbCls = total_nb >= 0 ? 'up' : 'down';
      var nbSign = total_nb >= 0 ? '+' : '';
      html += '<div class="w04-northbound-row">' +
        '<div class="kpi-card w04-northbound-card">' +
        '<span class="w04-northbound-label">北向资金</span> ' +
        '<span class="' + nbCls + '">' + _w04Esc(nbSign + total_nb.toFixed(1) + '亿') + '</span>' +
        '</div></div>';
    }

    // === 昨日收盘基线 (折叠式，点击展开) ===
    var yestIndexes = [
      {name:'上证', chg:yb['上证昨涨幅']||'—', amt:formatW04AmountText(yb['上证昨成交额']), up:yb['上证昨上涨'], dn:yb['上证昨下跌']},
      {name:'深证', chg:yb['深证昨涨幅']||'—', amt:formatW04AmountText(yb['深证昨成交额']), up:yb['深证昨上涨'], dn:yb['深证昨下跌']},
      {name:'创业', chg:yb['创业昨涨幅']||'—', amt:formatW04AmountText(yb['创业昨成交额']), up:yb['创业昨上涨'], dn:yb['创业昨下跌']}
    ];
    var yestBody = '';
      yestIndexes.forEach(function(yi) {
        var ydir = yi.chg.charAt(0) === '+' ? 'up' : yi.chg.charAt(0) === '-' ? 'down' : '';
        yestBody += '<span class="w04-baseline-pill">' +
          '<strong>' + _w04Esc(yi.name) + '</strong> ' +
          '<span class="' + ydir + '">' + _w04Esc(yi.chg) + '</span>' +
          '<span>' + _w04Esc(yi.amt) + '</span>';
        if (yi.up != null && yi.dn != null) {
          yestBody += ' <span class="up">' + _w04Esc(yi.up) + '</span>/<span class="down">' + _w04Esc(yi.dn) + '</span>';
        }
        yestBody += '</span>';
      });

      html += '<div class="w04-baseline">' +
        '<div id="w04_baseline_toggle" class="w04-baseline-toggle">' +
        '<span id="w04_baseline_arrow" class="w04-baseline-arrow">▶</span> 昨日收盘基线</div>' +
        '<div id="w04_baseline_body" class="w04-baseline-body">' + yestBody + '</div>' +
        '</div>';

    html += '</div>';

    body.innerHTML = html;
    this.updateTimestamp();

    // 绑定基线折叠（DOM 随 render 重建，用 onclick 天然防重复绑定）
    var toggle = body.querySelector('#w04_baseline_toggle');
    var arrow = body.querySelector('#w04_baseline_arrow');
    var bBody = body.querySelector('#w04_baseline_body');
    if (toggle && bBody) {
      if (this._baselineOpen) bBody.style.display = 'flex';
      toggle.onclick = function() {
        bBody.style.display = bBody.style.display === 'none' ? 'flex' : 'none';
        this._baselineOpen = bBody.style.display !== 'none';
        if (arrow) arrow.style.transform = bBody.style.display !== 'none' ? 'rotate(90deg)' : '';
      }.bind(this);
    }
  }

  _card(title, bodyContent) {
    return '<div style="background:var(--bg-base);border-radius:var(--radius-md);padding:var(--sp-xs) var(--sp-sm)">' +
      '<div style="font-size:var(--fs-label);font-weight:600;color:var(--text-primary);margin-bottom:var(--sp-xs);padding-bottom:2px;border-bottom:1px solid var(--border-light)">'+title+'</div>' +
      bodyContent + '</div>';
  }
}

function parseAmountYi(v) {
  var s = String(v || '').replace(/,/g, '').trim();
  if (!s || s === '—') return 0;
  if (s.indexOf('万亿') >= 0) {
    var w = parseFloat(s.replace('万亿', ''));
    if (!isFinite(w)) return 0;
    return w > 1000 ? w / 100000000 : w * 10000;
  }
  if (s.indexOf('亿') >= 0) return parseFloat(s.replace('亿', '')) || 0;
  return (parseFloat(s) || 0) / 100000000;
}

function formatW04AmountText(v) {
  if (v == null || v === '' || v === '—') return '—';
  var yi = parseAmountYi(v);
  if (yi <= 0) return String(v);
  if (Math.abs(yi) >= 10000) {
    return (yi / 10000).toFixed(2).replace(/\.00$/, '') + '万亿';
  }
  return yi.toFixed(0) + '亿';
}

function hasW04Own(obj, key) {
  return Object.prototype.hasOwnProperty.call(obj || {}, key);
}

function isW04IwencaiUsable(iw) {
  var level = iw && iw._freshness && iw._freshness.level;
  return level !== 'dead';
}

function parseW04Count(v) {
  if (v == null || v === '') return null;
  if (typeof v === 'number') return isFinite(v) ? v : null;
  var n = parseInt(String(v).replace(/[^\d-]/g, ''), 10);
  return isNaN(n) ? null : n;
}

function pickW04HotLimitUp(hotList) {
  hotList = hotList || {};
  var count = parseW04Count(hotList.zt_count);
  if (count != null && count > 0) return count;
  if (Array.isArray(hotList.zt_stocks) && hotList.zt_stocks.length > 0) return hotList.zt_stocks.length;
  return null;
}

function pickW04HotLimitDown(hotList) {
  hotList = hotList || {};
  if (hotList._limit_source !== 'eastmoney_zt_pool') return null;
  return parseW04Count(hotList.dt_count);
}

function pickW04LimitCount(limitCounts, key) {
  limitCounts = limitCounts || {};
  if (!hasW04Own(limitCounts, key)) return null;
  return parseW04Count(limitCounts[key]);
}

function pickW04BreadthLimitCount(br, key) {
  br = br || {};
  if (br._source === 'live_index_fallback') return null;
  if (!hasW04Own(br, key)) return null;
  return parseW04Count(br[key]);
}

function buildW04LimitCounts(iw, iwUsable, limitCounts, hotList, br) {
  var zt = pickW04LimitCount(limitCounts, '涨停家数');
  var dt = pickW04LimitCount(limitCounts, '跌停家数');
  if (iwUsable !== false) {
    if (zt == null && hasW04Own(iw, '涨停家数')) zt = parseW04Count(iw['涨停家数']);
    if (dt == null && hasW04Own(iw, '跌停家数')) dt = parseW04Count(iw['跌停家数']);
  }
  if (zt == null) zt = pickW04HotLimitUp(hotList);
  if (dt == null) dt = pickW04HotLimitDown(hotList);
  if (zt == null) zt = pickW04BreadthLimitCount(br, '涨停');
  if (dt == null) dt = pickW04BreadthLimitCount(br, '跌停');
  return { zt: zt, dt: dt };
}

function pickW04Return(liveObj, key, fallback, hasLiveIwencai) {
  if (hasLiveIwencai && hasW04Own(liveObj, key)) return liveObj[key];
  return hasLiveIwencai ? null : fallback;
}

function formatW04Pct(v) {
  if (v == null || v === '' || v === '—') return '—';
  var n = parseFloat(String(v).replace('%', '').replace('+', ''));
  if (isNaN(n)) return String(v);
  return (n > 0 ? '+' : '') + n + '%';
}

function getTradeElapsedRatio(now) {
  var minutes = now.getHours() * 60 + now.getMinutes();
  var open = 9 * 60 + 30;
  var morningClose = 11 * 60 + 30;
  var afternoonOpen = 13 * 60;
  var close = 15 * 60;
  var traded = 0;
  if (minutes <= open) traded = 0;
  else if (minutes <= morningClose) traded = minutes - open;
  else if (minutes < afternoonOpen) traded = 120;
  else if (minutes <= close) traded = 120 + minutes - afternoonOpen;
  else traded = 240;
  return Math.max(1, Math.min(240, traded)) / 240;
}

function buildW04AmountCompare(li, yb, now) {
  li = li || {};
  yb = yb || {};
  var backend = buildW04BackendAmountCompare(li);
  if (backend.text) return backend;

  var todayAmtYi = parseAmountYi(li['成交额']);
  if (todayAmtYi <= 0) return { text: '', dir: '' };

  var minutes = now.getHours() * 60 + now.getMinutes();
  var lunchStart = 11 * 60 + 30;
  var afternoonOpen = 13 * 60;
  var close = 15 * 60;
  var yestSameYi = 0;
  var label = '昨同段';

  if (minutes >= lunchStart && minutes < afternoonOpen) {
    yestSameYi = parseAmountYi(yb['昨日午间成交额'] || yb['午盘昨成交额']);
    label = '昨午盘';
  } else if (minutes >= close) {
    yestSameYi = parseAmountYi(yb['昨日全天成交额'] || yb['上证昨成交额']);
    label = '昨收';
  }

  if (yestSameYi <= 0) return { text: '', dir: '' };
  return formatW04AmountCompare(todayAmtYi - yestSameYi, yestSameYi, label);
}

function buildW04BackendAmountCompare(li) {
  var totalDiff = 0;
  var totalYest = 0;
  var count = 0;
  ['上证', '深证'].forEach(function(name) {
    var diff = parseAmountYi(li[name + '成交额差']);
    var yest = parseAmountYi(li[name + '昨成交额']);
    if (yest > 0 && diff !== 0) {
      totalDiff += diff;
      totalYest += yest;
      count += 1;
    }
  });
  if (count >= 2 && totalYest > 0) {
    return formatW04AmountCompare(totalDiff, totalYest, '昨同段');
  }
  return { text: '', dir: '' };
}

function formatW04AmountCompare(diffYi, baseYi, label) {
  var pct = baseYi > 0 ? diffYi / baseYi * 100 : null;
  var signPct = pct >= 0 ? '+' : '';
  return {
    text: label + ' ' + formatAmtDiff(diffYi) + (pct == null ? '' : ' ' + signPct + pct.toFixed(1) + '%'),
    dir: diffYi >= 0 ? 'up' : 'down'
  };
}

function formatAmtDiff(v) {
  if (Math.abs(v) >= 10000) return (v >= 0 ? '+' : '') + (v / 10000).toFixed(2) + '万亿';
  return (v >= 0 ? '+' : '') + v.toFixed(0) + '亿';
}

WidgetRegistry.register('W04', MarketOverviewWidget);
