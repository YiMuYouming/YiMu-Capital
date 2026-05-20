// widgets/llm-chat.js — AI盯盘浮动聊天框
// 继承 YiMuWidget 的 _timers 自动清理机制
'use strict';

class LlmChatWidget {
  constructor(config) {
    this.id = config.id || 'LLM_CHAT';
    this._timers = [];          // 基类约定，供 unmount 清理
    this._domListeners = [];
    this._conversation = [];
    this._loading = false;
    this._cooldown = false;
    this._lastTriggerTime = 0;
    this._msgEl = null;
    this._inputEl = null;
    this._sendBtn = null;
    this._panelOverlay = null;
  }

  // === 生命周期 ===

  mount(container) {
    this._container = container;
    this._initDOM();
    this._bindEvents();
    this._loadHistory();
    this._startTimers();
  }

  unmount() {
    this._timers.forEach(function(t) { clearInterval(t); clearTimeout(t); });
    this._timers = [];
    this._domListeners.forEach(function(d) {
      if (d.el && d.event && d.fn) d.el.removeEventListener(d.event, d.fn);
    });
    this._domListeners = [];
    this._container = null;
  }

  // === DOM ===

  _initDOM() {
    var el = this._container;
    el.innerHTML =
      '<div class="chat-overlay" id="chatOverlay">' +
        '<div class="chat-panel" id="chatPanel">' +
          '<div class="chat-header" id="chatHeader">' +
            '<span style="font-size:var(--fs-subtitle);font-weight:600">🤖 AI盯盘</span>' +
            '<div style="display:flex;gap:var(--sp-sm);align-items:center">' +
              '<button id="chatRefresh" style="background:var(--info);color:#fff;border:none;padding:2px 12px;border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body)">🔄 立即研判</button>' +
              '<button id="chatClose" style="background:none;border:none;font-size:18px;cursor:pointer;color:var(--text-secondary);padding:0 4px">×</button>' +
            '</div>' +
          '</div>' +
          '<div class="chat-messages" id="chatMessages" tabindex="0"></div>' +
          '<div class="chat-typing" id="chatTyping" style="display:none">🤖 AI分析中...</div>' +
          '<div class="chat-input-row">' +
            '<input id="chatInput" type="text" placeholder="问AI一个问题..." autocomplete="off" />' +
            '<button id="chatSend">发送</button>' +
          '</div>' +
        '</div>' +
      '</div>';

    this._panelOverlay = document.getElementById('chatOverlay');
    this._msgEl = document.getElementById('chatMessages');
    this._inputEl = document.getElementById('chatInput');
    this._sendBtn = document.getElementById('chatSend');

    // 引导文案（首次空状态）
    if (this._conversation.length === 0) {
      this._conversation.push({
        role: 'system',
        ts: this._now(),
        text: 'AI盯盘已启动，每15分钟自动研判。\n可问：大盘走向 · 持仓分析 · 板块机会 · 个股研判',
        auto: false,
      });
      this._renderMessages();
    }
  }

  _on(el, event, fn) {
    if (!el) return;
    el.addEventListener(event, fn);
    this._domListeners.push({ el: el, event: event, fn: fn });
  }

  _bindEvents() {
    var self = this;

    // 关闭
    this._on(document.getElementById('chatClose'), 'click', function() {
      self.hide();
    });
    // 点击遮罩关闭
    this._on(this._panelOverlay, 'click', function(e) {
      if (e.target === self._panelOverlay) self.hide();
    });

    // 发送
    this._on(document.getElementById('chatSend'), 'click', function() {
      self._sendManual();
    });
    this._on(this._inputEl, 'keydown', function(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        self._sendManual();
      }
    });

    // 聚焦/失焦清红点
    this._on(this._msgEl, 'focus', function() {
      window._llmBadgeCount = 0;
      if (typeof window._updateLlmBadge === 'function') window._updateLlmBadge();
    });

    // 立即研判
    this._on(document.getElementById('chatRefresh'), 'click', function() {
      self._triggerManual();
    });
  }

  // === 历史加载 ===

  _loadHistory() {
    var self = this;
    fetch('/api/llm/history')
      .then(function(r) { return r.ok ? r.json() : null; })
      .catch(function() { return null; })
      .then(function(data) {
        if (!data) return;
        var conv = data.conversation || [];
        // 已有引导文案则跳过 system
        var hasSystem = conv.some(function(c) { return c.role === 'system'; });
        if (hasSystem) {
          self._conversation = conv;
        } else {
          // 插入引导
          self._conversation = [{
            role: 'system',
            ts: self._now(),
            text: 'AI盯盘已启动，每15分钟自动研判。\n可问：大盘走向 · 持仓分析 · 板块机会 · 个股研判',
            auto: false,
          }].concat(conv);
        }
        self._renderMessages();
        // 未读计数
        var latest = conv[conv.length - 1];
        if (latest && latest.auto && typeof window._notifyLLMAuto === 'function') {
          // 静默加载历史，不弹 Toast
        }
      });
  }

  // === 定时器（push 进 _timers）===

  _startTimers() {
    var self = this;
    // 30s 检查一次是否该触发（实际由 _shouldTrigger 控制间隔）
    var timer = setInterval(function() {
      if (self._shouldTrigger()) self._triggerAuto();
    }, 30000);
    this._timers.push(timer);
  }

  _shouldTrigger() {
    var now = new Date();
    var mins = now.getHours() * 60 + now.getMinutes();
    if (mins < 565 || mins > 905) return false;  // 非盘中 (9:25-15:05)
    if (Date.now() - this._lastTriggerTime < 840000) return false;  // 14min 冷却
    return true;
  }

  _triggerAuto() {
    if (this._loading) return;
    this._lastTriggerTime = Date.now();
    this._send('', 'auto');
  }

  _triggerManual() {
    if (this._loading) return;
    this._lastTriggerTime = Date.now();
    this._send('', 'manual');
  }

  _sendManual() {
    var q = (this._inputEl.value || '').trim();
    if (!q) return;
    if (this._cooldown) {
      if (typeof window.showToast === 'function') window.showToast('请求太频繁，请30秒后再试');
      return;
    }
    this._cooldown = true;
    var self = this;
    setTimeout(function() { self._cooldown = false; }, 30000);

    // 追加 user 气泡
    this._conversation.push({
      role: 'user',
      ts: this._now(),
      text: q,
      auto: false,
    });
    this._inputEl.value = '';
    this._renderMessages();
    this._send(q, 'manual');
  }

  _send(question, mode) {
    var self = this;
    this._loading = true;
    this._showTyping(true);

    fetch('/api/llm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: mode, question: question || '' }),
    })
    .then(function(r) { return r.json(); })
    .then(function(res) {
      self._loading = false;
      self._showTyping(false);
      if (res.ok) {
        self._conversation.push({
          role: 'assistant',
          ts: res.timestamp,
          text: res.text || '(无内容)',
          signals: res.signals || [],
          auto: mode === 'auto',
        });
        self._renderMessages();
        if (mode === 'auto' && typeof window._notifyLLMAuto === 'function') {
          window._notifyLLMAuto(res.text);
        }
        if (mode === 'manual') {
          if (typeof window.showToast === 'function') window.showToast('研判已完成');
        }
      } else {
        self._conversation.push({
          role: 'system',
          ts: self._now(),
          text: '研判失败: ' + (res.error || '未知错误'),
          auto: false,
        });
        self._renderMessages();
        if (typeof window.showToast === 'function') {
          window.showToast('研判失败: ' + (res.error || '未知错误'));
        }
      }
    })
    .catch(function() {
      self._loading = false;
      self._showTyping(false);
      self._conversation.push({
        role: 'system',
        ts: self._now(),
        text: '网络错误，请重试',
        auto: false,
      });
      self._renderMessages();
    });
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

  _bubbleHTML(c) {
    var role = c.role;
    var ts = c.ts || '';
    var text = (c.text || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');

    var sigHtml = '';
    if (role === 'assistant' && c.signals && c.signals.length > 0) {
      var tags = [];
      c.signals.forEach(function(s) {
        var color = s.type === 'BUY' ? '#059669' : s.type === 'RISK' ? '#DC2626' : '#6B7280';
        var bg = s.status === '✅' ? '#D1FAE5' : '#FEF3C7';
        tags.push(
          '<span style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;' +
          'background:' + bg + ';color:' + color + ';margin:1px 2px">' +
          (s.type || '') + ' ' + (s.target || '') + ' ' + (s.direction || '') +
          ' <span style="opacity:0.7">' + (s.status || '') + '</span>' +
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
             '<div style="font-size:10px;opacity:0.6;margin-top:2px;text-align:right">' + ts + '</div></div>';
    }
    // assistant
    return '<div class="chat-bubble chat-bubble--assistant"><div>' + text + '</div>' + sigHtml +
           '<div style="font-size:10px;opacity:0.5;margin-top:4px">' + ts +
           (c.auto ? ' · 自动' : ' · 手动') + '</div></div>';
  }

  show() {
    if (this._panelOverlay) this._panelOverlay.classList.add('show');
    // 清红点
    window._llmBadgeCount = 0;
    if (typeof window._updateLlmBadge === 'function') window._updateLlmBadge();
    this._msgEl && this._msgEl.focus();
  }

  hide() {
    if (this._panelOverlay) this._panelOverlay.classList.remove('show');
  }

  // === 辅助 ===

  _now() {
    var d = new Date();
    return String(d.getHours()).padStart(2, '0') + ':' +
           String(d.getMinutes()).padStart(2, '0') + ':' +
           String(d.getSeconds()).padStart(2, '0');
  }
}

// 注册（全局暴露供 index.html 调用）
window.LlmChatWidget = LlmChatWidget;
