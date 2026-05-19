// widgets/sentiment-dash.js — W05 情绪节点对比 v4.0
'use strict';

class SentimentDashWidget extends YiMuWidget {
  constructor(config) {
    super(config);
    this._data = null;
  }

  render(data) {
    var body = this.getBody();
    if (!body) return;

    if (!this._data) {
      this._loadData(body);
      body.innerHTML = '<div style="font-size:var(--fs-label);color:var(--text-disabled);text-align:center;padding:var(--sp-md)">加载节点数据...</div>';
      return;
    }

    this._renderTable(body);
  }

  _loadData(body) {
    var self = this;
    fetch('data/sentiment_auto.json?t=' + Date.now())
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) {
        if (data) {
          self._data = data;
          self._renderBody();
        }
      })
      .catch(function() {});
  }

  _renderTable(body) {
    var NODES = [
      {id:'auction', label:'9:25', time:'竞价'},
      {id:'morning', label:'10:00', time:'早盘'},
      {id:'midday', label:'11:30', time:'午盘'},
      {id:'afternoon', label:'14:00', time:'尾盘'},
      {id:'close', label:'15:00', time:'收盘'},
    ];

    // 找今天的快照，按节点匹配
    var today = new Date().toISOString().slice(0, 10);
    var allDay = this._data[today] || [];
    // 也找昨天的（如果今天还没有）
    var yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
    if (!allDay.length) allDay = this._data[yesterday] || [];

    // 每个节点找最接近的快照
    var nodeSnaps = {};
    NODES.forEach(function(nd) {
      var match = null;
      for (var i = allDay.length - 1; i >= 0; i--) {
        var s = allDay[i];
        var nodeName = s.node || '';
        // 匹配：竞价/早盘/午盘/尾盘/收盘
        if (nodeName.indexOf(nd.time) >= 0 || nd.time.indexOf(nodeName) >= 0) {
          match = s; break;
        }
      }
      // 模糊匹配
      if (!match) {
        var timeMap = {auction:'竞价', morning:'早盘', midday:'午盘', afternoon:'尾盘', close:'收盘'};
        var targetNode = timeMap[nd.id];
        for (var j = allDay.length - 1; j >= 0; j--) {
          if ((allDay[j].node || '').indexOf(targetNode) >= 0) {
            match = allDay[j]; break;
          }
        }
      }
      nodeSnaps[nd.id] = match || {};
    });

    function fmt(val, suffix) {
      if (val == null || val === '') return '—';
      var s = String(val);
      // 去掉已有的百分号避免重复
      if (suffix === '%' && s.indexOf('%') >= 0) return s;
      if (suffix === '亿' && s.indexOf('亿') >= 0) return s;
      return s + (suffix || '');
    }

    function cellCls(key, val) {
      var num = parseFloat(String(val).replace('%','').replace('亿',''));
      if (isNaN(num)) return '';
      if (key === '炸板收益') return num < 0 ? 'up' : num > 1 ? 'down' : '';
      if (key === '涨停收益' || key === '连板收益') return num >= 2 ? 'up' : num >= 0 ? '' : 'down';
      if (key === '情绪值') return num >= 40 && num <= 60 ? 'up' : num < 20 ? 'down' : '';
      return num >= 0 ? 'up' : 'down';
    }

    var rows = [
      {key:'上证指数', label:'上证', fmt:function(v){return v||'—';}},
      {key:'情绪值', label:'情绪值', fmt:function(v){return v!=null ? v+'%' : '—';}},
      {key:'涨跌比', label:'涨跌比', fmt:function(v,snap){var u=snap['上涨家数'],d=snap['下跌家数'];return u!=null&&d!=null ? u+'/'+d : '—';}},
      {key:'涨跌停', label:'涨跌停', fmt:function(v,snap){var z=snap['涨停家数'],d=snap['跌停家数'];return z!=null&&d!=null ? '<span class=\"up\">'+z+'</span>/<span class=\"down\">'+d+'</span>' : '—';}},
      {key:'涨停收益', label:'涨停收益', fmt:function(v){return v!=null ? (v>=0?'+':'')+v+'%' : '—';}},
      {key:'连板收益', label:'连板收益', fmt:function(v){return v!=null ? (v>=0?'+':'')+v+'%' : '—';}},
      {key:'炸板收益', label:'炸板收益', fmt:function(v){return v!=null ? (v>=0?'+':'')+v+'%' : '—';}},
    ];

    var html = '';
    html += '<table style="width:100%;border-collapse:collapse;font-size:var(--fs-body)">';

    // 表头
    html += '<thead><tr style="border-bottom:2px solid var(--border)">' +
      '<th style="text-align:left;padding:3px var(--sp-sm);color:var(--text-disabled);font-weight:400;width:60px">指标</th>';
    NODES.forEach(function(nd) {
      var hasData = Object.keys(nodeSnaps[nd.id]).length > 3;
      html += '<th style="text-align:center;padding:3px 4px;color:'+(hasData?'var(--text-primary)':'var(--text-disabled)')+';font-weight:600;font-size:var(--fs-body)">' + nd.label + '</th>';
    });
    html += '</tr></thead><tbody>';

    // 数据行
    rows.forEach(function(row) {
      html += '<tr style="border-bottom:1px solid var(--border-light)">' +
        '<td style="padding:3px var(--sp-sm);color:var(--text-secondary);white-space:nowrap;font-weight:500">' + row.label + '</td>';

      NODES.forEach(function(nd) {
        var snap = nodeSnaps[nd.id];
        // 特殊行：涨跌比用上涨/下跌家数，涨跌停用涨停/跌停家数
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

    // LLM 研判卡槽
    html += '<div style="margin-top:var(--sp-sm);padding:3px 8px;background:var(--bg-base);border-radius:var(--radius-sm);font-size:var(--fs-body);border:1px dashed var(--border-light)" id="w05-llm-text">' +
      '<span style="color:var(--text-disabled)">🤖 待研判</span></div>';

    body.innerHTML = html;
    this.updateTimestamp();

    // 异步加载 LLM
    this._loadLLM(body);
  }

  _loadLLM(body) {
    fetch('data/llm_insights.json?t=' + Date.now())
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) {
        if (!data) return;
        var today = new Date().toISOString().slice(0, 10);
        var keys = Object.keys(data).filter(function(k) { return k.indexOf(today) === 0; }).sort().reverse();
        var text = '';
        keys.forEach(function(k) {
          if (data[k] && data[k].text) text = data[k].text;
        });
        var el = body.querySelector('#w05-llm-text');
        if (el && text) {
          el.innerHTML = '<span style="color:var(--info)">🤖 ' + (text.length > 150 ? text.substring(0, 150) + '...' : text) + '</span>';
        }
      })
      .catch(function() {});
  }
}

WidgetRegistry.register('W05', SentimentDashWidget);
