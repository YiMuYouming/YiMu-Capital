// widgets/sentiment-dash.js — W05 情绪仪表盘 v3.0 (矩阵: 指标×5节点)
'use strict';

class SentimentDashWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var nodes = (data && data.sentiment_nodes) || {};
    var S = (data && data.sentiment) || {};
    var li = (data && data.live_index) || {};

    var NODES = ['竞价','早盘','午盘','尾盘','收盘'];

    // 过滤有实质数据的节点
    var isPlaceholder = function(v) {
      if (!v) return true;
      v = String(v);
      if (v === '—' || v === '%' || v === '亿' || v === '板') return true;
      if (v.indexOf('点位') >= 0 || v.indexOf('(%)') >= 0) return true;
      if (/^(好|一般|差)(\/(好|一般|差))+$/.test(v)) return true;
      if (/^(完整|断层)(\/(完整|断层))+$/.test(v)) return true;
      if (/^(竞价|早盘|午盘|尾盘|收盘)$/.test(v)) return true;
      return false;
    };
    var filledNodes = NODES.filter(function(n) {
      var nd = nodes[n] || {};
      return Object.keys(nd).filter(function(k) {
        return !isPlaceholder(nd[k]);
      }).length > 1;
    });

    if (filledNodes.length === 0) {
      this._renderBaseline(body, S, li);
      return;
    }

    var now = new Date();
    var min = now.getHours() * 60 + now.getMinutes();
    var curSeg = min < 570 ? '盘前' : min < 600 ? '竞价' : min < 690 ? '早盘' : min < 780 ? '午休' : min < 840 ? '午盘' : min < 900 ? '尾盘' : '收盘';
    var liveUp = li['上涨家数'];
    var liveDn = li['下跌家数'];

    // === 颜色逻辑 ===
    function cellCls(indKey, val) {
      var num = parseFloat(String(val).replace('%',''));
      if (isNaN(num)) return '';
      if (indKey === '炸板收益' || indKey === '炸板率') return num <= 0 ? 'up' : num > 2 ? 'down' : '';
      if (indKey === '涨停收益' || indKey === '连板收益') return num >= 2 ? 'up' : num >= 0 ? '' : 'down';
      if (indKey === '情绪') return num >= 40 && num <= 60 ? 'up' : num < 20 ? 'down' : '';
      return num > 0 ? 'up' : num < 0 ? 'down' : '';
    }

    // === 指标定义 ===
    var indicators = [
      {key:'情绪',     label:'情绪'},
      {key:'涨停收益', label:'涨停收益'},
      {key:'连板收益', label:'连板收益'},
      {key:'炸板收益', label:'炸板收益'},
      {key:'封板率',   label:'封板率'},
      {key:'炸板率',   label:'炸板率'},
      {key:'晋级率',   label:'晋级率'},
    ];

    var html = '';

    // === 顶部 ===
    html += '<div style="display:flex;align-items:center;gap:var(--sp-sm);margin-bottom:var(--sp-sm);padding:var(--sp-xs) var(--sp-md);background:var(--bg-base);border-radius:var(--radius-md)">' +
      '<span style="font-size:var(--fs-body);color:var(--text-secondary)">当前</span>' +
      '<span style="font-weight:700;color:var(--info)">' + curSeg + '</span>' +
      '<span style="color:var(--text-disabled)">|</span>';
    NODES.forEach(function(n) {
      var on = filledNodes.indexOf(n) >= 0;
      html += '<span style="font-size:var(--fs-body);font-weight:'+(on?'600':'400')+';color:'+(on?'var(--text-primary)':'var(--text-disabled)')+'">' + n + '</span>';
    });
    html += '<span style="margin-left:auto;display:flex;align-items:center;gap:var(--sp-sm)">' +
      '<button id="w05_refresh" style="font-size:var(--fs-label);padding:1px 8px;background:var(--info);color:var(--text-inverse);border:none;border-radius:3px;cursor:pointer">🔄 刷新</button>' +
      '<span style="font-size:var(--fs-body)">' +
        '<span style="color:var(--text-disabled)">涨跌 </span>' +
        '<span class="up" style="font-weight:600">'+(liveUp||'—')+'</span>' +
        '<span style="color:var(--text-disabled)">/</span>' +
        '<span class="down" style="font-weight:600">'+(liveDn||'—')+'</span>' +
        '<span style="font-size:10px;color:var(--info);margin-left:2px">⚡</span>' +
      '</span></span></div>';

    // === 矩阵表格 ===
    html += '<table style="width:100%;border-collapse:collapse;font-size:var(--fs-body)">';

    // 表头
    html += '<thead><tr style="border-bottom:1px solid var(--border)">' +
      '<th style="text-align:left;padding:2px var(--sp-sm);color:var(--text-disabled);font-weight:400;width:56px">指标</th>';
    NODES.forEach(function(n) {
      var isLast = n === filledNodes[filledNodes.length - 1];
      html += '<th style="text-align:center;padding:2px 4px;' +
        'color:'+(isLast?'var(--info)':'var(--text-secondary)')+';' +
        'font-weight:'+(isLast?'700':'400')+'">' + n + '</th>';
    });
    html += '</tr></thead><tbody>';

    // 数据行
    indicators.forEach(function(ind) {
      // 跳过完全没有数据的行
      var hasAny = filledNodes.some(function(n) {
        return nodes[n][ind.key] != null && !isPlaceholder(nodes[n][ind.key]);
      });
      if (!hasAny) return;

      html += '<tr style="border-bottom:1px solid var(--border-light)">' +
        '<td style="padding:3px var(--sp-sm);color:var(--text-secondary);white-space:nowrap">' + ind.label + '</td>';

      NODES.forEach(function(n) {
        var v = nodes[n] ? nodes[n][ind.key] : null;
        var filled = v != null && !isPlaceholder(v);
        var cls = filled ? cellCls(ind.key, v) : '';

        html += '<td style="text-align:center;padding:3px 4px;font-family:var(--font-mono);' +
          'color:' + (filled ? 'var(--text-primary)' : 'var(--text-disabled)') + ';' +
          'font-weight:' + (filled ? '600' : '400') + '">';
        if (filled) {
          html += '<span class="' + cls + '">' + v + '</span>';
        } else {
          html += '—';
        }
        html += '</td>';
      });

      html += '</tr>';
    });

    html += '</tbody></table>';

    // === 底部汇总（单值指标）===
    // 取各指标的最新节点
    function nodeVal(key, fallback) {
      for (var i = NODES.length-1; i >= 0; i--) {
        var v = (nodes[NODES[i]] || {})[key];
        if (v != null && !isPlaceholder(v)) return {val: v, node: NODES[i]};
      }
      return {val: fallback, node: ''};
    }
    var maxB = nodeVal('最高板', S['最高板']);
    var secB = nodeVal('次高板', S['次高板']);
    var tierV = nodeVal('梯队', S['连板梯队']);
    var profitN = nodeVal('赚钱效应', S['赚钱效应']);
    var riskN = nodeVal('连板风险值', S['连板风险值']);

    var summaryItems = [
      {t:'赚钱效应', v:profitN.val, n:profitN.node},
      {t:'连板风险', v:riskN.val, n:riskN.node},
      {t:'最高板', v:maxB.val, n:maxB.node},
      {t:'次高板', v:secB.val, n:secB.node},
      {t:'梯队', v:tierV.val, n:tierV.node},
    ];
    var hasSum = summaryItems.some(function(item) { return item.v != null && item.v !== ''; });
    if (hasSum) {
      html += '<div style="display:flex;flex-wrap:wrap;gap:4px var(--sp-md);margin-top:var(--sp-sm);padding:var(--sp-xs) var(--sp-sm);font-size:var(--fs-body)">';
      summaryItems.forEach(function(item) {
        if (item.v != null && item.v !== '') {
          html += '<span><span style="color:var(--text-disabled)">' + item.t + '</span> <strong style="color:var(--text-primary)">' + item.v + '</strong>' +
            (item.n ? '<span style="font-size:9px;color:var(--text-disabled)"> ' + item.n + '</span>' : '') +
            '</span>';
        }
      });
      html += '</div>';
    }

    body.innerHTML = html;

    // 刷新按钮
    var self = this;
    var btn = body.querySelector('#w05_refresh');
    if (btn) {
      btn.addEventListener('click', function() {
        btn.textContent = '⏳ ...';
        btn.disabled = true;
        fetch('/api/refresh', {method: 'POST'})
          .then(function(r) { return r.json(); })
          .then(function(res) { if (res.ok) DataStore.fetchAll(); })
          .catch(function() {})
          .finally(function() {
            setTimeout(function() { self._renderBody(); }, 1500);
          });
      });
    }

    this.updateTimestamp();
  }

  _renderBaseline(body, S, li) {
    var qx = S['情绪值'];
    var qxNum = parseFloat(qx) || 0;
    var zone = S['情绪区间'] || (qxNum < 20 ? '冰点' : qxNum < 40 ? '低迷' : qxNum < 60 ? '主升' : qxNum < 80 ? '强势' : '高潮');
    var liveUp = li['上涨家数'] || '—';
    var liveDn = li['下跌家数'] || '—';

    var risk = parseFloat(S['连板风险值']);
    var riskLabel = isNaN(risk) ? '' : risk < 0.4 ? '安全' : risk < 0.5 ? '关注' : '退潮';

    var html = '<div style="padding:var(--sp-sm);margin-bottom:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md);font-size:var(--fs-body);color:var(--text-secondary)">' +
      '昨日基线（5节点数据待录入） <span style="color:var(--info)">涨跌 <b>'+(liveUp||'—')+'</b>/<b>'+(liveDn||'—')+'</b> ⚡</span></div>';

    var kpis = [
      {l:'情绪值', v:(qx!=null?qx+'% '+zone:'—')},
      {l:'涨停收益', v:S['昨日涨停收益']||'—'},
      {l:'连板收益', v:S['连板收益']||'—'},
      {l:'炸板收益', v:S['昨日炸板收益']||'—'},
      {l:'风险值', v:!isNaN(risk)?risk+' '+riskLabel:'—'},
      {l:'晋级率', v:S['晋级率']||'—'},
      {l:'封板率', v:S['封板率']||'—'},
      {l:'赚钱效应', v:S['赚钱效应']||'—'},
      {l:'最高板', v:S['最高板']||'—'},
    ];

    html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(90px,1fr));gap:var(--sp-sm)">';
    kpis.forEach(function(k) {
      html += '<div class="kpi-card"><div class="kpi-label">'+k.l+'</div><div class="kpi-value" style="font-size:var(--fs-subtitle)">'+k.v+'</div></div>';
    });
    html += '</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W05', SentimentDashWidget);
