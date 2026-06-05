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

class TradeTicketsWidget extends YiMuWidget {
  constructor(config) {
    super(config);
    this._tickets = null;
    this._loading = false;
    this._error = null;
    this._statusMessage = '';
    this._selectedTicketId = '';
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
      action_type: val('[data-tt-action]') || 'buy',
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
      self._statusMessage = e.message || String(e);
      if (self._lastBody) self._renderTicketBody(self._lastBody);
      throw e;
    });
  }

  _previewFill(payload) {
    var self = this;
    payload = payload || {};
    if (!payload.ticket_id) payload.ticket_id = this._selectedTicketId;
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
      self._statusMessage = e.message || String(e);
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
      self._statusMessage = e.message || String(e);
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
  }

  _section(title, tickets, tone) {
    var html = '<div style="min-width:0"><div style="font-size:var(--fs-label);font-weight:700;color:var(--text-secondary);margin-bottom:4px">' +
      _ttEsc(title) + ' <span style="font-family:var(--font-mono);color:var(--text-disabled)">' + tickets.length + '</span></div>';
    if (!tickets.length) {
      return html + '<div style="padding:8px;border:1px dashed var(--border);border-radius:var(--radius-sm);color:var(--text-disabled);font-size:var(--fs-small);text-align:center">空</div></div>';
    }
    tickets.slice(0, 8).forEach(function(t) {
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
      html += '<div style="border:1px solid var(--border);border-left:3px solid var(--' + tone + ');border-radius:var(--radius-sm);padding:6px;margin-bottom:6px;background:var(--bg-card)">' +
        '<div style="display:flex;justify-content:space-between;gap:6px;align-items:center">' +
          '<span style="font-weight:700;font-size:var(--fs-body)">' + _ttEsc(t.name || t.code) + '</span>' +
          '<span style="font-family:var(--font-mono);font-size:10px;color:var(--text-disabled)">' + _ttEsc(t.ticket_id) + '</span>' +
        '</div>' +
        '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:4px;font-size:var(--fs-small);color:var(--text-secondary)">' +
          '<span>' + _ttEsc(t.action_type) + '</span><span>' + _ttEsc(t.status) + '</span>' +
          (t.window ? '<span>' + _ttEsc(t.window) + '</span>' : '') +
          (t.max_qty ? '<span>qty ' + _ttEsc(t.max_qty) + '</span>' : '') +
          (t.sellable_quantity != null ? '<span>可卖 ' + _ttEsc(t.sellable_quantity) + '</span>' : '') +
        '</div>' +
        (trades.length ? '<div style="margin-top:4px;font-size:10px;color:var(--text-secondary);font-family:var(--font-mono)">trade ' + _ttEsc(trades.join(',')) + '</div>' : '') +
        (blockText ? '<div style="margin-top:4px;font-size:10px;color:var(--danger);white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="' + _ttEsc(blockText) + '">' + _ttEsc(blockText) + '</div>' : '') +
        (missingText ? '<div style="margin-top:4px;font-size:10px;color:var(--warn);white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="' + _ttEsc(missingText) + '">缺数据 ' + _ttEsc(missingText) + '</div>' : '') +
        (conflictText ? '<div style="margin-top:4px;font-size:10px;color:var(--danger);white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="' + _ttEsc(conflictText) + '">' + _ttEsc(conflictText) + '</div>' : '') +
      '</div>';
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
    var pendingText = this._pendingPreview ? ('待确认 ' + this._pendingPreview.confirmation_id) : '';
    body.innerHTML = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(88px,1fr));gap:6px;margin-bottom:8px;align-items:end">' +
      '<input data-tt-intent placeholder="意图" style="min-width:0;padding:5px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:11px">' +
      '<input data-tt-action placeholder="buy/sell" value="buy" style="min-width:0;padding:5px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:11px">' +
      '<input data-tt-code placeholder="代码" style="min-width:0;padding:5px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:11px">' +
      '<input data-tt-name placeholder="名称" style="min-width:0;padding:5px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:11px">' +
      '<input data-tt-window placeholder="W2" value="W2" style="min-width:0;padding:5px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:11px">' +
      '<input data-tt-qty placeholder="股数" style="min-width:0;padding:5px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:11px">' +
      '<input data-tt-fill placeholder="已买/已卖 ..." style="grid-column:1/-1;min-width:0;padding:5px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:11px">' +
      '<button data-tt-prepare style="padding:5px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg-card);font-size:11px">出票据</button>' +
      '<button data-tt-preview style="padding:5px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg-card);font-size:11px">预览成交</button>' +
      '<button data-tt-confirm style="padding:5px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg-card);font-size:11px">确认成交</button>' +
      ((this._statusMessage || pendingText) ? '<div style="grid-column:1/-1;color:var(--text-secondary);font-size:10px;font-family:var(--font-mono)">' + _ttEsc(this._statusMessage || pendingText) + '</div>' : '') +
      '</div>' +
      '<div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:var(--sp-sm);font-size:var(--fs-body)">' +
      this._section('待确认', pending, 'info') +
      this._section('可执行', exec, 'up') +
      this._section('已阻断', blocked, 'danger') +
      this._section('已成交/关闭', done, 'text-secondary') +
      '</div>';
    this._bindActions(body);
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W24', TradeTicketsWidget);
