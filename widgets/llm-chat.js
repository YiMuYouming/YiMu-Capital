// widgets/llm-chat.js — AI盯盘浮动聊天框
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
    this._startTimers();
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
    this._on(this._msgEl, 'focus', function() {
      window._llmBadgeCount = 0;
      if (typeof window._updateLlmBadge === 'function') window._updateLlmBadge();
    });
    // 立即研判（P1-4 修正: 用 'auto' 模式，因为没有用户问题）
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
            text: 'AI盯盘已启动，每15分钟自动研判。\n可问：大盘走向 · 持仓分析 · 板块机会 · 个股研判',
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
      text: 'AI盯盘已启动，每15分钟自动研判。\n可问：大盘走向 · 持仓分析 · 板块机会 · 个股研判',
      auto: false,
    });
    this._renderMessages();
  }

  // === 定时器 ===

  _startTimers() {
    var self = this;
    var timer = setInterval(function() {
      if (self._shouldTrigger()) self._triggerAuto();
    }, 30000);
    this._timers.push(timer);
  }

  _shouldTrigger() {
    var now = new Date();
    var mins = now.getHours() * 60 + now.getMinutes();
    if (mins < 565 || mins > 905) return false;
    if (Date.now() - this._lastTriggerTime < 840000) return false;
    return true;
  }

  _triggerAuto() {
    if (this._loading) return;
    this._lastTriggerTime = Date.now();
    this._send('', 'auto');
  }

  // P1-4: 立即研判走 'auto' 模式（无用户提问）
  _triggerManual() {
    if (this._loading) return;
    this._lastTriggerTime = Date.now();
    this._send('', 'auto');
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

    var userMsg = {
      role: 'user',
      ts: this._now(),
      text: q,
      auto: false,
    };
    this._conversation.push(userMsg);
    this._inputEl.value = '';
    this._renderMessages();
    this._send(q, 'manual', userMsg);
  }

  /**
   * P1-3: userMsg 传给后端，由后端写入 llm_insights.json conversation
   * P1-4: mode='auto' 时 question 为空字符串，调用 auto 模式 prompt
   */
  _send(question, mode, userMsg) {
    var self = this;
    this._loading = true;
    this._showTyping(true);

    // P1-3: 附上用户消息供后端持久化
    fetch('/api/llm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode: mode,
        question: question || '',
        userMsg: userMsg || null,
      }),
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
    window._llmBadgeCount = 0;
    if (typeof window._updateLlmBadge === 'function') window._updateLlmBadge();
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
