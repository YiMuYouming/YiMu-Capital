// widgets/llm-monitor.js — W20 AI盯盘（精简：摘要视图，聊天交给 llm-chat.js）
'use strict';

class LLMMonitorWidget extends YiMuWidget {
  constructor(config) {
    super(config);
    this._lastInsight = null;
    this._loading = false;
  }

  // 重写：60s 轮询最新研判，不再自己触发 LLM
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

    // 顶栏
    html += '<div style="display:flex;align-items:center;gap:var(--sp-sm);margin-bottom:var(--sp-sm)">' +
      '<span style="font-weight:700;font-size:14px;color:var(--info)">🤖 AI 盯盘</span>' +
      '<span style="font-size:var(--fs-body);color:var(--text-secondary)">' +
        (insight ? '上次: ' + insight.ts : '等待首次研判') +
      '</span>' +
      '</div>';

    // 研判摘要（限200字）
    if (insight && insight.text) {
      var text = insight.text;
      var truncated = text.length > 200 ? text.substring(0, 200) + '...' : text;
      html += '<div style="padding:var(--sp-sm) var(--sp-md);margin-bottom:var(--sp-sm);' +
        'background:var(--bg-base);border-radius:var(--radius-md);' +
        'border-left:3px solid var(--info);font-size:14px;line-height:1.7">' +
        truncated.replace(/\n/g, '<br>') +
        '</div>';

      // 信号统计
      if (signalCount > 0) {
        var buySig = (insight.signals || []).filter(function(s) { return s.type === 'BUY'; }).length;
        var watchSig = (insight.signals || []).filter(function(s) { return s.type === 'WATCH'; }).length;
        var riskSig = (insight.signals || []).filter(function(s) { return s.type === 'RISK'; }).length;
        var statParts = [];
        if (buySig > 0) statParts.push('<span style="color:var(--up)">BUY ×' + buySig + '</span>');
        if (watchSig > 0) statParts.push('<span style="color:var(--info)">WATCH ×' + watchSig + '</span>');
        if (riskSig > 0) statParts.push('<span style="color:var(--danger)">RISK ×' + riskSig + '</span>');
        statParts.push('<span style="color:var(--up)">✅' + verified + '</span>');
        if (warnings > 0) statParts.push('<span style="color:var(--warn)">⚠️' + warnings + '</span>');

        html += '<div style="font-size:var(--fs-body);margin-bottom:var(--sp-sm);display:flex;gap:var(--sp-sm);flex-wrap:wrap">' +
          statParts.join(' ') + '</div>';
      }
    } else if (this._loading) {
      html += '<div style="padding:var(--sp-md);text-align:center;color:var(--text-secondary)">⏳ 加载研判数据...</div>';
    } else {
      html += '<div style="padding:var(--sp-md);text-align:center;color:var(--text-disabled)">等待首次研判</div>';
    }

    // 打开对话按钮
    html += '<div style="text-align:center;margin-top:var(--sp-sm)">' +
      '<button id="w20_openChat" style="' +
        'background:var(--info);color:#fff;border:none;' +
        'padding:5px 18px;border-radius:20px;cursor:pointer;' +
        'font-size:var(--fs-body);font-weight:600">' +
        '💬 打开对话' +
      '</button>' +
      '</div>';

    body.innerHTML = html;
    this.updateTimestamp();

    // 绑定按钮
    var self = this;
    var btn = body.querySelector('#w20_openChat');
    if (btn) {
      btn.addEventListener('click', function() {
        if (window._llmChat) window._llmChat.show();
      });
    }
  }
}

WidgetRegistry.register('W20', LLMMonitorWidget);
