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

function _ttFriendlyError(message) {
  var text = String(message || '');
  if (/ticket not found/i.test(text)) return '请先选择一张票据，或先出票据再预览成交。';
  if (/preview|confirmation/i.test(text)) return '还没有可确认的成交预览，请先点“预览成交”。';
  return text || '操作失败，请稍后重试。';
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
      body.innerHTML = '<div style="padding:var(--sp-md);text-align:center;color:var(--text-disabled)">加载票据...</div>';
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

  _postJson(url, payload) {
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
    return this._postJson('/api/trade/tickets/prepare', payload).then(function(d) {
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
    return this._postJson('/api/trade/fills/preview', payload).then(function(d) {
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
    return this._postJson('/api/trade/fills/confirm', payload).then(function(d) {
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
    return '<div style="border:1px solid var(--border-light);border-radius:var(--radius-sm);padding:6px 8px;background:var(--bg-card);min-width:0">' +
      '<div style="font-size:10px;color:var(--text-disabled);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + _ttEsc(label) + '</div>' +
      '<div style="font-family:var(--font-mono);font-size:16px;font-weight:800;color:var(--' + tone + ');line-height:1.1;margin-top:2px">' + _ttEsc(count) + '</div>' +
    '</div>';
  }

  _section(title, tickets, tone, compact) {
    var html = '<div style="min-width:0"><div style="font-size:var(--fs-label);font-weight:700;color:var(--text-secondary);margin-bottom:4px">' +
      _ttEsc(title) + ' <span style="font-family:var(--font-mono);color:var(--text-disabled)">' + tickets.length + '</span></div>';
    if (!tickets.length) {
      return html + '<div style="padding:10px 8px;border:1px dashed var(--border-light);border-radius:var(--radius-sm);color:var(--text-disabled);font-size:var(--fs-small);text-align:center;background:var(--bg-soft)">暂无</div></div>';
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
      var titleText = (t.name || t.code || '未命名') + '｜' + _ttActionLabel(t.action_type) + (qty ? ' ' + qty + '股' : '');
      html += '<button data-tt-select="' + _ttEsc(t.ticket_id) + '" style="display:block;width:100%;text-align:left;border:1px solid ' + (selected ? 'var(--info)' : 'var(--border)') + ';border-left:4px solid var(--' + tone + ');border-radius:var(--radius-sm);padding:8px;margin-bottom:7px;background:' + (selected ? 'var(--bg-soft)' : 'var(--bg-card)') + ';cursor:pointer;color:var(--text-primary)">' +
        '<div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start">' +
          '<span style="font-weight:800;font-size:var(--fs-body);line-height:1.25;min-width:0;word-break:break-word">' + _ttEsc(titleText) + '</span>' +
          '<span style="flex:0 0 auto;border:1px solid var(--border-light);border-radius:999px;padding:1px 6px;font-size:10px;color:var(--text-secondary);background:var(--bg-soft)">' + _ttEsc(_ttStatusLabel(t.status)) + '</span>' +
        '</div>' +
        '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:4px;font-size:var(--fs-small);color:var(--text-secondary)">' +
          (t.window ? '<span>窗口 ' + _ttEsc(t.window) + '</span>' : '') +
          (t.sellable_quantity != null ? '<span>可卖 ' + _ttEsc(t.sellable_quantity) + '</span>' : '') +
          (t.target_lot_id ? '<span>目标 ' + _ttEsc(t.target_lot_id) + '</span>' : '') +
        '</div>' +
        (trades.length ? '<div style="margin-top:4px;font-size:10px;color:var(--text-secondary);font-family:var(--font-mono)">已关联成交 trade ' + _ttEsc(trades.join(',')) + '</div>' : '') +
        (t.ticket_id ? '<div style="margin-top:4px;font-size:10px;color:var(--text-disabled);font-family:var(--font-mono);white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="' + _ttEsc(t.ticket_id) + '">' + _ttEsc(t.ticket_id) + '</div>' : '') +
        (blockText ? '<div style="margin-top:4px;font-size:10px;color:var(--danger);white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="' + _ttEsc(blockText) + '">阻断原因 ' + _ttEsc(blockText) + '</div>' : '') +
        (missingText ? '<div style="margin-top:4px;font-size:10px;color:var(--warn);white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="' + _ttEsc(missingText) + '">缺数据 ' + _ttEsc(missingText) + '</div>' : '') +
        (conflictText ? '<div style="margin-top:4px;font-size:10px;color:var(--danger);white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="' + _ttEsc(conflictText) + '">冲突 ' + _ttEsc(conflictText) + '</div>' : '') +
      '</button>';
    });
    return html + '</div>';
  }

  _renderTicketBody(body) {
    if (this._error) {
      body.innerHTML = '<div style="padding:var(--sp-md);text-align:center;color:var(--danger)">' + _ttEsc(this._error) + '</div>';
      this.updateTimestamp();
      return;
    }
    var tickets = this._tickets || [];
    var pending = tickets.filter(function(t){ return t.status === 'confirmed' || t.status === 'draft'; });
    var exec = tickets.filter(function(t){ return t.status === 'executable'; });
    var blocked = tickets.filter(function(t){ return t.status === 'blocked' || t.status === 'audit_degraded'; });
    var done = tickets.filter(function(t){ return ['filled','partially_filled','closed','closed_with_conflict','cancelled'].indexOf(t.status) >= 0; });
    var filled = done.filter(function(t){ return ['filled','partially_filled','closed','closed_with_conflict'].indexOf(t.status) >= 0; });
    var cancelled = done.filter(function(t){ return t.status === 'cancelled'; });
    var pendingText = this._pendingPreview ? ('待确认 ' + this._pendingPreview.confirmation_id) : '';
    var selectedText = this._selectedTicketId ? '当前票据 ' + this._selectedTicketId : '未选择票据';
    var activeAction = this._selectedAction || 'buy';
    function actionButton(action, label) {
      var active = activeAction === action;
      return '<button data-tt-action-set="' + _ttEsc(action) + '" style="padding:4px 8px;border:1px solid ' + (active ? 'var(--info)' : 'var(--border)') + ';border-radius:var(--radius-sm);background:' + (active ? 'var(--bg-soft)' : 'var(--bg-card)') + ';font-size:11px;font-weight:' + (active ? '800' : '500') + '">' + _ttEsc(label) + '</button>';
    }
    body.innerHTML = '<div style="display:grid;grid-template-columns:1fr auto;gap:8px;margin-bottom:8px;align-items:start">' +
      '<div style="min-width:0">' +
        '<div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:6px">' +
          actionButton('buy', '买入') +
          actionButton('add', '加仓') +
          actionButton('reduce', '减仓') +
          actionButton('clear', '清仓') +
          actionButton('do_t', '做T') +
          actionButton('observe', '观察') +
        '</div>' +
        '<input data-tt-action value="' + _ttEsc(activeAction) + '" type="hidden">' +
        '<div style="display:grid;grid-template-columns:2fr 72px 1.2fr 70px 80px;gap:5px;margin-bottom:5px">' +
          '<input data-tt-intent placeholder="准备 W2 买 光迅科技 200股" style="min-width:0;padding:6px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:11px">' +
          '<input data-tt-code placeholder="代码" style="min-width:0;padding:6px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:11px">' +
          '<input data-tt-name placeholder="名称" style="min-width:0;padding:6px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:11px">' +
          '<input data-tt-window placeholder="W2" value="W2" style="min-width:0;padding:6px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:11px">' +
          '<input data-tt-qty placeholder="股数" style="min-width:0;padding:6px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:11px">' +
        '</div>' +
        '<input data-tt-fill placeholder="成交口令：已买/已卖 光迅科技 200股 232.30" style="width:100%;box-sizing:border-box;min-width:0;padding:6px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:11px">' +
      '</div>' +
      '<div style="display:grid;grid-template-columns:1fr;gap:5px;min-width:112px">' +
        '<button data-tt-prepare style="padding:7px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg-card);font-weight:700;font-size:11px">出票据</button>' +
        '<button data-tt-preview style="padding:7px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg-card);font-weight:700;font-size:11px">预览成交</button>' +
        '<button data-tt-confirm style="padding:7px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg-card);font-weight:700;font-size:11px">确认入账</button>' +
      '</div>' +
      ((this._statusMessage || pendingText || selectedText) ? '<div style="grid-column:1/-1;color:' + (this._statusMessage ? 'var(--text-secondary)' : 'var(--text-disabled)') + ';font-size:10px;font-family:var(--font-mono);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + _ttEsc(this._statusMessage || pendingText || selectedText) + '</div>' : '') +
    '</div>' +
    '<div style="display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px;margin-bottom:8px">' +
      this._summaryPill('待确认', pending.length, 'info') +
      this._summaryPill('可执行', exec.length, 'up') +
      this._summaryPill('已阻断', blocked.length, 'danger') +
      this._summaryPill('已成交', filled.length, 'text-secondary') +
      this._summaryPill('已取消', cancelled.length, 'text-disabled') +
      '</div>' +
      '<div style="display:grid;grid-template-columns:2fr 1fr;gap:var(--sp-sm);font-size:var(--fs-body);align-items:start">' +
      '<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--sp-sm);min-width:0">' +
      this._section('待确认', pending, 'info') +
      this._section('可执行', exec, 'up') +
      this._section('已阻断', blocked, 'danger') +
      '</div>' +
      '<div style="min-width:0">' +
      this._section('已成交/关闭', filled, 'text-secondary', true) +
      (cancelled.length ? '<details style="margin-top:6px"><summary style="font-size:var(--fs-label);color:var(--text-disabled);cursor:pointer">已取消 ' + cancelled.length + '</summary>' + this._section('取消记录', cancelled, 'text-disabled', true) + '</details>' : '') +
      '</div>' +
      '</div>';
    this._bindActions(body);
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W24', TradeTicketsWidget);
