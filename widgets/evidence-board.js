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
    return '<div class="evidence-card' + _evToneClass(item.tone) + '" data-evidence-id="' + _evEsc(item.id) + '">' +
      '<div class="evidence-card-title"><span class="evidence-ref">' + _evEsc(item.id) + '</span><span>' + _evEsc(item.title) + '</span><span class="evidence-source">' + _evEsc(item.source || '') + '</span></div>' +
      '<div class="evidence-card-value">' + _evEsc(item.value || '') + '</div>' +
      '<div class="evidence-card-detail">' + _evEsc(item.detail || '') + '</div>' +
    '</div>';
  }

  _section(title, items, kind) {
    var html = '<div class="evidence-section evidence-section-' + _evEsc(kind || '') + '"><div class="evidence-section-title"><span>' + _evEsc(title) + '</span><span>' + items.length + '</span></div>';
    items.forEach(function(item) { html += this._card(item); }, this);
    return html + '</div>';
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
    var pnl = s.pnl || {};
    var health = s.health || {};
    var trade = s.trade || {};
    var connection = s.connection || {};
    var sentiment = s.sentiment || {};
    var pnlCls = String(pnl.pnl_pct_text || '').charAt(0) === '+' ? 'up' : String(pnl.pnl_pct_text || '').charAt(0) === '-' ? 'down' : '';
    var healthTone = trade.allowed ? 'ok' : 'blocked';
    var headline = s.summary || (((health.confirmed && trade.allowed) ? '可交易' : '状态未确认') + ' · ' + (connection.label || connection.status || '—'));

    body.innerHTML = '<div class="evidence-board">' +
      '<div class="evidence-hero evidence-hero-' + healthTone + '">' +
        '<div class="evidence-hero-main">' +
          '<div class="evidence-hero-label"><span class="evidence-ref">S0</span>作战态势</div>' +
          '<div class="evidence-hero-title">' + _evEsc(headline) + '</div>' +
        '</div>' +
        '<div class="evidence-hero-metrics">' +
          '<div><span>情绪</span><strong>' + _evEsc(sentiment.text || '—') + '</strong></div>' +
          '<div><span>盈亏</span><strong class="' + pnlCls + '">' + _evEsc(pnl.pnl_pct_text || '—') + '</strong></div>' +
          '<div><span>仓位</span><strong>' + _evEsc(pnl.position_pct_text || '—') + '</strong></div>' +
          '<div><span>连接</span><strong>' + _evEsc(connection.label || connection.status || '—') + '</strong></div>' +
        '</div>' +
      '</div>' +
      '<div class="evidence-section-grid">' +
        this._section('关键证据', snapshot.evidence || [], 'evidence') +
        this._section('注意事项', snapshot.alerts || [], 'alerts') +
        this._section('规则/风控', snapshot.risks || [], 'risks') +
      '</div>' +
    '</div>';
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W25', EvidenceBoardWidget);
