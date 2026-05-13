// widgets/llm-monitor.js — W20 AI盯盘 (15min自动触发+手动刷新)
'use strict';

class LLMMonitorWidget extends YiMuWidget {
  constructor(config) {
    super(config);
    this._lastInsight = null;
    this._loading = false;
    this._history = [];
    this._lastTriggerTime = 0;
  }

  // 覆盖：自定义定时器（30s检查一次，15min触发）
  _startTimers() {
    var self = this;
    var timer = setInterval(function() {
      self._checkAndTrigger();
    }, 30000); // 30s检查一次
    this._timers.push(timer);
  }

  _checkAndTrigger() {
    var now = new Date();
    var hour = now.getHours();
    var min = now.getMinutes();
    var mins = hour * 60 + min;

    // 盘中时间范围: 9:25-15:05
    if (mins < 565 || mins > 905) return;

    // 距上次触发 >14min 才再次触发
    if (Date.now() - this._lastTriggerTime < 840000) return;
    this._lastTriggerTime = Date.now();
    this._triggerLLM();
  }

  _triggerLLM() {
    if (this._loading) return;
    var self = this;
    this._loading = true;
    this._renderBody();

    var snapshot = this._buildSnapshot();
    var now = new Date();
    var node = now.getHours() + ':' + String(now.getMinutes()).padStart(2,'0');

    fetch('/api/llm', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({node: node, data_snapshot: snapshot})
    })
    .then(function(r) { return r.json(); })
    .then(function(res) {
      self._loading = false;
      if (res.ok && res.text) {
        self._lastInsight = res;
        // 加载历史
        self._loadHistory();
      }
      self._renderBody();
    })
    .catch(function() {
      self._loading = false;
      self._renderBody();
    });
  }

  _loadHistory() {
    var self = this;
    fetch('data/llm_insights.json?t=' + Date.now())
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) {
        if (data) {
          var today = new Date().toISOString().slice(0,10);
          var todayInsights = data[today] || {};
          self._history = Object.keys(todayInsights).map(function(k) {
            return todayInsights[k];
          }).reverse();
        }
      })
      .catch(function() {});
  }

  _buildSnapshot() {
    var d = DataStore.merged || {};
    var S = d.sentiment || {}, M = d.market || {};
    var li = d.live_index || {}, liveQ = d.live_quotes || {};
    var trPool = d.trend_pool || [], lbPool = d.lianban_pool || [];
    var sectors = d.sectors || [], nodes = d.sentiment_nodes || {};
    var positions = d.positions || [];
    var style = d.style || {};
    var risk = d.risk || {};

    // 最新节点数据
    var NODE_ORDER = ['竞价','早盘','午盘','尾盘','收盘'];
    var latestNode = null;
    for (var i = NODE_ORDER.length-1; i >= 0; i--) {
      if (Object.keys(nodes[NODE_ORDER[i]]||{}).length > 2) { latestNode = NODE_ORDER[i]; break; }
    }

    var qx = S['情绪值'] || (latestNode ? nodes[latestNode]['情绪'] : null);

    // 板块摘要
    var sectorSummary = (sectors||[]).map(function(sec) {
      return {
        name: sec['板块']||'',
        type: sec['类型']||'',
        涨停数: sec['涨停数']||'—',
        龙头: sec['龙头']||'—',
        状态: sec['状态']||''
      };
    });

    // 趋势自选（含回踩信息，供验证用）
    var trendSignals = (trPool||[]).map(function(s) {
      var q = liveQ[s['代码']] || {};
      var price = q['最新价'] || s['收盘价'] || 0;
      var ma10_60m = q['MA10_60m'];
      var volRatio = q['量比'] || 1;
      var chg = q['涨幅'] || '—';
      var dist = ma10_60m ? (((parseFloat(price)||0) - ma10_60m) / ma10_60m * 100).toFixed(1) + '%' : '—';
      return {
        name: s['标的'],
        price: price,
        dist_to_ma10_60m: dist,
        volRatio: parseFloat(volRatio).toFixed(2),
        chg: chg
      };
    });

    // 持仓
    var posSummary = (positions||[]).filter(function(p) {
      return (p['状态']||'').indexOf('清') < 0;
    }).map(function(p) {
      var q = liveQ[p['代码']] || {};
      var price = parseFloat(q['最新价']) || parseFloat(p['现价']) || 0;
      var cost = parseFloat(p['成本']) || 0;
      var pnl = cost > 0 ? ((price - cost) / cost * 100) : 0;
      return {
        name: p['标的'],
        cost: cost,
        price: price,
        pnl_pct: pnl.toFixed(1) + '%',
        qty: p['数量'] || 0
      };
    });

    return {
      time: new Date().toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit'}),
      node: latestNode || '盘前',
      情绪: qx,
      情绪区间: qx < 20 ? '冰点' : qx < 40 ? '低迷' : qx < 60 ? '主升' : qx < 80 ? '强势' : '高潮',
      上证: li['上证指数涨幅'] || S['上证涨幅'] || '—',
      涨跌家数: (li['上涨家数']||'—') + '/' + (li['下跌家数']||'—'),
      涨停收益: S['昨日涨停收益'] || '—',
      赚钱效应: S['赚钱效应'] || '—',
      风格: style['风格'] || '—',
      总分: style['总分'] || '—',
      总仓位上限: style['总仓位上限'] || '—',
      连亏天数: risk['连亏天数'] || 0,
      熔断触发: risk['熔断触发'] || false,
      sectors: sectorSummary,
      '趋势自选': trendSignals,
      持仓: posSummary
    };
  }

  render(data) {
    var body = this.getBody();
    if (!body) return;

    var html = '';

    // 顶栏
    html += '<div style="display:flex;align-items:center;gap:var(--sp-sm);margin-bottom:var(--sp-sm);padding:var(--sp-xs) var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md)">'+
      '<span style="font-weight:700;font-size:14px;color:var(--info)">🤖 AI 盯盘</span>'+
      '<span style="font-size:var(--fs-body);color:var(--text-secondary)">'+
        (this._lastInsight ? '上次: '+this._lastInsight.timestamp : '等待首次研判')+
      '</span>'+
      '<span style="margin-left:auto;display:flex;gap:var(--sp-sm)">'+
        (this._loading ? '<span style="font-size:var(--fs-body);color:var(--warn)">⏳ 分析中...</span>' : '')+
        '<button id="w20_refresh" style="font-size:var(--fs-label);padding:1px 8px;background:var(--info);color:#fff;border:none;border-radius:3px;cursor:pointer" '+
          (this._loading ? 'disabled' : '')+'>🔄 立即研判</button>'+
      '</span></div>';

    // 主研判文本
    if (this._lastInsight && this._lastInsight.text) {
      html += '<div style="padding:var(--sp-sm) var(--sp-md);margin-bottom:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md);border-left:3px solid var(--info);font-size:14px;line-height:1.7">'+
        this._lastInsight.text.replace(/\n/g, '<br>') +
        '</div>';

      // 信号验证列表
      var signals = this._lastInsight.signals || [];
      if (signals.length > 0) {
        html += '<div style="margin-bottom:var(--sp-sm);font-size:var(--fs-body)">'+
          '<span style="font-weight:600;color:var(--text-primary)">信号验证 </span>'+
          '<span style="font-size:var(--fs-label);color:var(--info)">'+this._lastInsight.verified_count+'✓</span> '+
          (this._lastInsight.warning_count > 0 ? '<span style="font-size:var(--fs-label);color:var(--warn)">'+this._lastInsight.warning_count+'⚠</span>' : '')+
          '</div>';
        signals.forEach(function(s) {
          var icon = s.status === '✅' ? '✅' : '⚠️';
          var color = s.status === '✅' ? 'var(--up)' : 'var(--warn)';
          html += '<div style="padding:2px var(--sp-sm);margin-bottom:1px;font-size:var(--fs-body)">'+
            '<span style="color:'+color+'">'+icon+'</span> '+
            '<span style="color:var(--text-primary)">'+s.signal+'</span>'+
            (s.note ? '<span style="color:var(--text-secondary);margin-left:var(--sp-sm)">— '+s.note+'</span>' : '')+
            '</div>';
        });
      }
    } else if (this._loading) {
      html += '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-secondary)">⏳ AI 正在分析全盘数据...</div>';
    } else {
      html += '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled)">等待首次研判触发<br><span style="font-size:var(--fs-label)">盘中每15分钟自动触发，或点🔄手动触发</span></div>';
    }

    // 历史折叠
    if (this._history.length > 1) {
      html += '<div style="font-size:var(--fs-label);font-weight:600;color:var(--text-primary);margin-bottom:2px;cursor:pointer" onclick="var el=document.getElementById(\'w20_hist\');el.style.display=el.style.display==\'none\'?\'block\':\'none\'">📋 历史研判 ('+this._history.length+'条) ▼</div>';
      html += '<div id="w20_hist" style="display:none">';
      this._history.slice(1).forEach(function(h) {
        html += '<div style="padding:var(--sp-xs) var(--sp-sm);margin-bottom:2px;background:var(--bg-base);border-radius:var(--radius-sm);font-size:var(--fs-body);line-height:1.5">'+
          '<span style="color:var(--text-disabled)">'+h.timestamp+'</span> '+
          (h.text||'').substring(0, 200)+'...</div>';
      });
      html += '</div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();

    // 绑定手动刷新
    var self = this;
    var btn = body.querySelector('#w20_refresh');
    if (btn) {
      btn.addEventListener('click', function() {
        self._lastTriggerTime = 0; // 重置触发计时
        self._triggerLLM();
      });
    }
  }
}

WidgetRegistry.register('W20', LLMMonitorWidget);
