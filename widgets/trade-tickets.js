// widgets/trade-tickets.js — W24 交易票据看板
'use strict';

function _ttEsc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function _ttList(values) {
  if (!Array.isArray(values)) return [];
  return values.filter(function(v){ return v !== null && v !== undefined && v !== ''; });
}

function _ttActionLabel(action) {
  var map = {
    buy: '买入',
    sell: '卖出',
    add: '加仓',
    reduce: '减仓',
    clear: '清仓',
    t: '做T',
    do_t: '做T',
    observe: '观察'
  };
  return map[String(action || '').toLowerCase()] || (action || '未定');
}

function _ttStatusLabel(status) {
  var map = {
    draft: '待确认',
    confirmed: '待确认',
    executable: '可执行',
    blocked: '已阻断',
    audit_degraded: '审计降级',
    filled: '已成交',
    partially_filled: '部分成交',
    closed: '已关闭',
    closed_with_conflict: '冲突关闭',
    cancelled: '已取消'
  };
  return map[String(status || '').toLowerCase()] || (status || '未知状态');
}

function _ttIsExitAction(action) {
  return ['sell', 'reduce', 'clear'].indexOf(String(action || '').toLowerCase()) >= 0;
}

function _ttEffectiveStatus(t) {
  t = t || {};
  var status = String(t.status || '').toLowerCase();
  var blocks = _ttList(t.blocking_rule_ids || []);
  var missing = _ttList(t.missing_required_data || t.missing_data || []);
  var qty = t.max_qty != null ? Number(t.max_qty) : Number(t.qty);
  var sellable = t.sellable_quantity != null ? Number(t.sellable_quantity) : NaN;
  var contextOnly = blocks.length === 1 && blocks[0] === 'context_status';
  var sellableOk = !Number.isFinite(qty) || (Number.isFinite(sellable) && qty <= sellable);
  if (status === 'blocked' && _ttIsExitAction(t.action_type) && contextOnly && !missing.length && sellableOk) {
    return 'audit_degraded';
  }
  return status;
}

function _ttCreatedAt(t) {
  var raw = (t || {}).created_at || (t || {}).updated_at || '';
  var ts = Date.parse(String(raw).replace(' ', 'T'));
  return Number.isFinite(ts) ? ts : 0;
}

function _ttIsSupersededAuditTicket(t, tickets) {
  if (_ttEffectiveStatus(t) !== 'audit_degraded' || !_ttIsExitAction((t || {}).action_type)) return false;
  var blocks = _ttList((t || {}).blocking_rule_ids || []);
  if (!(blocks.length === 1 && blocks[0] === 'context_status')) return false;
  var code = String((t || {}).code || '');
  if (!code) return false;
  var created = _ttCreatedAt(t);
  return (tickets || []).some(function(other) {
    if (!other || other === t) return false;
    if (String(other.code || '') !== code) return false;
    if (!_ttIsExitAction(other.action_type)) return false;
    if (['filled', 'partially_filled', 'closed', 'closed_with_conflict'].indexOf(String(other.status || '').toLowerCase()) < 0) return false;
    return _ttCreatedAt(other) >= created;
  });
}

function _ttFriendlyError(message) {
  var text = String(message || '');
  if (/ticket not found/i.test(text)) return '请先选择一张票据，或先出票据再预览成交。';
  if (/preview|confirmation/i.test(text)) return '还没有可确认的成交预览，请先点“预览成交”。';
  return text || '操作失败，请稍后重试。';
}

function _ttWriteGate(action) {
  var w = (typeof window !== 'undefined') ? window : null;
  var loc = (typeof location !== 'undefined') ? location : null;
  var exitAction = _ttIsExitAction(action);
  var readonly = false;
  if (w && typeof w._detectRuntimeMode === 'function') {
    try { readonly = !!(w._detectRuntimeMode() || {}).readonly; } catch (e) { readonly = false; }
  } else if (loc) {
    readonly = loc.protocol === 'file:' || /^180(8[0-9]|9[0-9])$/.test(loc.port || '');
  }
  if (readonly) return { canWrite: false, reason: '本地预览只读，不发起写入' };
  if (w) {
    if (w._healthConfirmed !== true) return { canWrite: false, reason: '健康状态未确认' };
    if (w._healthCritical === true && !exitAction) return { canWrite: false, reason: '健康门禁阻断' };
    if (w._tradeEntryAllowed === false && !exitAction) return { canWrite: false, reason: '交易录入已关闭' };
  }
  return { canWrite: true, reason: '' };
}

class TradeTicketsWidget extends YiMuWidget {
  constructor(config) {
    super(config);
    this._tickets = null;
    this._loading = false;
    this._error = null;
    this._statusMessage = '';
    this._selectedTicketId = '';
    this._selectedAction = 'buy';
    this._pendingPreview = null;
    this._lastBody = null;
    this._apiLoaded = false;
  }

  render(data) {
    var body = this.getBody();
    if (!body) return;
    this._lastBody = body;
    if (data && Array.isArray(data.trade_tickets) && data.trade_tickets.length) {
      this._tickets = data.trade_tickets;
      this._renderTicketBody(body);
      return;
    }
    if (data && Array.isArray(data.trade_tickets) && this._apiLoaded) {
      this._renderTicketBody(body);
      return;
    }
    if (!this._tickets && !this._loading) {
      this._tickets = [];
      this._renderTicketBody(body);
      this._fetch(body, true);
      return;
    }
    this._renderTicketBody(body);
  }

  _fetch(body, silent) {
    var self = this;
    this._lastBody = body;
    this._loading = true;
    if (!silent) {
      body.innerHTML = '<div class="ui-empty ui-empty-inline"><div class="ui-empty-title">加载票据</div></div>';
    }
    fetch('/api/trade/tickets')
      .then(function(r){ return r.ok ? r.json() : Promise.reject(new Error('load failed')); })
      .then(function(d){
        self._loading = false;
        self._apiLoaded = true;
        self._tickets = (d && Array.isArray(d.tickets)) ? d.tickets : [];
        self._renderTicketBody(body);
      })
      .catch(function(){
        self._loading = false;
        self._error = '票据加载失败';
        self._renderTicketBody(body);
      });
  }

  _ticketAction(ticketId) {
    var tickets = this._tickets || [];
    for (var i = 0; i < tickets.length; i++) {
      if (String(tickets[i].ticket_id || '') === String(ticketId || '')) {
        return tickets[i].action_type || '';
      }
    }
    return '';
  }

  _postJson(url, payload, actionType) {
    var gate = _ttWriteGate(actionType || (payload && payload.action_type));
    if (!gate.canWrite) return Promise.reject(new Error(gate.reason));
    return fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload || {})
    }).then(function(r) {
      return r.json().then(function(d) {
        if (!r.ok || (d && d.ok === false)) {
          throw new Error((d && d.error) || 'request failed');
        }
        return d;
      });
    });
  }

  _readForm(body) {
    function val(sel) {
      var el = body && body.querySelector ? body.querySelector(sel) : null;
      return el ? String(el.value || '').trim() : '';
    }
    var qty = val('[data-tt-qty]');
    return {
      intent_text: val('[data-tt-intent]'),
      action_type: val('[data-tt-action]') || this._selectedAction || 'buy',
      code: val('[data-tt-code]'),
      name: val('[data-tt-name]'),
      window: val('[data-tt-window]') || 'W2',
      qty: qty ? Number(qty) : undefined,
      input_text: val('[data-tt-fill]')
    };
  }

  _refreshTickets() {
    if (this._lastBody) this._fetch(this._lastBody);
  }

  _prepareTicket(payload) {
    var self = this;
    return this._postJson('/api/trade/tickets/prepare', payload, payload && payload.action_type).then(function(d) {
      var ticket = d.ticket || {};
      self._selectedTicketId = ticket.ticket_id || '';
      self._statusMessage = self._selectedTicketId ? '票据已生成 ' + self._selectedTicketId : '票据已生成';
      self._refreshTickets();
      return d;
    }).catch(function(e) {
      self._statusMessage = _ttFriendlyError(e.message || String(e));
      if (self._lastBody) self._renderTicketBody(self._lastBody);
      throw e;
    });
  }

  _previewFill(payload) {
    var self = this;
    payload = payload || {};
    if (!payload.ticket_id) payload.ticket_id = this._selectedTicketId;
    if (!payload.ticket_id) {
      var msg = '请先选择一张票据，或先出票据再预览成交。';
      this._statusMessage = msg;
      if (this._lastBody) this._renderTicketBody(this._lastBody);
      return Promise.reject(new Error(msg));
    }
    return this._postJson('/api/trade/fills/preview', payload, this._ticketAction(payload.ticket_id)).then(function(d) {
      self._pendingPreview = {
        confirmation_id: d.confirmation_id,
        preview_token: d.preview_token,
        preview_hash: d.preview_hash,
        parsed: d.parsed || null
      };
      self._statusMessage = '成交待确认 ' + d.confirmation_id;
      if (self._lastBody) self._renderTicketBody(self._lastBody);
      return d;
    }).catch(function(e) {
      self._statusMessage = _ttFriendlyError(e.message || String(e));
      if (self._lastBody) self._renderTicketBody(self._lastBody);
      throw e;
    });
  }

  _confirmFill(payload) {
    var self = this;
    var pending = this._pendingPreview || {};
    payload = Object.assign({
      confirmation_id: pending.confirmation_id,
      preview_token: pending.preview_token,
      preview_hash: pending.preview_hash,
      confirmed_by: 'yimu'
    }, payload || {});
    return this._postJson('/api/trade/fills/confirm', payload, this._ticketAction(this._selectedTicketId)).then(function(d) {
      self._pendingPreview = null;
      self._statusMessage = d.trade_id ? '成交已写入 trade ' + d.trade_id : '成交已写入';
      self._refreshTickets();
      return d;
    }).catch(function(e) {
      self._statusMessage = _ttFriendlyError(e.message || String(e));
      if (self._lastBody) self._renderTicketBody(self._lastBody);
      throw e;
    });
  }

  _bindActions(body) {
    if (!body || !body.querySelector) return;
    var self = this;
    var prepare = body.querySelector('[data-tt-prepare]');
    var preview = body.querySelector('[data-tt-preview]');
    var confirm = body.querySelector('[data-tt-confirm]');
    if (prepare) prepare.addEventListener('click', function() {
      var form = self._readForm(body);
      self._prepareTicket({
        intent_text: form.intent_text,
        action_type: form.action_type,
        code: form.code,
        name: form.name,
        window: form.window,
        qty: form.qty
      }).catch(function(){});
    });
    if (preview) preview.addEventListener('click', function() {
      var form = self._readForm(body);
      self._previewFill({
        ticket_id: self._selectedTicketId || form.ticket_id,
        input_text: form.input_text
      }).catch(function(){});
    });
    if (confirm) confirm.addEventListener('click', function() {
      self._confirmFill({confirmed_by: 'yimu'}).catch(function(){});
    });
    var actionBtns = body.querySelectorAll ? body.querySelectorAll('[data-tt-action-set]') : [];
    Array.prototype.forEach.call(actionBtns, function(btn) {
      btn.addEventListener('click', function() {
        var action = btn.getAttribute('data-tt-action-set') || 'buy';
        self._selectedAction = action;
        var input = body.querySelector('[data-tt-action]');
        if (input) input.value = action;
        self._statusMessage = '已选择动作：' + _ttActionLabel(action);
        self._renderTicketBody(body);
      });
    });
    var ticketBtns = body.querySelectorAll ? body.querySelectorAll('[data-tt-select]') : [];
    Array.prototype.forEach.call(ticketBtns, function(btn) {
      btn.addEventListener('click', function() {
        self._selectedTicketId = btn.getAttribute('data-tt-select') || '';
        self._statusMessage = self._selectedTicketId ? '已选票据：' + self._selectedTicketId : '';
        self._renderTicketBody(body);
      });
    });
  }

  _summaryPill(label, count, tone) {
    return '<div class="ticket-summary-pill">' +
      '<div class="ticket-summary-label">' + _ttEsc(label) + '</div>' +
      '<div class="ticket-summary-value" style="color:var(--' + tone + ')">' + _ttEsc(count) + '</div>' +
    '</div>';
  }

  _acceptanceStep(stage, label, value, detail, active) {
    return '<div class="ticket-acceptance-step' + (active ? ' is-active' : '') + '" data-ticket-stage="' + _ttEsc(stage) + '">' +
      '<span>' + _ttEsc(label) + '</span>' +
      '<b>' + _ttEsc(value) + '</b>' +
      '<em>' + _ttEsc(detail) + '</em>' +
    '</div>';
  }

  _acceptanceRail(counts) {
    counts = counts || {};
    return '<div class="ticket-acceptance-rail" aria-label="票据验收路径">' +
      this._acceptanceStep('handoff', 'AI交付', counts.pending, counts.pending ? '待确认票据' : '无待确认', counts.pending > 0) +
      this._acceptanceStep('execute', '终端执行', counts.exec, counts.exec ? '等待成交回填' : '无可执行', counts.exec > 0) +
      this._acceptanceStep('review', '规则复核', counts.blocked, counts.blocked ? '存在阻断' : '无阻断', counts.blocked > 0) +
      this._acceptanceStep('closed', '闭环对账', counts.filled + '/' + counts.total, counts.total ? '已闭环/总票据' : '无票据', counts.filled > 0 || counts.total === 0) +
    '</div>';
  }

  _chainStep(stage, label, value, detail, tone) {
    return '<div class="ticket-chain-step' + (tone ? ' tone-' + _ttEsc(tone) : '') + '" data-ticket-chain="' + _ttEsc(stage) + '">' +
      '<span>' + _ttEsc(label) + '</span>' +
      '<b>' + _ttEsc(value) + '</b>' +
      '<em>' + _ttEsc(detail) + '</em>' +
    '</div>';
  }

  _executionChain(counts) {
    counts = counts || {};
    return '<div class="ticket-execution-chain" aria-label="票据到持仓执行链">' +
      '<div class="ticket-chain-title"><span>执行链</span><b>AI → 终端 → 账户</b></div>' +
      this._chainStep('ticket', 'E2票据', counts.total + '张票据', counts.exec ? counts.exec + '张待执行' : '票据已分流', '') +
      this._chainStep('trade', 'W23成交', counts.linkedTrades + '笔成交', counts.filled ? counts.filled + '张已回填' : '等待回填', '') +
      this._chainStep('account', 'E1账户', counts.accountPending + '张待核', counts.accountPending ? '到 W15 核对' : '暂无账户动作', '') +
      this._chainStep('risk', '异常', counts.conflicts + '项冲突', counts.conflicts ? '需复核' : '无冲突', counts.conflicts ? 'danger' : '') +
    '</div>';
  }

  _section(title, tickets, tone, compact) {
    var html = '<div class="ticket-section"><div class="ticket-section-title"><span>' +
      _ttEsc(title) + '</span><span class="ticket-section-count">' + tickets.length + '</span></div>';
    if (!tickets.length) {
      return html + '<div class="ui-empty ui-empty-inline"><div class="ui-empty-title">暂无</div></div></div>';
    }
    var self = this;
    tickets.slice(0, compact ? 6 : 8).forEach(function(t) {
      var blocks = t.blocking_rule_ids || [];
      var missing = t.missing_required_data || [];
      var trades = _ttList(t.linked_trade_ids || t.trade_ids);
      var conflicts = _ttList(t.conflicts || t.ticket_conflict_log || t.conflict_log);
      var blockText = blocks.length ? blocks.join(', ') : '';
      var missingText = missing.length ? missing.join(', ') : '';
      var conflictText = conflicts.map(function(c) {
        if (typeof c === 'string') return c;
        var typ = c.conflict_type || c.type || 'conflict';
        var exp = c.expected_value != null ? c.expected_value : c.expected;
        var act = c.actual_value != null ? c.actual_value : c.actual;
        var tail = (exp != null || act != null) ? ' ' + (exp == null ? '?' : exp) + ' vs ' + (act == null ? '?' : act) : '';
        return typ + tail;
      }).join(' | ');
      var selected = self._selectedTicketId && self._selectedTicketId === t.ticket_id;
      var qty = t.max_qty != null ? t.max_qty : (t.qty != null ? t.qty : '');
      var effectiveStatus = _ttEffectiveStatus(t);
      var blockLabel = effectiveStatus === 'audit_degraded' ? '审计原因 ' : '阻断原因 ';
      var blockTone = effectiveStatus === 'audit_degraded' ? 'warn' : 'danger';
      var titleText = (t.name || t.code || '未命名') + '｜' + _ttActionLabel(t.action_type) + (qty ? ' ' + qty + '股' : '');
      html += '<button class="ticket-card' + (selected ? ' is-selected' : '') + '" data-tt-select="' + _ttEsc(t.ticket_id) + '" style="--ticket-tone:var(--' + tone + ')">' +
        '<div class="ticket-card-head">' +
          '<span class="ticket-card-title">' + _ttEsc(titleText) + '</span>' +
          '<span class="ticket-card-status">' + _ttEsc(_ttStatusLabel(effectiveStatus)) + '</span>' +
        '</div>' +
        '<div class="ticket-card-meta">' +
          (t.window ? '<span>窗口 ' + _ttEsc(t.window) + '</span>' : '') +
          (t.sellable_quantity != null ? '<span>可卖 ' + _ttEsc(t.sellable_quantity) + '</span>' : '') +
          (t.target_lot_id ? '<span>目标 ' + _ttEsc(t.target_lot_id) + '</span>' : '') +
        '</div>' +
        (trades.length ? '<div class="ticket-card-note trade-link">已关联成交 trade ' + _ttEsc(trades.join(',')) + '</div>' : '') +
        (t.ticket_id ? '<div class="ticket-card-note mono" title="' + _ttEsc(t.ticket_id) + '">' + _ttEsc(t.ticket_id) + '</div>' : '') +
        (blockText ? '<div class="ticket-card-note ' + blockTone + '" title="' + _ttEsc(blockText) + '">' + blockLabel + _ttEsc(blockText) + '</div>' : '') +
        (missingText ? '<div class="ticket-card-note warn" title="' + _ttEsc(missingText) + '">缺数据 ' + _ttEsc(missingText) + '</div>' : '') +
        (conflictText ? '<div class="ticket-card-note danger" title="' + _ttEsc(conflictText) + '">冲突 ' + _ttEsc(conflictText) + '</div>' : '') +
      '</button>';
    });
    return html + '</div>';
  }

  _renderTicketBody(body) {
    if (this._error) {
      body.innerHTML = '<div class="ticket-brief-head"><span><span class="evidence-inline-ref">E2</span>票据闭环</span><span>降级</span></div>' +
        '<div class="ticket-degraded ui-degraded"><strong>票据接口不可达</strong><span>' + _ttEsc(this._error) + '，当前只读态势保留，真实操作请先复核 8088 服务。</span></div>';
      this.updateTimestamp();
      return;
    }
    var allTickets = this._tickets || [];
    var tickets = allTickets.filter(function(t) { return !_ttIsSupersededAuditTicket(t, allTickets); });
    var pending = tickets.filter(function(t){ var s = _ttEffectiveStatus(t); return s === 'confirmed' || s === 'draft'; });
    var exec = tickets.filter(function(t){ var s = _ttEffectiveStatus(t); return s === 'audit_degraded' || s === 'executable'; });
    var blocked = tickets.filter(function(t){ return _ttEffectiveStatus(t) === 'blocked'; });
    var done = tickets.filter(function(t){ return ['filled','partially_filled','closed','closed_with_conflict','cancelled'].indexOf(_ttEffectiveStatus(t)) >= 0; });
    var filled = done.filter(function(t){ return ['filled','partially_filled','closed','closed_with_conflict'].indexOf(_ttEffectiveStatus(t)) >= 0; });
    var cancelled = done.filter(function(t){ return _ttEffectiveStatus(t) === 'cancelled'; });
    var linkedTrades = [];
    var conflictCount = 0;
    tickets.forEach(function(t) {
      linkedTrades = linkedTrades.concat(_ttList(t.linked_trade_ids || t.trade_ids));
      conflictCount += _ttList(t.conflicts || t.ticket_conflict_log || t.conflict_log).length;
    });
    var pendingText = this._pendingPreview ? ('待确认 ' + this._pendingPreview.confirmation_id) : '';
    var selectedText = this._selectedTicketId ? '当前票据 ' + this._selectedTicketId : '未选择票据';
    var activeAction = this._selectedAction || 'buy';
    var writeGate = _ttWriteGate(activeAction);
    if (!writeGate.canWrite && activeAction !== 'clear') {
      var exitGate = _ttWriteGate('clear');
      if (exitGate.canWrite) writeGate = exitGate;
    }
    var counts = {
      pending: pending.length,
      exec: exec.length,
      blocked: blocked.length,
      filled: filled.length,
      total: tickets.length,
      linkedTrades: linkedTrades.length,
      accountPending: filled.length,
      conflicts: conflictCount
    };
    var nextAction = pending.length ? '复核待确认票据' :
      exec.length ? '等待终端执行回填' :
      blocked.length ? '复核阻断原因' :
      filled.length ? '核对已成交闭环' : '暂无票据动作';
    function actionButton(action, label) {
      var active = activeAction === action;
      return '<button class="ticket-action-toggle' + (active ? ' is-active' : '') + '" data-tt-action-set="' + _ttEsc(action) + '">' + _ttEsc(label) + '</button>';
    }
    var emergencyHtml = writeGate.canWrite ?
      '<div class="ticket-emergency-dock">' +
      '<details class="ticket-emergency-entry">' +
      '<summary><span>应急</span><em>手工出票 / 成交确认</em></summary>' +
      '<div class="ticket-entry-grid">' +
      '<div class="ticket-entry-main">' +
        '<div class="ticket-action-row">' +
          actionButton('buy', '买入') +
          actionButton('add', '加仓') +
          actionButton('reduce', '减仓') +
          actionButton('clear', '清仓') +
          actionButton('do_t', '做T') +
          actionButton('observe', '观察') +
        '</div>' +
        '<input data-tt-action value="' + _ttEsc(activeAction) + '" type="hidden">' +
        '<div class="ticket-prepare-grid">' +
          '<input class="ticket-input" data-tt-intent placeholder="准备 W2 买 光迅科技 200股">' +
          '<input class="ticket-input" data-tt-code placeholder="代码">' +
          '<input class="ticket-input" data-tt-name placeholder="名称">' +
          '<input class="ticket-input" data-tt-window placeholder="W2" value="W2">' +
          '<input class="ticket-input" data-tt-qty placeholder="股数">' +
        '</div>' +
        '<input class="ticket-input ticket-fill-input" data-tt-fill placeholder="成交口令：已买/已卖 光迅科技 200股 232.30">' +
      '</div>' +
      '<div class="ticket-entry-actions">' +
        '<button class="ticket-command-btn" data-tt-prepare>出票据</button>' +
        '<button class="ticket-command-btn" data-tt-preview>预览成交</button>' +
        '<button class="ticket-command-btn" data-tt-confirm>确认入账</button>' +
      '</div>' +
      ((this._statusMessage || pendingText || selectedText) ? '<div class="ticket-status-line' + (this._statusMessage ? ' has-message' : '') + '">' + _ttEsc(this._statusMessage || pendingText || selectedText) + '</div>' : '') +
    '</div></details></div>' :
      '<div class="ticket-readonly-lock ui-empty ui-empty-inline"><div class="ui-empty-title">只读闭环</div><div class="ui-empty-detail">' + _ttEsc(writeGate.reason) + '，票据状态仅用于核对。</div></div>';
    body.innerHTML = '<div class="ticket-brief-head"><span><span class="evidence-inline-ref">E2</span>票据闭环</span><span>已成交 ' + filled.length + ' / 已取消 ' + cancelled.length + '</span></div>' +
    '<div class="ticket-command-strip">' +
      '<div><span class="evidence-inline-ref">E2</span><b>AI验收台</b><em>票据由 AI/终端生成与执行，本面板只做状态核对。</em></div>' +
      '<div><span>下一步</span><b>' + _ttEsc(nextAction) + '</b><em>' + _ttEsc(selectedText) + '</em></div>' +
      '<div><span>闭环</span><b>' + filled.length + '/' + tickets.length + '</b><em>成交 ' + filled.length + ' · 取消 ' + cancelled.length + '</em></div>' +
    '</div>' +
    this._executionChain(counts) +
    this._acceptanceRail(counts) +
    '<div class="ticket-summary-grid">' +
      this._summaryPill('待确认', pending.length, 'info') +
      this._summaryPill('可执行', exec.length, 'up') +
      this._summaryPill('已阻断', blocked.length, 'danger') +
      this._summaryPill('已成交', filled.length, 'text-secondary') +
      this._summaryPill('已取消', cancelled.length, 'text-disabled') +
      '</div>' +
      '<div class="ticket-layout">' +
      '<div class="ticket-primary-sections">' +
      this._section('待确认', pending, 'info') +
      this._section('可执行', exec, 'up') +
      this._section('已阻断', blocked, 'danger') +
      '</div>' +
      '<div class="ticket-history-section">' +
      this._section('已成交/关闭', filled, 'text-secondary', true) +
      (cancelled.length ? '<details style="margin-top:6px"><summary style="font-size:var(--fs-label);color:var(--text-disabled);cursor:pointer">已取消 ' + cancelled.length + '</summary>' + this._section('取消记录', cancelled, 'text-disabled', true) + '</details>' : '') +
      '</div>' +
      '</div>' +
      emergencyHtml;
    this._bindActions(body);
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W24', TradeTicketsWidget);
