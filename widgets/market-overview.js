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
    var amtDiff = li['上证成交额差'] || '';
    var amtPct = li['上证成交额差百分比'] || '';
    var amtDir = amtDiff.charAt(0) === '+' ? 'up' : amtDiff.charAt(0) === '-' ? 'down' : '';
    var upCnt = li['上涨家数'];
    var dnCnt = li['下跌家数'];
    var udHtml = (upCnt != null && dnCnt != null)
      ? '<span class="up">' + upCnt + '</span>/<span class="down">' + dnCnt + '</span>'
      : (m['涨跌比'] || '—');
    var amp = li['上证指数振幅'] || '—';
    var iw = d.iwencai || {};
    var zt = iw['涨停家数'];
    var dt = iw['跌停家数'];

    html += '<div style="display:flex;gap:6px">';
    html += '<div class="kpi-card" style="flex:1;padding:6px 8px"><div class="kpi-label">成交额</div><div class="kpi-value" style="font-size:14px">'+(li['成交额']||'—')+'</div>'+(amtPct?'<div class="kpi-verdict ' + amtDir + '">较昨日此时 '+amtPct+'</div>':'')+'</div>';
    html += '<div class="kpi-card" style="flex:1;padding:6px 8px"><div class="kpi-label">涨跌比</div><div class="kpi-value" style="font-size:14px">'+udHtml+'</div></div>';
    html += '<div class="kpi-card" style="flex:1;padding:6px 8px"><div class="kpi-label">振幅</div><div class="kpi-value" style="font-size:14px;color:var(--warn)">'+amp+'</div></div>';
    html += '<div class="kpi-card" style="flex:1;padding:6px 8px"><div class="kpi-label">涨跌停</div><div class="kpi-value" style="font-size:14px"><span class="up">'+(zt!=null?zt:'—')+'</span>/<span class="down">'+(dt!=null?dt:'—')+'</span></div></div>';
    html += '</div>';

    // === 涨跌分布条 (更宽，更醒目) ===
    var br = d.live_breadth || {};
    var bt = br['_total'] || 0;
    if (bt > 0) {
      var upCats = ['涨停', '>7%', '5~7%', '3~5%', '0~3%'];
      var dnCats = ['-0~-3%', '-3~-5%', '-5~-7%', '<-7%', '跌停'];
      var upColors = ['#DC2626', '#EF4444', '#F87171', '#FCA5A5', '#FEE2E2'];
      var dnColors = ['#D1FAE5', '#A7F3D0', '#6EE7B7', '#34D399', '#059669'];
      var allCats = upCats.concat(dnCats);
      var allColors = upColors.concat(dnColors);
      html += '<div style="flex:1;display:flex;flex-direction:column;justify-content:center">';
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
      html += '</div>';
    }

    // === 第三行：实时情绪（iwencai 2min 轮询）===
    var iw = d.iwencai || {};
    var upCnt2 = li['上涨家数'];
    var dnCnt2 = li['下跌家数'];
    var emotionVal = (upCnt2 != null && dnCnt2 != null && upCnt2 + dnCnt2 > 0)
      ? Math.round(upCnt2 / (upCnt2 + dnCnt2) * 100) : null;
    html += '<div style="display:flex;gap:6px">';
    html += '<div class="kpi-card" style="flex:1;padding:6px 8px"><div class="kpi-label">情绪值</div><div class="kpi-value" style="font-size:14px">'+ (emotionVal != null ? emotionVal + '%' : '—') +'</div></div>';
    var ztVal = iw['昨日涨停收益'];
    var ztCls = (ztVal != null && !isNaN(parseFloat(ztVal)) && parseFloat(ztVal) > 0) ? 'up' : (ztVal != null && !isNaN(parseFloat(ztVal)) && parseFloat(ztVal) < 0) ? 'down' : '';
    html += '<div class="kpi-card" style="flex:1;padding:6px 8px"><div class="kpi-label">涨停收益</div><div class="kpi-value'+(ztCls?' '+ztCls:'')+'" style="font-size:14px">'+ (ztVal != null ? (parseFloat(ztVal)>0?'+':'')+ztVal+'%' : '—') +'</div></div>';
    var lbVal = iw['连板收益'];
    var lbCls = (lbVal != null && !isNaN(parseFloat(lbVal)) && parseFloat(lbVal) > 0) ? 'up' : (lbVal != null && !isNaN(parseFloat(lbVal)) && parseFloat(lbVal) < 0) ? 'down' : '';
    html += '<div class="kpi-card" style="flex:1;padding:6px 8px"><div class="kpi-label">连板收益</div><div class="kpi-value'+(lbCls?' '+lbCls:'')+'" style="font-size:14px">'+ (lbVal != null ? (parseFloat(lbVal)>0?'+':'')+lbVal+'%' : '—') +'</div></div>';
    var zbVal = iw['炸板收益'];
    var zbCls = (zbVal != null && !isNaN(parseFloat(zbVal)) && parseFloat(zbVal) > 0) ? 'up' : (zbVal != null && !isNaN(parseFloat(zbVal)) && parseFloat(zbVal) < 0) ? 'down' : '';
    html += '<div class="kpi-card" style="flex:1;padding:6px 8px"><div class="kpi-label">炸板收益</div><div class="kpi-value'+(zbCls?' '+zbCls:'')+'" style="font-size:14px">'+ (zbVal != null ? (parseFloat(zbVal)>0?'+':'')+zbVal+'%' : '—') +'</div></div>';
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
    var yb = d.yesterday_baseline || {};
    var yestIndexes = [
      {name:'上证', chg:yb['上证昨涨幅']||'—', amt:yb['上证昨成交额']||'—', up:yb['上证昨上涨'], dn:yb['上证昨下跌']},
      {name:'深证', chg:yb['深证昨涨幅']||'—', amt:yb['深证昨成交额']||'—', up:yb['深证昨上涨'], dn:yb['深证昨下跌']},
      {name:'创业', chg:yb['创业昨涨幅']||'—', amt:yb['创业昨成交额']||'—', up:yb['创业昨上涨'], dn:yb['创业昨下跌']}
    ];
    var hasYest = yestIndexes.some(function(yi) { return yi.chg !== '—' || yi.amt !== '—'; });
    if (hasYest) {
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
        '<span style="font-size:8px;transition:transform .2s" id="w04_baseline_arrow">▶</span> 昨日收盘基线</div>' +
        '<div id="w04_baseline_body" style="display:none;margin-top:4px;gap:6px;flex-wrap:wrap">' + yestBody + '</div>' +
        '</div>';
    }

    // === LLM 研判卡槽 ===
    var llmHtml = '<span style="color:var(--text-disabled)">🤖 待研判</span>';
    try {
      var llmRaw = DataStore.manualData.getAll()['_llm_market'] || '';
      if (llmRaw) {
        llmHtml = '<span style="color:var(--info)">🤖 ' + (llmRaw.length > 150 ? llmRaw.substring(0, 150) + '...' : llmRaw) + '</span>';
      }
    } catch(e) {}
    html += '<div style="margin-top:4px;padding:3px 8px;background:var(--bg-base);border-radius:var(--radius-sm);font-size:var(--fs-body);border:1px dashed var(--border-light)" id="w04-llm-text">' + llmHtml + '</div>';

    html += '</div>';

    body.innerHTML = html;
    this.updateTimestamp();

    // 异步加载 LLM 研判
    this._loadLLM(body);

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

  _loadLLM(body) {
    var self = this;
    fetch('data/llm_insights.json?t=' + Date.now())
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) {
        if (!data) return;
        // 找今天的研判
        var today = new Date().toISOString().slice(0, 10);
        var keys = Object.keys(data).filter(function(k) { return k.indexOf(today) === 0; }).sort().reverse();
        var text = '';
        keys.forEach(function(k) {
          if (data[k] && data[k].text) text = data[k].text;
        });
        if (text) {
          var el = body.querySelector('#w04-llm-text');
          if (el) el.innerHTML = '🤖 ' + (text.length > 150 ? text.substring(0, 150) + '...' : text);
        }
      })
      .catch(function() {});
  }

  _card(title, bodyContent) {
    return '<div style="background:var(--bg-base);border-radius:var(--radius-md);padding:var(--sp-xs) var(--sp-sm)">' +
      '<div style="font-size:var(--fs-label);font-weight:600;color:var(--text-primary);margin-bottom:var(--sp-xs);padding-bottom:2px;border-bottom:1px solid var(--border-light)">'+title+'</div>' +
      bodyContent + '</div>';
  }
}

WidgetRegistry.register('W04', MarketOverviewWidget);
