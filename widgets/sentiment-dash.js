// widgets/sentiment-dash.js — W05 情绪节点对比 v5.0 (DataStore subscription, no direct fetch)
'use strict';

class SentimentDashWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;

    var nodes = (data && data.sentiment_nodes) || {};

    if (!nodes._available) {
      body.innerHTML = '<div class="ui-empty ui-empty-inline"><div class="ui-empty-title">情绪节点数据不可用</div></div>';
      this.updateTimestamp();
      return;
    }

    this._renderTable(body, nodes, nodes._stale);
  }

  _renderTable(body, nodes, isStale) {
    var NODES = [
      {id:'auction',    label:'9:25',  target:'竞价'},
      {id:'morning',    label:'10:00', target:'早盘'},
      {id:'morning2',   label:'10:30', target:'早盘2'},
      {id:'midday',     label:'11:30', target:'午盘'},
      {id:'afternoon1', label:'13:30', target:'尾盘1'},
      {id:'afternoon',  label:'14:00', target:'尾盘'},
      {id:'afternoon2', label:'14:30', target:'尾盘2'},
      {id:'close',      label:'15:00', target:'收盘'},
    ];

    // 取最新日期 key（与 DataStore 北京交易日统一，不依赖 UTC toISOString）
    var nodeKeys = Object.keys(nodes).filter(function(k) {
      return /^\d{4}-\d{2}-\d{2}$/.test(k);
    }).sort().reverse();
    var allDay = [];
    for (var i = 0; i < nodeKeys.length; i++) {
      allDay = nodes[nodeKeys[i]] || [];
      if (allDay.length) break;
    }

    var nodeSnaps = {};
    NODES.forEach(function(nd) {
      var match = null;
      for (var i = allDay.length - 1; i >= 0; i--) {
        if (allDay[i].node === nd.target) { match = allDay[i]; break; }
      }
      nodeSnaps[nd.id] = match || {};
    });

    function fmt(val, suffix) {
      if (val == null || val === '') return '—';
      var s = String(val);
      if (suffix === '%' && s.indexOf('%') >= 0) return s;
      if (suffix === '亿' && s.indexOf('亿') >= 0) return s;
      return s + (suffix || '');
    }

    function cellCls(key, val) {
      var num = parseFloat(String(val).replace('%','').replace('亿',''));
      if (isNaN(num)) return '';
      return num > 0 ? 'up' : num < 0 ? 'down' : '';
    }

    var rows = [
      {key:'上证指数', label:'上证', fmt:function(v){return v||'—';}},
      {key:'情绪值', label:'情绪值', fmt:function(v){return v!=null ? v+'%' : '—';}},
      {key:'涨跌比', label:'涨跌比', fmt:function(v,snap){var u=snap['上涨家数'],d=snap['下跌家数'];if(u==null&&d==null)return'—';return (u!=null?'<span class=\"up\">'+u+'</span>':'—')+'/'+(d!=null?'<span class=\"down\">'+d+'</span>':'—');}},
      {key:'涨跌停', label:'涨跌停', fmt:function(v,snap){var z=snap['涨停家数'],d=snap['跌停家数'];if(z==null&&d==null)return'—';return (z!=null?'<span class=\"up\">'+z+'</span>':'—')+'/'+(d!=null?'<span class=\"down\">'+d+'</span>':'—');}},
      {key:'涨停收益', label:'涨停收益', fmt:function(v){return v!=null ? (v>=0?'+':'')+v+'%' : '—';}},
      {key:'连板收益', label:'连板收益', fmt:function(v){return v!=null ? (v>=0?'+':'')+v+'%' : '—';}},
      {key:'炸板收益', label:'炸板收益', fmt:function(v){return v!=null ? (v>=0?'+':'')+v+'%' : '—';}},
    ];

    var html = '';
    if (isStale) {
      html += '<div class="w05-stale" style="text-align:center;padding:2px 8px;margin-bottom:var(--sp-xs);background:var(--warn);color:#fff;font-size:var(--fs-label);border-radius:var(--radius-sm)">数据过期 — 最后更新超过30分钟</div>';
    }

    html += '<table style="width:100%;border-collapse:collapse;font-size:var(--fs-body)">';

    html += '<thead><tr style="border-bottom:2px solid var(--border)">' +
      '<th style="text-align:left;padding:3px var(--sp-sm);color:var(--text-disabled);font-weight:400;width:60px">指标</th>';
    NODES.forEach(function(nd) {
      var hasData = Object.keys(nodeSnaps[nd.id]).length > 3;
      html += '<th style="text-align:center;padding:3px 4px;color:'+(hasData?'var(--text-primary)':'var(--text-disabled)')+';font-weight:600;font-size:var(--fs-body)">' + nd.label + '</th>';
    });
    html += '</tr></thead><tbody>';

    rows.forEach(function(row) {
      html += '<tr style="border-bottom:1px solid var(--border-light)">' +
        '<td style="padding:3px var(--sp-sm);color:var(--text-secondary);white-space:nowrap;font-weight:500">' + row.label + '</td>';

      NODES.forEach(function(nd) {
        var snap = nodeSnaps[nd.id];
        var display, cls = '';
        if (row.key === '涨跌比') {
          display = row.fmt(null, snap);
        } else if (row.key === '涨跌停') {
          display = row.fmt(null, snap);
        } else {
          var val = snap[row.key];
          display = row.fmt(val);
          if (val != null && val !== '') cls = cellCls(row.key, val);
        }

        html += '<td style="text-align:center;padding:3px 4px;font-family:var(--font-mono);font-size:var(--fs-body);' +
          'color:'+(display==='—'?'var(--text-disabled)':'var(--text-primary)')+';' +
          'font-weight:'+(display==='—'?'400':'600')+'">';
        if (cls) {
          html += '<span class="' + cls + '">' + display + '</span>';
        } else {
          html += display;
        }
        html += '</td>';
      });

      html += '</tr>';
    });

    html += '</tbody></table>';

    html += '<div class="ui-note ui-note-muted" id="w05-llm-text">等待外部研判记录</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W05', SentimentDashWidget);
