// widgets/trade-review.js — W23 日级逐笔复盘视图 v2.0 (只读, XSS-safe)
'use strict';

function _esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

class TradeReviewWidget extends YiMuWidget {
  constructor(config) {
    super(config);
    this._reviews = null;
    this._loading = false;
    this._error = null;
    this._reqId = 0;
    var now = new Date();
    this._date = now.getFullYear() + '-' +
      String(now.getMonth() + 1).padStart(2, '0') + '-' +
      String(now.getDate()).padStart(2, '0');
  }

  render(data) {
    var body = this.getBody();
    if (!body) return;

    if (this._error) {
      body.textContent = '';
      var errHtml = '<div style="text-align:center;padding:var(--sp-md);color:var(--danger);margin-bottom:var(--sp-sm)">复盘数据加载失败</div>' +
        '<div style="display:flex;align-items:center;gap:var(--sp-sm);justify-content:center">' +
          '<span style="font-weight:600;font-size:var(--fs-body)">复盘日期</span>' +
          '<input type="date" id="w23_date" value="' + _esc(this._date) + '" style="border:1px solid var(--border);border-radius:var(--radius-sm);padding:2px 6px;font-size:var(--fs-body);background:var(--bg-card);color:var(--text-primary)">' +
          '<button id="w23_refresh" style="background:var(--info);color:#fff;border:none;padding:2px 10px;border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body)">重试</button>' +
        '</div>';
      body.innerHTML = errHtml;
      this.updateTimestamp();
      var self = this;
      var dateEl = body.querySelector('#w23_date');
      var refreshEl = body.querySelector('#w23_refresh');
      if (dateEl && refreshEl) {
        refreshEl.onclick = function() {
          self._reviews = null; self._error = null;
          self._fetch(dateEl.value, body);
        };
      }
      return;
    }

    if (!this._reviews && !this._loading) {
      this._fetch(this._date, body);
      return;
    }

    if (this._loading) {
      body.innerHTML = '<div style="text-align:center;padding:var(--sp-md);color:var(--text-disabled)">加载复盘数据...</div>';
      this.updateTimestamp();
      return;
    }

    this._renderTable(body, this._reviews, this._date);
  }

  _fetch(date, body) {
    var self = this;
    this._date = date;
    this._loading = true;
    this._error = null;
    var reqId = ++this._reqId;
    body.innerHTML = '<div style="text-align:center;padding:var(--sp-md);color:var(--text-disabled)">加载复盘数据...</div>';

    fetch('/api/trades/review?date=' + date)
      .then(function(r) {
        if (reqId !== self._reqId) return null;
        if (!r.ok) { self._error = '复盘数据加载失败'; return null; }
        return r.json();
      })
      .then(function(data) {
        if (reqId !== self._reqId) return;
        self._loading = false;
        if (data === null) { self._reviews = null; self._renderBody(); return; }
        self._reviews = Array.isArray(data) ? data : [];
        self._renderBody();
      })
      .catch(function() {
        if (reqId !== self._reqId) return;
        self._loading = false;
        self._error = '复盘数据加载失败';
        self._renderBody();
      });
  }

  _td(innerHTML) {
    return '<td style="padding:3px 6px;white-space:nowrap">' + innerHTML + '</td>';
  }

  _renderTable(body, reviews, date) {
    var html = '';

    html += '<div style="display:flex;align-items:center;gap:var(--sp-sm);margin-bottom:var(--sp-sm)">' +
      '<span style="font-weight:600;font-size:var(--fs-body)">复盘日期</span>' +
      '<input type="date" id="w23_date" value="' + _esc(date) + '" style="border:1px solid var(--border);border-radius:var(--radius-sm);padding:2px 6px;font-size:var(--fs-body);background:var(--bg-card);color:var(--text-primary)">' +
      '<button id="w23_refresh" style="background:var(--info);color:#fff;border:none;padding:2px 10px;border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body)">查看</button>' +
      '</div>';

    if (!reviews.length) {
      html += '<div style="text-align:center;padding:var(--sp-lg);color:var(--text-disabled)">' +
        _esc(date) + ' 暂无成交记录</div>';
    } else {
      html += '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px">' +
        '<thead><tr style="border-bottom:2px solid var(--border);text-align:left">' +
          '<th style="padding:3px 6px;white-space:nowrap">时间</th>' +
          '<th style="padding:3px 6px;white-space:nowrap">动作</th>' +
          '<th style="padding:3px 6px;white-space:nowrap">标的</th>' +
          '<th style="padding:3px 6px;white-space:nowrap">代码</th>' +
          '<th style="padding:3px 6px;white-space:nowrap">价格</th>' +
          '<th style="padding:3px 6px;white-space:nowrap">数量</th>' +
          '<th style="padding:3px 6px;white-space:nowrap">窗口</th>' +
          '<th style="padding:3px 6px;white-space:nowrap">原因</th>' +
          '<th style="padding:3px 6px;white-space:nowrap">收盘结果</th>' +
          '<th style="padding:3px 6px;white-space:nowrap">状态</th>' +
          '<th style="padding:3px 6px;white-space:nowrap">归因备注</th>' +
        '</tr></thead><tbody>';

      reviews.forEach(function(r, ri) {
        var rowId = 'w23r' + ri;
        var hasTrusted = !!(r.rule_state && r.market_snapshot);
        var hasRule = !!(r.rule_state);

        html += '<tr style="border-bottom:1px solid var(--border-light)" id="' + rowId + '">' +
          '<td style="padding:3px 6px;white-space:nowrap;font-family:var(--font-mono)">' + _esc(r.trade_time) + '</td>' +
          '<td style="padding:3px 6px;white-space:nowrap;font-weight:600;color:' + ((r.action||'').indexOf('买')>=0?'var(--up)':(r.action||'').indexOf('卖')>=0?'var(--down)':'var(--text-primary)') + '">' + _esc(r.action) + '</td>' +
          '<td style="padding:3px 6px;white-space:nowrap;font-weight:600">' + _esc(r.name) + '</td>' +
          '<td style="padding:3px 6px;font-family:var(--font-mono)">' + _esc(r.code) + '</td>' +
          '<td style="padding:3px 6px;font-family:var(--font-mono);text-align:right">' + (r.price != null ? _esc(String(r.price)) : '—') + '</td>' +
          '<td style="padding:3px 6px;font-family:var(--font-mono);text-align:right">' + _esc(String(r.qty || '')) + '</td>' +
          '<td style="padding:3px 6px;white-space:nowrap">' + _esc(r.window) + '</td>' +
          '<td style="padding:3px 6px;font-size:11px;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + _esc(r.reason) + '">' + _esc(r.reason) + '</td>' +
          '<td style="padding:3px 6px;font-size:11px;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + _esc(r.outcome) + '">' + _esc(r.outcome) + '</td>';

        // Status column
        if (hasTrusted) {
          var rs = r.rule_state;
          var tradable = rs.tradable;
          var winKey = (r.window || '').toLowerCase();
          var w = (rs.windows || {})[winKey] || {};
          var buyAllowed = w.buy_allowed;
          var conclusion;
          if (tradable && buyAllowed !== false) conclusion = '允许交易';
          else if (!tradable) conclusion = '禁止交易';
          else conclusion = '窗口关闭';
          var blocks = (rs.blocks || []).map(function(b){return b.code;}).join(',');
          var warns = (rs.warnings || []).join(',');
          var evidence = [];
          if (r.market_snapshot.iwencai && r.market_snapshot.iwencai['情绪值'] != null)
            evidence.push('情绪' + r.market_snapshot.iwencai['情绪值']);
          if (r.market_snapshot.live_index && r.market_snapshot.live_index['上证指数涨幅'])
            evidence.push('上证' + r.market_snapshot.live_index['上证指数涨幅']);
          var evStr = evidence.length ? ' | ' + evidence.join(' ') : '';
          var blocksStr = blocks ? ' | 阻断:' + blocks : '';
          var ws = warns ? ' | 预警:' + warns : '';
          var concColor = tradable && buyAllowed !== false ? 'var(--down)' : 'var(--danger)';
          html += '<td style="padding:3px 6px;white-space:nowrap;font-size:11px">' +
            '<span style="color:' + concColor + ';font-weight:600">已验证 · ' + conclusion + '</span>' +
            '<span style="font-size:10px;color:var(--text-secondary)">' + _esc(evStr + blocksStr + ws) + '</span></td>';
        } else if (hasRule) {
          html += '<td style="padding:3px 6px;white-space:nowrap;font-size:11px">' +
            '<span style="color:var(--warn)">人工记录 / 未验证</span></td>';
        } else {
          html += '<td style="padding:3px 6px;white-space:nowrap;font-size:11px">' +
            '<span style="color:var(--warn)">人工记录 / 未验证</span></td>';
        }

        html += '<td style="padding:3px 6px;font-size:11px;color:var(--text-secondary);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + _esc(r.review_note) + '">' + _esc(r.review_note) + '</td>' +
          '</tr>';
      });

      // Summary
      var buyCount = reviews.filter(function(r){return(r.action||'').indexOf('买')>=0;}).length;
      var sellCount = reviews.filter(function(r){return(r.action||'').indexOf('卖')>=0;}).length;
      var unverifiedCount = reviews.filter(function(r){return !(r.rule_state && r.market_snapshot);}).length;
      html += '<tr style="background:var(--bg-hover);font-size:11px;color:var(--text-secondary)">' +
        '<td colspan="11" style="padding:4px 6px">' +
          '共 ' + reviews.length + ' 笔 | 买入 ' + buyCount + ' | 卖出 ' + sellCount + ' | 未验证 ' + unverifiedCount +
        '</td></tr>';

      html += '</tbody></table></div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();

    var self = this;
    var dateEl = body.querySelector('#w23_date');
    var refreshEl = body.querySelector('#w23_refresh');
    if (dateEl && refreshEl) {
      refreshEl.onclick = function() {
        self._reviews = null;
        self._error = null;
        self._fetch(dateEl.value, body);
      };
    }
  }
}

WidgetRegistry.register('W23', TradeReviewWidget);
