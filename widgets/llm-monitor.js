// widgets/llm-monitor.js — W20 外部研判摘要（只读展示）
'use strict';

function _w20Esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

class LLMMonitorWidget extends YiMuWidget {
  constructor(config) {
    super(config);
    this._lastInsight = null;
    this._loading = false;
  }

  // 60s 轮询最新研判，只读展示，不触发 LLM。
  _startTimers() {
    var self = this;
    var timer = setInterval(function() {
      self._loadLatest();
    }, 60000);
    this._timers.push(timer);
    // 初始加载
    this._loadLatest();
  }

  _loadLatest() {
    var self = this;
    if (this._loading) return;
    this._loading = true;

    fetch('/api/llm/history')
      .then(function(r) { return r.ok ? r.json() : null; })
      .catch(function() { return null; })
      .then(function(data) {
        self._loading = false;
        if (data && data.conversation && data.conversation.length > 0) {
          var conv = data.conversation;
          // 取最后一条 assistant 消息
          for (var i = conv.length - 1; i >= 0; i--) {
            if (conv[i].role === 'assistant') {
              self._lastInsight = conv[i];
              break;
            }
          }
        }
        self._renderBody();
      });
  }

  render(data) {
    var body = this.getBody();
    if (!body) return;

    var insight = this._lastInsight;
    var verified = insight ? (insight.signals || []).filter(function(s) { return s.status === '✅'; }).length : 0;
    var warnings = insight ? (insight.signals || []).filter(function(s) { return s.status === '⚠️'; }).length : 0;
    var signalCount = insight ? (insight.signals || []).length : 0;

    var html = '';

    html += '<div class="w20-head">' +
      '<span>外部研判摘要</span>' +
      '<em>' + (insight ? '上次 ' + _w20Esc(insight.ts) : '等待写入') + '</em>' +
      '</div>';

    // 研判摘要（限200字）
    if (insight && insight.text) {
      var text = insight.text;
      var truncated = text.length > 200 ? text.substring(0, 200) + '...' : text;
      html += '<div style="padding:var(--sp-sm) var(--sp-md);margin-bottom:var(--sp-sm);' +
        'background:var(--bg-base);border-radius:var(--radius-md);' +
        'border-left:3px solid var(--info);font-size:14px;line-height:1.7">' +
        _w20Esc(truncated).replace(/\n/g, '<br>') +
        '</div>';

      // 信号统计
      if (signalCount > 0) {
        var buySig = (insight.signals || []).filter(function(s) { return s.type === 'BUY'; }).length;
        var watchSig = (insight.signals || []).filter(function(s) { return s.type === 'WATCH'; }).length;
        var riskSig = (insight.signals || []).filter(function(s) { return s.type === 'RISK'; }).length;
        var statParts = [];
        if (buySig > 0) statParts.push('<span style="color:var(--up)">买入 ×' + buySig + '</span>');
        if (watchSig > 0) statParts.push('<span style="color:var(--info)">观察 ×' + watchSig + '</span>');
        if (riskSig > 0) statParts.push('<span style="color:var(--danger)">风险 ×' + riskSig + '</span>');
        statParts.push('<span style="color:var(--text-secondary)">已核 ' + verified + '</span>');
        if (warnings > 0) statParts.push('<span style="color:var(--warn)">待核 ' + warnings + '</span>');

        html += '<div style="font-size:var(--fs-body);margin-bottom:var(--sp-sm);display:flex;gap:var(--sp-sm);flex-wrap:wrap">' +
          statParts.join(' ') + '</div>';
      }
    } else if (this._loading) {
      html += '<div class="ui-empty"><div class="ui-empty-title">加载研判数据</div><div class="ui-empty-detail">读取外部 Agent 已写入的只读记录</div></div>';
    } else {
      html += '<div class="ui-empty"><div class="ui-empty-title">等待研判记录</div><div class="ui-empty-detail">仪表盘只展示结果，不在这里触发对话</div></div>';
    }

    html += '<div class="w20-foot">' +
      '<span>只读展示，不在仪表盘触发研判</span>' +
      (typeof window !== 'undefined' && typeof window._showLLMPanel === 'function' ? '<button id="w20_openHistory">查看历史</button>' : '') +
      '</div>';

    body.innerHTML = html;
    this.updateTimestamp();

    var btn = body.querySelector('#w20_openHistory');
    if (btn) {
      btn.addEventListener('click', function() {
        if (typeof window._showLLMPanel === 'function') window._showLLMPanel();
      });
    }
  }
}

WidgetRegistry.register('W20', LLMMonitorWidget);
