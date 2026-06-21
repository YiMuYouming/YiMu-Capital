// widgets/evidence-board.js — W25 态势证据屏
'use strict';

function _evEsc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function _evToneClass(tone) {
  if (tone === 'up') return ' evidence-tone-up';
  if (tone === 'down') return ' evidence-tone-down';
  if (tone === 'warn') return ' evidence-tone-warn';
  if (tone === 'danger') return ' evidence-tone-danger';
  return '';
}
function _evStateClass(state) {
  if (state === '通过') return ' is-pass';
  if (state === '提示') return ' is-warn';
  if (state === '阻断') return ' is-blocked';
  return ' is-neutral';
}
function _evCommandClass(tone) {
  if (tone === 'ready') return ' is-ready';
  if (tone === 'warn') return ' is-warn';
  if (tone === 'blocked') return ' is-blocked';
  return ' is-watch';
}
function _evWidgetLabel(wid) {
  var map = {
    W04: '情绪数据',
    W08: 'W1 信号',
    W09: 'W2 信号',
    W14: '风控门禁',
    W15: '账户持仓',
    W20: 'AI 研判',
    W24: '票据队列'
  };
  return map[wid] || wid || '相关组件';
}

class EvidenceBoardWidget extends YiMuWidget {
  _runtime() {
    var _win = typeof window !== 'undefined' ? window : (typeof global !== 'undefined' ? global : {});
    var _doc = typeof document !== 'undefined' ? document : null;
    var healthEl = null;
    try {
      if (_doc && typeof _doc.getElementById === 'function') healthEl = _doc.getElementById('healthLabel');
    } catch(e) { /* env without DOM */ }
    return {
      healthLabel: healthEl && healthEl.textContent ? healthEl.textContent : '',
      healthCritical: _win._healthCritical === true,
      healthConfirmed: _win._healthConfirmed === true,
      tradeEntryAllowed: _win._tradeEntryAllowed === true,
      connectionStatus: (typeof DataStore !== 'undefined' && DataStore.getConnectionStatus) ? DataStore.getConnectionStatus() : '',
      quoteHealthStatus: _win._quoteHealthStatus ? _win._quoteHealthStatus : ''
    };
  }

  _card(item) {
    var target = this._traceTarget(item);
    var traceAttrs = target ?
      ' evidence-card-trace" role="button" tabindex="0" data-evidence-target="' + _evEsc(target) + '" title="追溯到 ' + _evEsc(item.source || target) + '"' :
      '"';
    return '<div class="evidence-card' + _evToneClass(item.tone) + traceAttrs + ' data-evidence-id="' + _evEsc(item.id) + '">' +
      '<div class="evidence-card-title"><span class="evidence-ref">' + _evEsc(item.id) + '</span><span>' + _evEsc(item.title) + '</span><span class="evidence-source">' + _evEsc(item.source || '') + '</span></div>' +
      '<div class="evidence-card-value">' + _evEsc(item.value || '') + '</div>' +
      '<div class="evidence-card-detail">' + _evEsc(item.detail || '') + '</div>' +
    '</div>';
  }

  _gate(gate) {
    gate = gate || {};
    var traceTarget = gate.target ? this._traceTarget({ source: gate.target }) : '';
    var target = traceTarget ? ' data-evidence-target="' + _evEsc(traceTarget) + '"' : '';
    return '<div class="evidence-gate' + _evStateClass(gate.state) + (traceTarget ? ' evidence-gate-trace' : '') + '"' + target + ' role="' + (traceTarget ? 'button' : 'group') + '" tabindex="' + (traceTarget ? '0' : '-1') + '">' +
      '<div class="evidence-gate-head"><span>' + _evEsc(gate.id || '') + '</span><b>' + _evEsc(gate.title || '') + '</b><em>' + _evEsc(gate.state || '—') + '</em></div>' +
      '<div class="evidence-gate-value">' + _evEsc(gate.value || '—') + '</div>' +
      '<div class="evidence-gate-detail">' + _evEsc(gate.detail || '') + '</div>' +
    '</div>';
  }

  _queueItem(item) {
    item = item || {};
    var cls = item.tone === 'danger' ? ' is-danger' : item.tone === 'ready' ? ' is-ready' : item.tone === 'warn' ? ' is-warn' : '';
    var traceTarget = item.trace_target || (item.target ? this._traceTarget({ source: item.target }) : '');
    var target = traceTarget ? ' data-evidence-target="' + _evEsc(traceTarget) + '"' : '';
    return '<div class="evidence-queue-item evidence-card-trace' + cls + '"' + target + ' role="button" tabindex="0">' +
      '<span>' + _evEsc(item.id || '') + '</span>' +
      '<div><b>' + _evEsc(item.label || item.title || '') + '</b><em>' + _evEsc(item.reason || '') + '</em></div>' +
      '<strong>' + _evEsc(item.caption || (item.target ? (_evWidgetLabel(item.target) + ' · ' + item.target) : '')) + '</strong>' +
    '</div>';
  }

  _actionButton(item) {
    item = item || {};
    var traceTarget = item.trace_target || (item.target ? this._traceTarget({ source: item.target }) : '');
    var target = traceTarget ? ' data-evidence-target="' + _evEsc(traceTarget) + '"' : '';
    return '<button type="button" class="evidence-action-button evidence-card-trace"' + target + '>' +
      '<span>' + _evEsc(item.label || '打开相关组件') + '</span>' +
      '<em>' + _evEsc(item.caption || '') + '</em>' +
    '</button>';
  }

  _freshnessTarget(id) {
    var map = {
      quotes: 'W15',
      iwencai: 'W04',
      account: 'W15',
      baseline: 'W14',
      tickets: 'W24',
      llm: 'W20',
      ai_context: 'W20'
    };
    return map[id] || '';
  }

  _freshnessRow(row) {
    row = row || {};
    var status = row.status || 'unknown';
    var cls = row.tone === 'blocked' ? ' is-blocked' : row.tone === 'warn' ? ' is-warn' : row.tone === 'live' ? ' is-live' : '';
    var traceTarget = this._traceTarget({ source: row.target || this._freshnessTarget(row.id) });
    var target = traceTarget ? ' data-evidence-target="' + _evEsc(traceTarget) + '"' : '';
    var trading = row.trading ? '可用于交易' : (status === 'stale' || status === 'dead' || status === 'missing' || status === 'error' || status === 'blocked' ? '不可交易' : '仅观察');
    return '<div class="evidence-freshness-row evidence-card-trace' + cls + '"' + target + ' role="' + (traceTarget ? 'button' : 'group') + '" tabindex="' + (traceTarget ? '0' : '-1') + '">' +
      '<span>' + _evEsc(row.label || row.id || '') + '</span>' +
      '<b>' + _evEsc(status) + '</b>' +
      '<em>' + _evEsc(row.source || '') + '</em>' +
      '<strong>' + _evEsc(trading) + '</strong>' +
      '<small>' + _evEsc(row.detail || '') + '</small>' +
    '</div>';
  }

  _freshnessSummary(summary) {
    summary = summary || {};
    var total = summary.total == null ? '—' : summary.total;
    var tradable = summary.tradable_count == null ? '—' : summary.tradable_count;
    var review = summary.review_count == null ? '—' : summary.review_count;
    return '<div class="evidence-freshness-summary">' +
      '<div><span>可交易</span><b>' + _evEsc(tradable) + '/' + _evEsc(total) + '</b></div>' +
      '<div><span>需复核</span><b>' + _evEsc(review) + '</b></div>' +
    '</div>';
  }

  _focusChip(item) {
    var wid = typeof item === 'string' ? item : (item && (item.id || item.widget || item.target));
    var traceTarget = this._traceTarget({ source: wid || '' });
    var target = traceTarget ? ' data-evidence-target="' + _evEsc(traceTarget) + '"' : '';
    return '<button type="button" class="evidence-focus-chip"' + target + '><span>' + _evEsc(_evWidgetLabel(wid)) + '</span><em>' + _evEsc(wid || '—') + '</em></button>';
  }

  _evidenceItem(item) {
    item = item || {};
    var target = this._traceTarget(item);
    var targetAttr = target ? ' data-evidence-target="' + _evEsc(target) + '"' : '';
    var cls = item.tone === 'danger' ? ' is-danger' : item.tone === 'warn' ? ' is-warn' : item.tone === 'up' ? ' is-up' : item.tone === 'down' ? ' is-down' : '';
    return '<div class="evidence-compact-item evidence-card-trace' + cls + '"' + targetAttr + ' role="' + (target ? 'button' : 'group') + '" tabindex="' + (target ? '0' : '-1') + '">' +
      '<span>' + _evEsc(item.id || '') + '</span>' +
      '<div><b>' + _evEsc(item.title || '') + '</b><em>' + _evEsc(item.detail || item.source || '') + '</em></div>' +
      '<strong>' + _evEsc(item.value || item.source || '') + '</strong>' +
    '</div>';
  }

  _miniRef(item) {
    item = item || {};
    var target = this._traceTarget(item);
    var targetAttr = target ? ' data-evidence-target="' + _evEsc(target) + '"' : '';
    return '<div class="evidence-mini-ref' + _evToneClass(item.tone) + '"' + targetAttr + '>' +
      '<span>' + _evEsc(item.id || '') + '</span><b>' + _evEsc(item.title || '') + '</b><em>' + _evEsc(item.value || item.source || '') + '</em></div>';
  }

  _traceTarget(item) {
    var source = item && item.source ? String(item.source) : '';
    var match = source.match(/W\d{2}/);
    if (!match) return '';
    var wid = match[0];
    if (wid === 'W08' || wid === 'W09' || wid === 'W06' || wid === 'W10' || wid === 'W12' || wid === 'W13' || wid === 'W21') return 'shelf:SHELF_' + wid;
    return 'widget:' + wid;
  }

  _bindEvidenceTraceLinks() {
    var body = this.getBody();
    if (!body || body._evidenceTraceBound) return;
    body._evidenceTraceBound = true;
    var handler = function(e) {
      var card = e.target && e.target.closest ? e.target.closest('[data-evidence-target]') : null;
      if (!card) return;
      if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      var root = typeof window !== 'undefined' ? window : (typeof global !== 'undefined' ? global : {});
      if (root && typeof root._openEvidenceTarget === 'function') {
        root._openEvidenceTarget(card.getAttribute('data-evidence-target'));
      }
    };
    body.addEventListener('click', handler);
    body.addEventListener('keydown', handler);
  }

  _section(title, items, kind) {
    var html = '<div class="evidence-section evidence-section-' + _evEsc(kind || '') + '"><div class="evidence-section-title"><span>' + _evEsc(title) + '</span><span>' + items.length + '</span></div>';
    items.forEach(function(item) { html += this._card(item); }, this);
    return html + '</div>';
  }

  _firstPriority(items) {
    items = Array.isArray(items) ? items : [];
    return items.find(function(item) { return item && item.tone === 'danger'; }) ||
      items.find(function(item) { return item && item.tone === 'warn'; }) ||
      items[0] || null;
  }

  _nextAction(snapshot) {
    var s = snapshot.situation || {};
    var health = s.health || {};
    var trade = s.trade || {};
    var connection = s.connection || {};
    var alerts = Array.isArray(snapshot.alerts) ? snapshot.alerts : [];
    var risks = Array.isArray(snapshot.risks) ? snapshot.risks : [];
    if (connection.status === 'close_snapshot' || connection.label === '收盘快照') return '复核收盘快照';
    if (!health.confirmed) return '等待健康确认';
    if (!trade.allowed) return '停止交易，复核 ' + ((risks[0] && risks[0].id) || 'R1');
    if (alerts.length) return '核对 ' + alerts[0].id + ' 后执行';
    return '核对票据闭环';
  }

  _commandStrip(headline, snapshot) {
    var risk = this._firstPriority((snapshot.risks || []).concat(snapshot.alerts || []));
    var riskTitle = risk ? ((risk.id ? risk.id + ' ' : '') + risk.title) : '暂无关键阻断';
    var riskDetail = risk ? (risk.detail || risk.source || '') : '保持只读核对，等待外部 AI/终端动作';
    var nextAction = this._nextAction(snapshot);
    return '<div class="s0-command-strip">' +
      '<div><span>当前状态</span><b>' + _evEsc(headline) + '</b><em>首屏只显示结论，细节见 E/A/R。</em></div>' +
      '<div><span>关键风险</span><b>' + _evEsc(riskTitle) + '</b><em>' + _evEsc(riskDetail) + '</em></div>' +
      '<div><span>下一步</span><b>' + _evEsc(nextAction) + '</b><em>在 CodexIDE / 终端完成交互，本屏用于验收。</em></div>' +
    '</div>';
  }

  render(data) {
    var body = this.getBody();
    if (!body) return;
    if (typeof EvidenceSummary === 'undefined' || !EvidenceSummary.build) {
      body.innerHTML = '<div class="widget-error">EvidenceSummary 不可用</div>';
      return;
    }
    var snapshot = EvidenceSummary.build(data || {}, this._runtime());
    var s = snapshot.situation || {};
    var command = snapshot.command || {};
    var phase = snapshot.phase || {};
    var gates = Array.isArray(snapshot.gates) ? snapshot.gates : [];
    var queue = Array.isArray(snapshot.display_queue) ? snapshot.display_queue : (Array.isArray(snapshot.action_queue) ? snapshot.action_queue : []);
    var pnl = s.pnl || {};
    var connection = s.connection || {};
    var sentiment = s.sentiment || {};
    var pnlCls = String(pnl.pnl_pct_text || '').charAt(0) === '+' ? 'up' : String(pnl.pnl_pct_text || '').charAt(0) === '-' ? 'down' : '';
    var headline = command.label || s.summary || '状态未确认';
    var evidence = snapshot.evidence || [];
    var risk = this._firstPriority((snapshot.risks || []).concat(snapshot.alerts || []));
    var freshnessSummary = snapshot.freshness_summary || {};
    var freshnessRows = Array.isArray(freshnessSummary.urgent_rows) ? freshnessSummary.urgent_rows : (Array.isArray(snapshot.freshness_rows) ? snapshot.freshness_rows : []);
    var focusWidgets = Array.isArray(snapshot.focus_widgets) ? snapshot.focus_widgets.slice(0, 3) : [];
    var topEvidence = Array.isArray(snapshot.top_evidence) ? snapshot.top_evidence : evidence.slice(0, 3);
    var sourceRefs = topEvidence
      .map(this._evidenceItem, this).join('');
    var tradeSource = snapshot.command_source || 'fallback';
    var primaryActions = Array.isArray(command.primary_actions) ? command.primary_actions : [];

    body.innerHTML = '<div class="evidence-board">' +
      '<div class="evidence-dashboard-hero' + _evCommandClass(command.tone) + '">' +
        '<div class="evidence-command-main">' +
          '<div class="evidence-hero-label"><span class="evidence-ref">S0</span><span>盘中裁决</span><em>' + _evEsc(phase.label || '—') + '</em></div>' +
          '<div class="evidence-command-title">' + _evEsc(headline) + '</div>' +
          '<div class="evidence-command-reason">' + _evEsc(command.reason || '') + '</div>' +
          '<div class="evidence-command-next"><span>下一步</span><b>' + _evEsc(command.next || '保持观察') + '</b></div>' +
          '<div class="evidence-primary-actions">' + primaryActions.map(this._actionButton, this).join('') + '</div>' +
        '</div>' +
        '<div class="evidence-hero-metrics evidence-dashboard-metrics">' +
          '<div><span>情绪</span><strong>' + _evEsc(sentiment.text || '—') + '</strong></div>' +
          '<div><span>盈亏</span><strong class="' + pnlCls + '">' + _evEsc(pnl.pnl_pct_text || '—') + '</strong></div>' +
          '<div><span>仓位</span><strong>' + _evEsc(pnl.position_pct_text || '—') + '</strong></div>' +
          '<div><span>交易入口</span><strong>' + _evEsc(headline) + '</strong><em>' + _evEsc(tradeSource) + '</em></div>' +
        '</div>' +
      '</div>' +
      '<details class="evidence-gate-details"><summary><span>门禁明细</span><b>G1-G5</b></summary>' +
        '<div class="evidence-gate-row">' + gates.map(this._gate, this).join('') + '</div>' +
      '</details>' +
      '<div class="evidence-command-cockpit">' +
        '<section class="evidence-queue-panel"><div class="evidence-section-title"><span>A1 优先处理</span><span>' + queue.length + '</span></div>' + queue.map(this._queueItem, this).join('') + '</section>' +
        '<section class="evidence-freshness-panel"><div class="evidence-section-title"><span>F1 数据可信</span><span>' + freshnessRows.length + '</span></div>' + this._freshnessSummary(freshnessSummary) + freshnessRows.map(this._freshnessRow, this).join('') + '</section>' +
        '<section class="evidence-source-panel"><div class="evidence-section-title"><span>E1 关键证据</span><span>' + topEvidence.length + '</span></div>' + sourceRefs + '</section>' +
        '<section class="evidence-focus-panel"><div class="evidence-section-title"><span>当前聚焦</span><span>' + focusWidgets.length + '</span></div>' +
          '<div class="evidence-focus-list">' + focusWidgets.map(this._focusChip, this).join('') + '</div>' +
          '<div class="evidence-focus-label">当前阶段</div>' +
          '<div class="evidence-phase-title">' + _evEsc(phase.label || '—') + '</div>' +
          '<div class="evidence-phase-detail">' + _evEsc(phase.detail || '') + '</div>' +
          '<div class="evidence-risk-focus"><span>关键风险</span><b>' + _evEsc(risk ? ((risk.id ? risk.id + ' ' : '') + risk.title) : '暂无关键阻断') + '</b><em>' + _evEsc(risk ? (risk.detail || risk.source || '') : '保持只读核对') + '</em></div>' +
        '</section>' +
      '</div>' +
    '</div>';
    this._bindEvidenceTraceLinks();
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W25', EvidenceBoardWidget);
