// widgets/market-overview.js — W04 市场全景 v2.5 (品牌级视觉升级)
'use strict';

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

    var html = '<div style="display:flex;flex-direction:column;gap:6px;height:100%">';

    // === 顶层行：三大指数 KPI (紧凑，视觉吸睛) ===
    html += '<div style="display:flex;gap:6px">';
    [
      {name:'上证', price:li['上证指数']||'—', chg:String(li['上证指数涨幅']||'—')},
      {name:'深证', price:li['深证指数']||'—', chg:String(li['深证指数涨幅']||'—')},
      {name:'创业', price:li['创业指数']||'—', chg:String(li['创业指数涨幅']||'—')}
    ].forEach(function(idx) {
      var dir = idx.chg.charAt(0) === '+' ? 'up' : idx.chg.charAt(0) === '-' ? 'down' : '';
      var pctNum = parseFloat(idx.chg.replace('+','').replace('%',''));
      var arrow = pctNum > 0 ? '▲' : pctNum < 0 ? '▼' : '—';
      html += '<div class="kpi-card" style="flex:1;padding:8px 10px">' +
        '<div class="kpi-label" style="margin-bottom:2px">' + idx.name + '</div>' +
        '<div class="kpi-value ' + dir + '" style="font-size:20px">' + idx.price + '</div>' +
        '<div class="kpi-verdict ' + dir + '">' + arrow + ' ' + idx.chg + '</div>' +
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
      ? '<span class="up">' + upCnt + '</span>/<span class="down">' + dnCnt + '</span>'
      : (m['涨跌比'] || '—');
    var amp = li['上证指数振幅'] || '—';
    var iw = d.iwencai || {};
    var iwUsable = isW04IwencaiUsable(iw);
    var sent = d.sentiment || {};
    var zt = pickW04LiveFirst(iw, '涨停家数', m['涨停家数'], iwUsable);
    var dt = pickW04LiveFirst(iw, '跌停家数', m['跌停家数'], iwUsable);

    html += '<div style="display:flex;gap:6px">';
    html += '<div class="kpi-card" style="flex:1;padding:6px 8px"><div class="kpi-label">成交额</div><div class="kpi-value" style="font-size:14px">'+(li['成交额']||'—')+'</div>'+(amtCompareText?'<div class="kpi-verdict ' + amtDir + '">' + amtCompareText + '</div>':'')+'</div>';
    html += '<div class="kpi-card" style="flex:1;padding:6px 8px"><div class="kpi-label">涨跌比</div><div class="kpi-value" style="font-size:14px">'+udHtml+'</div></div>';
    html += '<div class="kpi-card" style="flex:1;padding:6px 8px"><div class="kpi-label">振幅</div><div class="kpi-value" style="font-size:14px;color:var(--warn)">'+amp+'</div></div>';
    html += '<div class="kpi-card" style="flex:1;padding:6px 8px"><div class="kpi-label">涨跌停</div><div class="kpi-value" style="font-size:14px"><span class="up">'+(zt!=null?zt:'—')+'</span>/<span class="down">'+(dt!=null?dt:'—')+'</span></div></div>';
    html += '</div>';

    // === 涨跌分布条 (更宽，更醒目) ===
    var br = d.live_breadth || d.breadth || {};
    var bt = br['_total'] || 0;
    if (bt > 0) {
      var isCoarseBreadth = br['_source'] === 'live_index_fallback';
      var upCats = ['涨停', '>7%', '5~7%', '3~5%', '0~3%'];
      var dnCats = ['-0~-3%', '-3~-5%', '-5~-7%', '<-7%', '跌停'];
      var upColors = ['#DC2626', '#EF4444', '#F87171', '#FCA5A5', '#FEE2E2'];
      var dnColors = ['#D1FAE5', '#A7F3D0', '#6EE7B7', '#34D399', '#059669'];
      var allCats = upCats.concat(dnCats);
      var allColors = upColors.concat(dnColors);
      html += '<div style="flex:1;display:flex;flex-direction:column;justify-content:center">';
      if (isCoarseBreadth) {
        var coarseUp = li['上涨家数'] != null ? li['上涨家数'] : (br['0~3%'] || 0);
        var coarseDn = li['下跌家数'] != null ? li['下跌家数'] : (br['-0~-3%'] || 0);
        var coarseTotal = Math.max(coarseUp + coarseDn, 1);
        var upPct = coarseUp / coarseTotal * 100;
        var dnPct = coarseDn / coarseTotal * 100;
        html += '<div style="display:flex;align-items:center;height:16px;border-radius:3px;overflow:hidden;background:var(--bg-base)">';
        if (upPct > 0) html += '<div title="上涨: '+coarseUp+'" style="width:'+upPct.toFixed(1)+'%;height:100%;background:#DC2626"></div>';
        if (dnPct > 0) html += '<div title="下跌: '+coarseDn+'" style="width:'+dnPct.toFixed(1)+'%;height:100%;background:#059669"></div>';
        html += '</div>';
        html += '<div style="display:flex;align-items:center;gap:8px;font-size:9px;color:var(--text-secondary);margin-top:3px">'+
          '<span class="up" style="font-weight:700">涨 '+coarseUp+'</span>'+
          '<span class="down" style="font-weight:700">跌 '+coarseDn+'</span>'+
          '</div>';
      } else {
        // 色条
        html += '<div style="display:flex;align-items:center;gap:1px;height:16px;border-radius:3px;overflow:hidden">';
        allCats.forEach(function(cat, i) {
          var n = br[cat] || 0;
          var pct = (n / bt * 100);
          if (pct > 0.3) {
            html += '<div title="' + cat + ': ' + n + ' (' + pct.toFixed(1) + '%)" style="width:' + pct.toFixed(1) + '%;height:100%;background:' + allColors[i] + ';cursor:pointer;min-width:2px;transition:opacity .15s" onmouseover="this.style.opacity=\'.7\'" onmouseout="this.style.opacity=\'1\'"></div>';
          }
        });
        html += '</div>';
        // 计数标签
        html += '<div style="display:flex;justify-content:space-between;font-size:8px;color:var(--text-disabled);margin-top:2px">';
        upCats.forEach(function(c) { html += '<span>' + (br[c]||0) + '</span>'; });
        html += '<span style="width:6px"></span>';
        dnCats.forEach(function(c) { html += '<span>' + (br[c]||0) + '</span>'; });
        html += '<span style="color:var(--text-secondary);font-weight:600">' + bt + '只</span>';
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
    html += '<div style="display:flex;gap:6px">';
    var emotionDisplay = emotionVal != null ? emotionVal + '%' : (sent['情绪值'] != null ? sent['情绪值'] + '%' : '—');
    html += '<div class="kpi-card" style="flex:1;padding:6px 8px"><div class="kpi-label">情绪值</div><div class="kpi-value" style="font-size:14px">'+ emotionDisplay +'</div></div>';
    var ztVal = pickW04Return(iw, '昨日涨停收益', sent['昨日涨停收益'], hasLiveIwencai);
    var ztCls = (ztVal != null && !isNaN(parseFloat(ztVal)) && parseFloat(ztVal) > 0) ? 'up' : (ztVal != null && !isNaN(parseFloat(ztVal)) && parseFloat(ztVal) < 0) ? 'down' : '';
    html += '<div class="kpi-card" style="flex:1;padding:6px 8px"><div class="kpi-label">昨停今日</div><div class="kpi-value'+(ztCls?' '+ztCls:'')+'" style="font-size:14px">'+ formatW04Pct(ztVal) +'</div></div>';
    var lbVal = pickW04Return(iw, '连板收益', sent['连板收益'], hasLiveIwencai);
    var lbCls = (lbVal != null && !isNaN(parseFloat(lbVal)) && parseFloat(lbVal) > 0) ? 'up' : (lbVal != null && !isNaN(parseFloat(lbVal)) && parseFloat(lbVal) < 0) ? 'down' : '';
    html += '<div class="kpi-card" style="flex:1;padding:6px 8px"><div class="kpi-label">连板今日</div><div class="kpi-value'+(lbCls?' '+lbCls:'')+'" style="font-size:14px">'+ formatW04Pct(lbVal) +'</div></div>';
    var zbVal = pickW04Return(iw, '炸板收益', sent['昨日炸板收益'], hasLiveIwencai);
    var zbCls = (zbVal != null && !isNaN(parseFloat(zbVal)) && parseFloat(zbVal) > 0) ? 'up' : (zbVal != null && !isNaN(parseFloat(zbVal)) && parseFloat(zbVal) < 0) ? 'down' : '';
    html += '<div class="kpi-card" style="flex:1;padding:6px 8px"><div class="kpi-label">炸板今日</div><div class="kpi-value'+(zbCls?' '+zbCls:'')+'" style="font-size:14px">'+ formatW04Pct(zbVal) +'</div></div>';
    html += '</div>';

    // === 北向资金 (60s 实时) ===
    var nb = d.northbound || {};
    if (nb.hgt_yi != null || nb.sgt_yi != null) {
      var hgt = nb.hgt_yi || 0;
      var sgt = nb.sgt_yi || 0;
      var total_nb = hgt + sgt;
      var nbCls = total_nb >= 0 ? 'up' : 'down';
      var nbSign = total_nb >= 0 ? '+' : '';
      html += '<div style="display:flex;gap:6px;padding:4px 0">' +
        '<div class="kpi-card" style="flex:1;padding:4px 8px">' +
        '<span style="font-size:9px;color:var(--text-disabled)">北向资金</span> ' +
        '<span class="' + nbCls + '" style="font-weight:600;font-size:14px">' + nbSign + total_nb.toFixed(1) + '亿</span>' +
        '</div></div>';
    }

    // === 昨日收盘基线 (折叠式，点击展开) ===
    var yestIndexes = [
      {name:'上证', chg:yb['上证昨涨幅']||'—', amt:yb['上证昨成交额']||'—', up:yb['上证昨上涨'], dn:yb['上证昨下跌']},
      {name:'深证', chg:yb['深证昨涨幅']||'—', amt:yb['深证昨成交额']||'—', up:yb['深证昨上涨'], dn:yb['深证昨下跌']},
      {name:'创业', chg:yb['创业昨涨幅']||'—', amt:yb['创业昨成交额']||'—', up:yb['创业昨上涨'], dn:yb['创业昨下跌']}
    ];
    var yestBody = '';
      yestIndexes.forEach(function(yi) {
        var ydir = yi.chg.charAt(0) === '+' ? 'up' : yi.chg.charAt(0) === '-' ? 'down' : '';
        yestBody += '<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;background:var(--bg-base);border-radius:4px;font-size:11px">' +
          '<strong style="color:var(--text-primary);font-size:12px">' + yi.name + '</strong> ' +
          '<span class="' + ydir + '" style="font-weight:600">' + yi.chg + '</span>' +
          '<span style="color:var(--text-disabled)">' + yi.amt + '</span>';
        if (yi.up != null && yi.dn != null) {
          yestBody += ' <span class="up">' + yi.up + '</span>/<span class="down">' + yi.dn + '</span>';
        }
        yestBody += '</span>';
      });

      html += '<div style="border-top:1px solid var(--border-light);padding-top:4px">' +
        '<div id="w04_baseline_toggle" style="display:flex;align-items:center;gap:4px;cursor:pointer;user-select:none;font-size:9px;color:var(--text-disabled);text-transform:uppercase;letter-spacing:0.5px">' +
        '<span style="font-size:8px;transition:transform .2s;transform:rotate(90deg)" id="w04_baseline_arrow">▶</span> 昨日收盘基线</div>' +
        '<div id="w04_baseline_body" style="display:flex;margin-top:4px;gap:6px;flex-wrap:wrap">' + yestBody + '</div>' +
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
  if (s.indexOf('万亿') >= 0) return parseFloat(s.replace('万亿', '')) * 10000 || 0;
  if (s.indexOf('亿') >= 0) return parseFloat(s.replace('亿', '')) || 0;
  return (parseFloat(s) || 0) / 100000000;
}

function hasW04Own(obj, key) {
  return Object.prototype.hasOwnProperty.call(obj || {}, key);
}

function isW04IwencaiUsable(iw) {
  var level = iw && iw._freshness && iw._freshness.level;
  return level !== 'dead';
}

function pickW04LiveFirst(liveObj, key, fallback, liveUsable) {
  if (liveUsable !== false && hasW04Own(liveObj, key)) return liveObj[key];
  return fallback != null ? fallback : null;
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
