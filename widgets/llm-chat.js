// widgets/llm-chat.js — 研判历史浮动框（只读）
// 继承 YiMuWidget 统一生命周期管理（_timers / _domListeners 自动清理）
'use strict';

class LlmChatWidget extends YiMuWidget {
  constructor(config) {
    // id/type/category/tier 由基类接管；聊天框不接入 GridStack 画板
    super({ id: 'LLM_CHAT', type: 'llm-chat', category: 'tool', tier: 'fast' });
    this._conversation = [];
    this._loading = false;
    this._cooldown = false;
    this._lastTriggerTime = 0;
    this._msgEl = null;
    this._inputEl = null;
    this._sendBtn = null;
    this._panelOverlay = null;
    this._domReady = false;   // P2-6: 防止 _initDOM / _loadHistory 重复插入引导
  }

  // === 生命周期 ===

  mount(container) {
    // 不调 super.mount() —— 聊天框不是 GridStack widget，跳过外壳渲染/数据订阅
    this._container = container;
    this._initDOM();
    this._bindEvents();
    this._loadHistory();
  }

  unmount() {
    // 基类 super.unmount() 会清理 _timers 和 _domListeners
    this._timers.forEach(function(t) { clearInterval(t); clearTimeout(t); });
    this._timers = [];
    this._domListeners.forEach(function(d) {
      if (d.el && d.event && d.fn) d.el.removeEventListener(d.event, d.fn);
    });
    this._domListeners = [];
    this._container = null;
    this._domReady = false;
  }

  // === DOM ===

  _initDOM() {
    var el = this._container;
    el.innerHTML =
      '<div class="chat-overlay" id="chatOverlay">' +
        '<div class="chat-panel" id="chatPanel">' +
          '<div class="chat-header" id="chatHeader">' +
            '<span style="font-size:var(--fs-subtitle);font-weight:600">研判历史</span>' +
            '<div style="display:flex;gap:var(--sp-sm);align-items:center">' +
              '<button id="chatRefresh" style="background:var(--bg-base);color:var(--text-secondary);border:1px solid var(--border);padding:2px 12px;border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body)">刷新历史</button>' +
              '<button id="chatClose" style="background:none;border:none;font-size:18px;cursor:pointer;color:var(--text-secondary);padding:0 4px">×</button>' +
            '</div>' +
          '</div>' +
          '<div class="chat-messages" id="chatMessages" tabindex="0"></div>' +
          '<div class="chat-typing" id="chatTyping" style="display:none">加载中...</div>' +
          '<div class="chat-input-row">' +
            '<input id="chatInput" type="text" placeholder="仪表盘仅保留研判历史" autocomplete="off" disabled />' +
            '<button id="chatSend" disabled>发送</button>' +
          '</div>' +
        '</div>' +
      '</div>';

    this._panelOverlay = document.getElementById('chatOverlay');
    this._msgEl = document.getElementById('chatMessages');
    this._inputEl = document.getElementById('chatInput');
    this._sendBtn = document.getElementById('chatSend');
  }

  _on(el, event, fn) {
    if (!el) return;
    el.addEventListener(event, fn);
    this._domListeners.push({ el: el, event: event, fn: fn });
  }

  _bindEvents() {
    var self = this;

    this._on(document.getElementById('chatClose'), 'click', function() {
      self.hide();
    });
    this._on(this._panelOverlay, 'click', function(e) {
      if (e.target === self._panelOverlay) self.hide();
    });
    this._on(document.getElementById('chatSend'), 'click', function() {
      self._sendManual();
    });
    this._on(this._inputEl, 'keydown', function(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        self._sendManual();
      }
    });
    // 仪表盘只读：刷新历史，不触发研判。
    this._on(document.getElementById('chatRefresh'), 'click', function() {
      self._loadHistory();
    });
  }

  // === 历史加载 ===

  _loadHistory() {
    var self = this;
    fetch('/api/llm/history')
      .then(function(r) { return r.ok ? r.json() : null; })
      .catch(function() { return null; })
      .then(function(data) {
        if (!data) {
          self._insertIntro();
          return;
        }
        var conv = data.conversation || [];
        var hasSystem = conv.some(function(c) { return c.role === 'system'; });
        if (hasSystem) {
          self._conversation = conv;
        } else {
          self._conversation = [{
            role: 'system',
            ts: self._now(),
            text: 'AI研判历史',
            auto: false,
          }].concat(conv);
        }
        self._domReady = true;   // _insertIntro 只在真的空时调用
        self._renderMessages();
      });
  }

  /** 只在真正空状态时插入一次引导文案（P2-6）*/
  _insertIntro() {
    if (this._domReady) return;
    this._domReady = true;
    this._conversation.push({
      role: 'system',
      ts: this._now(),
      text: 'AI研判历史',
      auto: false,
    });
    this._renderMessages();
  }

  // === 定时器 ===

  _startTimers() {
    this._loadHistory();
  }

  _shouldTrigger() {
    var now = new Date();
    var mins = now.getHours() * 60 + now.getMinutes();
    if (mins < 565 || mins > 905) return false;
    if (Date.now() - this._lastTriggerTime < 840000) return false;
    return true;
  }

  _triggerAuto() {
    this._loadHistory();
  }

  _triggerManual() {
    this._loadHistory();
  }

  _sendManual() {
    this._send();
  }

  _send() {
    this._conversation.push({
      role: 'system',
      ts: this._now(),
      text: '仪表盘仅保留研判历史',
      auto: false,
    });
    this._loading = false;
    this._showTyping(false);
    this._renderMessages();
  }

  // === UI ===

  _showTyping(show) {
    var el = document.getElementById('chatTyping');
    if (el) el.style.display = show ? '' : 'none';
  }

  _renderMessages() {
    var el = this._msgEl;
    if (!el) return;
    var html = '';
    var self = this;
    this._conversation.forEach(function(c) {
      html += self._bubbleHTML(c);
    });
    el.innerHTML = html;
    el.scrollTop = el.scrollHeight;
  }

  _esc(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  _bubbleHTML(c) {
    var role = c.role;
    var ts = c.ts || '';
    // 统一文本转义（覆盖 system/user/assistant 全部文本）
    var text = this._esc(c.text || '').replace(/\n/g, '<br>');

    var sigHtml = '';
    if (role === 'assistant' && c.signals && c.signals.length > 0) {
      var tags = [];
      var self = this;
      c.signals.forEach(function(s) {
        // P2-5: 信号 type/target/direction 全部转义后拼入 HTML
        var color = s.type === 'BUY' ? '#059669' : s.type === 'RISK' ? '#DC2626' : '#6B7280';
        var bg = s.status === '✅' ? '#D1FAE5' : '#FEF3C7';
        tags.push(
          '<span style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;' +
          'background:' + bg + ';color:' + color + ';margin:1px 2px">' +
          self._esc(s.type || '') + ' ' + self._esc(s.target || '') + ' ' + self._esc(s.direction || '') +
          ' <span style="opacity:0.7">' + self._esc(s.status || '') + '</span>' +
          '</span>'
        );
      });
      sigHtml = '<div class="chat-signals">' + tags.join('') + '</div>';
    }

    if (role === 'system') {
      return '<div class="chat-bubble chat-bubble--intro">' + text + '</div>';
    }
    if (role === 'user') {
      return '<div class="chat-bubble chat-bubble--user"><div>' + text + '</div>' +
             '<div style="font-size:10px;opacity:0.6;margin-top:2px;text-align:right">' + this._esc(ts) + '</div></div>';
    }
    return '<div class="chat-bubble chat-bubble--assistant"><div>' + text + '</div>' + sigHtml +
           '<div style="font-size:10px;opacity:0.5;margin-top:4px">' + this._esc(ts) +
           (c.auto ? ' · 自动' : ' · 手动') + '</div></div>';
  }

  show() {
    if (this._panelOverlay) this._panelOverlay.classList.add('show');
    if (this._msgEl) {
      this._msgEl.focus();
      requestAnimationFrame(function() { this._msgEl.scrollTop = this._msgEl.scrollHeight; }.bind(this));
    }
  }

  hide() {
    if (this._panelOverlay) this._panelOverlay.classList.remove('show');
  }

  _now() {
    var d = new Date();
    return String(d.getHours()).padStart(2, '0') + ':' +
           String(d.getMinutes()).padStart(2, '0') + ':' +
           String(d.getSeconds()).padStart(2, '0');
  }
}

window.LlmChatWidget = LlmChatWidget;
