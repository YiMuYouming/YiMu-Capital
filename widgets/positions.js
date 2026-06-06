// widgets/positions.js — W15 持仓+手工补录+清仓 v4.0 (SSOT-only rendering)
'use strict';

function _esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function _fmtPrice(v) {
  if (v == null || isNaN(v)) return '—';
  return Number(v).toFixed(2);
}

function _fmtAmount(v) {
  if (v == null || isNaN(v)) return '—';
  return Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function _fmtPnL(v) {
  if (v == null || isNaN(v)) return '—';
  var n = Number(v);
  return (n >= 0 ? '+' : '') + n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function _fmtPct(v) {
  if (v == null || isNaN(v)) return '';
  var n = Number(v);
  return (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
}

function _w15WriteGate() {
  var w = (typeof window !== 'undefined') ? window : null;
  var loc = (typeof location !== 'undefined') ? location : null;
  var readonly = false;
  if (w && typeof w._detectRuntimeMode === 'function') {
    try { readonly = !!(w._detectRuntimeMode() || {}).readonly; } catch (e) { readonly = false; }
  } else if (loc) {
    readonly = loc.protocol === 'file:' || /^180(8[0-9]|9[0-9])$/.test(loc.port || '');
  }
  if (readonly) return { canWrite: false, reason: '本地预览只读，不录真实交易' };
  if (w) {
    if (w._healthConfirmed !== true) return { canWrite: false, reason: '健康状态未确认' };
    if (w._healthCritical === true) return { canWrite: false, reason: '健康门禁阻断' };
    if (w._tradeEntryAllowed === false) return { canWrite: false, reason: '交易录入已关闭' };
  }
  return { canWrite: true, reason: '' };
}

class PositionsWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var liveQ = (data && data.live_quotes) || {};
    var pnlLive = (data && data.pnl_live) || {};

    // === 可信状态检查 ===
    var isBlocked = pnlLive.anchor_blocked === true;
    var isValuationIncomplete = pnlLive.valuation_complete === false && !isBlocked;
    var quoteStatus = pnlLive.quote_status || '';
    var isPostClose = quoteStatus === 'close_snapshot';
    var isLive = quoteStatus === 'live';

    // === SSOT positions ===
    var ssotPositions = Array.isArray(pnlLive.positions) ? pnlLive.positions : [];
    var active = [];
    ssotPositions.forEach(function(p) {
      var st = (p['状态'] || '');
      if (st.indexOf('清') >= 0 || st.indexOf('删') >= 0) return;
      active.push(p);
    });

    // === Summary cards (SSOT) ===
    var taNull = pnlLive.total_asset == null;
    var mvNull = pnlLive.mv == null;
    var cashNull = pnlLive.cash == null;
    var ta = taNull ? 0 : parseFloat(pnlLive.total_asset);
    var mv = mvNull ? 0 : parseFloat(pnlLive.mv);
    var cash = cashNull ? 0 : parseFloat(pnlLive.cash);
    var posPctNull = pnlLive.pos_pct == null;
    var posPct = posPctNull ? 0 : parseFloat(pnlLive.pos_pct);

    var tpNull = pnlLive.pnl_amount == null;
    var ppNull = pnlLive.pnl_pct == null;
    var tp = tpNull ? 0 : parseFloat(pnlLive.pnl_amount);
    var pp = ppNull ? 0 : parseFloat(pnlLive.pnl_pct);
    var tc = tp > 0 ? 'up' : tp < 0 ? 'down' : '';

    // 卡片渲染
    var naData = '<span style="color:var(--text-disabled)">— / 数据不可用</span>';
    var naQuote = '<span style="color:var(--text-disabled)">— / 行情不可用</span>';
    var naPostClose = '<span style="color:var(--text-disabled)">— / 收盘价 · 非实时</span>';
    var naWaitToday = '<span style="color:var(--text-disabled)">— / 等待今日行情</span>';
    var naDash = '<span style="color:var(--text-disabled)">—</span>';
    var snapshotTag = ' <span style="font-size:var(--fs-label);color:var(--text-disabled)">非实时</span>';
    var closeTag = ' <span style="font-size:var(--fs-label);color:var(--text-disabled)">收盘</span>';
    // 行情缺失时仍保留账户快照；只有今日盈亏等待实时行情确认。
    var isUnavailable = isValuationIncomplete && !isPostClose;
    var taDisplay = isUnavailable ? (taNull ? naQuote : _fmtAmount(ta) + snapshotTag) : (isPostClose ? (_fmtAmount(ta) + closeTag) : (taNull ? naData : _fmtAmount(ta)));
    var mvDisplay = isUnavailable ? (mvNull ? naQuote : _fmtAmount(mv) + snapshotTag) : (isPostClose ? (_fmtAmount(mv) + closeTag) : (mvNull ? naData : _fmtAmount(mv)));
    var cashDisplay = cashNull ? naData : _fmtAmount(cash);
    var posPctDisplay = posPctNull ? naDash : posPct + '%';
    var posPctColor = posPctNull ? '' : (posPct > 80 ? 'var(--danger)' : posPct > 50 ? 'var(--warn)' : 'var(--info)');
    var pnlColorStyle = tc ? ' style="color:var(--' + tc + ')"' : '';
    var posColorStyle = posPctColor ? ' style="color:' + posPctColor + '"' : '';

    var pnlCardHtml;
    if (isUnavailable) {
      pnlCardHtml = naWaitToday;
    } else if (isPostClose) {
      pnlCardHtml = _fmtPnL(tp) + ' <span style="font-size:var(--fs-body);font-weight:400">(' + (pp >= 0 ? '+' : '') + pp.toFixed(2) + '%)</span>' + closeTag;
    } else if (tpNull && ppNull) {
      pnlCardHtml = '<span style="color:var(--text-disabled)">— / 基准不可用</span>';
    } else {
      pnlCardHtml = _fmtPnL(tp) + ' <span style="font-size:var(--fs-body);font-weight:400">(' + (pp >= 0 ? '+' : '') + pp.toFixed(2) + '%)</span>';
    }

    var html = '';

    // Trust-status banner
    if (isBlocked) {
      html += '<div style="margin-bottom:var(--sp-md);padding:var(--sp-sm);background:var(--danger-bg, #fef2f2);border:1px solid var(--danger);border-radius:var(--radius-md);font-size:var(--fs-body);color:var(--danger);font-weight:600">' +
        '锚点被阻断 — 数据不可信' +
        (pnlLive.block_reason ? ' <span style="font-weight:400;opacity:0.8">(' + _esc(pnlLive.block_reason) + ')</span>' : '') +
        '</div>';
    } else if (isValuationIncomplete) {
      var bannerText = isPostClose ? '收盘行情 — 非实时估值' : '行情缺失 — 估值不可信（行情不可用，显示非实时快照）';
      var bannerBg = isPostClose ? 'var(--bg-card)' : 'var(--warn-bg, #fffbeb)';
      var bannerBorder = isPostClose ? 'var(--border)' : 'var(--warn)';
      var bannerColor = isPostClose ? 'var(--text-secondary)' : 'var(--warn)';
      html += '<div style="margin-bottom:var(--sp-md);padding:var(--sp-sm);background:' + bannerBg + ';border:1px solid ' + bannerBorder + ';border-radius:var(--radius-md);font-size:var(--fs-body);color:' + bannerColor + ';font-weight:600">' +
        bannerText + '</div>';
    } else if (isPostClose && !isValuationIncomplete) {
      html += '<div style="margin-bottom:var(--sp-md);padding:var(--sp-sm);background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-md);font-size:var(--fs-body);color:var(--text-secondary);font-weight:600">' +
        '收盘快照 — 非实时行情</div>';
    }

    // Prefill banner
    var _pf = DataStore._prefill;
    if (_pf && Date.now() - (_pf.ts || 0) < 300000) {
      html += '<div class="prefill-banner">' +
        '<span style="font-weight:700;color:var(--info)">预填: </span>' +
        '<span>' + _esc(_pf.name) + ' ' + _esc(_pf.code) + ' ' + _esc(_pf.window) + '</span>' +
        '<span style="margin-left:8px;font-size:10px;color:var(--text-secondary)">' + _esc(_pf.evidence || '') + '</span>' +
        '<button onclick="DataStore._prefill=null;DataStore.notifyAll()" style="float:right;background:none;border:none;cursor:pointer;font-size:14px;color:var(--text-disabled)" title="关闭预填">x</button>' +
        '</div>';
    }

    html += '<div id="w15_sync_status" style="display:none;font-size:var(--fs-small);margin-bottom:var(--sp-xs);padding:2px 6px;border-radius:3px;background:var(--bg-base)"></div>' +
      '<div class="w15-kpi-grid">' +
      '<div class="w15-kpi-card"><div class="kpi-label">总资产</div><div class="w15-kpi-value">' + taDisplay + '</div></div>' +
      '<div class="w15-kpi-card"><div class="kpi-label">持仓市值</div><div class="w15-kpi-value">' + mvDisplay + '</div></div>' +
      '<div class="w15-kpi-card"><div class="kpi-label">今日盈亏</div><div class="w15-kpi-value"' + pnlColorStyle + '>' + pnlCardHtml + '</div></div>' +
      '<div class="w15-kpi-card"><div class="kpi-label">可用资金</div><div class="w15-kpi-value">' + cashDisplay + '</div></div>' +
      '<div class="w15-kpi-card"><div class="kpi-label">仓位</div><div class="w15-kpi-value"' + posColorStyle + '>' + posPctDisplay + '</div></div>' +
      '</div>';

    // ===== 持仓 (SSOT) =====
    if (isBlocked) {
      html += '<div class="ui-empty"><div class="ui-empty-title">数据不可用</div><div class="ui-empty-detail">锚点被阻断，持仓快照进入只读核对态</div></div>';
    } else {
    html += '<div class="w15-section-title"><span class="evidence-inline-ref">E1</span><span>持仓</span><span>（由成交流水驱动）</span></div>';
    if (active.length) {
      html += '<table class="data-table w15-table"><thead><tr><th>标的</th><th>市值</th><th>现价</th><th>成本</th><th>今日盈亏</th><th>累计盈亏</th><th>止损</th></tr></thead><tbody>';
      active.forEach(function(p) {
        var tPnL = p['today_pnl'], tPct = p['today_pnl_pct'];
        var totPnL = p['total_pnl'], totPct = p['total_pnl_pct'];
        var tdc = (tPnL || 0) > 0 ? 'up' : (tPnL || 0) < 0 ? 'down' : '';
        var todc = (totPnL || 0) > 0 ? 'up' : (totPnL || 0) < 0 ? 'down' : '';

        // 估值不可信时，价格相关字段标记不可用
        var mvCell, priceCell, todayCell, totalCell;
        if (isUnavailable) {
          mvCell = p['市值'] == null ? naQuote : _fmtAmount(p['市值']) + snapshotTag;
          priceCell = p['现价'] == null ? naQuote : _fmtPrice(p['现价']) + snapshotTag;
          todayCell = naWaitToday;
          totalCell = totPnL == null ? naQuote : _fmtPnL(totPnL) + ' <span style="font-size:var(--fs-label)">' + _fmtPct(totPct) + '</span>' + snapshotTag;
        } else if (isPostClose) {
          mvCell = _fmtAmount(p['市值']) + closeTag;
          priceCell = _fmtPrice(p['现价']) + closeTag;
          if (tPnL != null) {
            todayCell = _fmtPnL(tPnL) + ' <span style="font-size:var(--fs-label)">' + _fmtPct(tPct) + '</span>';
          } else {
            todayCell = '<span style="color:var(--text-disabled);font-weight:400">— / 基准不可用</span>';
          }
          totalCell = _fmtPnL(totPnL) + ' <span style="font-size:var(--fs-label)">' + _fmtPct(totPct) + '</span>';
        } else {
          mvCell = _fmtAmount(p['市值']);
          priceCell = _fmtPrice(p['现价']);
          if (tPnL != null) {
            todayCell = _fmtPnL(tPnL) + ' <span style="font-size:var(--fs-label)">' + _fmtPct(tPct) + '</span>';
          } else {
            todayCell = '<span style="color:var(--text-disabled);font-weight:400">— / 基准不可用</span>';
          }
          totalCell = _fmtPnL(totPnL) + ' <span style="font-size:var(--fs-label)">' + _fmtPct(totPct) + '</span>';
        }

        // 止损: percentage → stop-loss price
        var slRaw = p['止损'], slDisplay = '—';
        if (slRaw != null && slRaw !== '-' && slRaw !== '—') {
          var slPct = parseFloat(String(slRaw).replace('%', ''));
          var cost = parseFloat(p['成本'] || p['成本价']) || 0;
          if (!isNaN(slPct) && slPct !== 0 && cost > 0) {
            slDisplay = (cost * (1 + slPct / 100)).toFixed(2);
          }
        }

        html += '<tr>' +
          '<td style="font-size:var(--fs-body);font-weight:600">' + _esc(p['标的']) + ' <span style="font-size:var(--fs-label);color:var(--text-disabled)">' + _esc(p['代码']) + '</span></td>' +
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">' + mvCell + '</td>' +
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">' + priceCell + '</td>' +
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono);color:var(--text-secondary)">' + _fmtPrice(p['成本价'] != null ? p['成本价'] : p['成本']) + '</td>' +
          '<td class="' + (isValuationIncomplete ? '' : tdc) + '" style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">' + todayCell + '</td>' +
          '<td class="' + (isValuationIncomplete ? '' : todc) + '" style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">' + totalCell + '</td>' +
          '<td style="font-size:var(--fs-body)">' + (isValuationIncomplete ? naDash : _esc(slDisplay)) + '</td>' +
          '</tr>';
      });
      html += '</tbody></table>';
    } else {
      html += '<div class="ui-empty ui-empty-inline"><div class="ui-empty-title">空仓</div></div>';
    }

    // ===== 今日记录 (SSOT trade_records) =====
    var writeGate = _w15WriteGate();
    html += '<div class="w15-record-head">' +
      '<span>今日记录</span>' +
      (writeGate.canWrite ?
        '<details class="w15-emergency-entry"><summary>应急补录</summary><button id="w15_add">打开补录</button></details>' :
        '<span class="w15-readonly-lock" title="' + _esc(writeGate.reason) + '">只读</span>') +
      '</div>';

    var trades = Array.isArray(pnlLive.trades) ? pnlLive.trades : [];
    if (trades.length) {
      html += '<table class="data-table w15-table"><thead><tr><th>时间</th><th>动作</th><th>标的</th><th>代码</th><th>价格</th><th>数量</th><th>窗口</th><th>原因</th></tr></thead><tbody>';
      trades.forEach(function(t) {
        var act = t.action || '—';
        var isBuy = act.indexOf('买入') >= 0 || act.indexOf('追') >= 0;
        html += '<tr>' +
          '<td style="font-size:var(--fs-body)">' + _esc(t.trade_time) + '</td>' +
          '<td><span class="tag" style="font-size:var(--fs-body);background:var(--' + (isBuy ? 'up-bg' : 'down-bg') + ');color:var(--' + (isBuy ? 'up' : 'down') + ')">' + _esc(act) + '</span></td>' +
          '<td style="font-size:var(--fs-body);font-weight:600">' + _esc(t.name) + '</td>' +
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono);color:var(--text-secondary)">' + _esc(t.code) + '</td>' +
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">' + _fmtPrice(t.price) + '</td>' +
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">' + _esc(String(t.qty || '—')) + '</td>' +
          '<td style="font-size:var(--fs-body)">' + _esc(t.window || '—') + '</td>' +
          '<td style="font-size:var(--fs-body);color:var(--text-secondary);max-width:100px;white-space:normal">' + _esc(t.reason || '') + '</td>' +
          '</tr>';
      });
      html += '</tbody></table>';
    } else {
      html += '<div class="ui-empty ui-empty-inline"><div class="ui-empty-title">今日无操作</div></div>';
    }

    // ===== 清仓跟踪 (SSOT closed_positions only, 7个交易日) =====
    var closed = Array.isArray(pnlLive.closed_positions) ? pnlLive.closed_positions : [];
    if (closed.length) {
      var tracked = closed;
      if (tracked.length) {
        html += '<div style="margin-top:var(--sp-md)"><span style="font-size:var(--fs-body);font-weight:600">清仓跟踪（7个交易日）</span></div>';
        html += '<table class="data-table w15-table"><thead><tr><th>标的</th><th>卖出价</th><th>已实现盈亏</th><th>现价</th><th>卖出后涨跌</th><th>原因</th></tr></thead><tbody>';
        tracked.forEach(function(c) {
          var sp = parseFloat(c.sell_price) || 0;
          var lq = liveQ[(c.code || '')] || {};
          var cur = parseFloat(lq['最新价']) || 0;
          var liveOk = cur > 0;
          var realized = c.realized_today_pnl != null ? parseFloat(c.realized_today_pnl) : null;
          var realizedDisplay = realized != null ? _fmtPnL(realized) : '<span style="color:var(--text-disabled);font-weight:400">— / 基准不可用</span>';
          var ap = liveOk && sp > 0 ? ((cur - sp) / sp * 100) : null;
          var acls = ap != null ? (ap > 0 ? 'up' : ap < 0 ? 'down' : '') : '';

          html += '<tr>' +
            '<td style="font-size:var(--fs-body);font-weight:600">' + _esc(c.name) + '</td>' +
            '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">' + _fmtPrice(sp) + '</td>' +
            '<td class="' + (realized != null ? (realized >= 0 ? 'up' : 'down') : '') + '" style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">' + realizedDisplay + '</td>' +
            '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">' + (liveOk ? _fmtPrice(cur) : '—') + '</td>' +
            '<td class="' + acls + '" style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">' + (ap != null ? (ap >= 0 ? '+' : '') + ap.toFixed(2) + '%' : '—') + '</td>' +
            '<td style="font-size:var(--fs-body);color:var(--text-secondary);max-width:100px;white-space:normal">' + _esc(c.reason || '') + '</td>' +
            '</tr>';
        });
        html += '</tbody></table>';
      }
    }
    } // end if (!isBlocked) — 持仓+记录+清仓区域

    body.innerHTML = html;
    this._bindEvents(active);
    this.updateTimestamp();
  }

  _bindEvents(active) {
    var self = this;
    if (!_w15WriteGate().canWrite) return;
    var body = this.getBody();
    var addBtn = body.querySelector('#w15_add');
    if (addBtn) addBtn.onclick = function() { self._showForm(active); };
  }

  _showForm(active) {
    var gate = _w15WriteGate();
    if (!gate.canWrite) {
      if (typeof showToast === 'function') showToast(gate.reason);
      return;
    }
    var self = this;
    var pf = DataStore._prefill || {};

    var o = document.createElement('div');
    o.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);z-index:var(--z-toast);display:flex;align-items:center;justify-content:center';

    var sellOpts = active.map(function(p) {
      return '<option value="' + _esc(p['标的']) + '" data-code="' + _esc(p['代码'] || '') + '" data-price="' + (p['现价'] || '') + '" data-qty="' + (p['数量'] || 0) + '">' + _esc(p['标的']) + ' (' + _esc(p['代码'] || '') + ')</option>';
    }).join('');

    o.innerHTML = '<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:var(--sp-lg);width:90%;max-width:400px">' +
      '<div style="font-size:var(--fs-subtitle);font-weight:700;margin-bottom:var(--sp-xs)">手工补录成交</div>' +
      '<div style="font-size:var(--fs-small);color:var(--warn);margin-bottom:var(--sp-md)">优先用交易票据确认成交；这里只用于补录真实已成交流水。</div>' +
      '<div style="display:flex;gap:var(--sp-sm);margin-bottom:var(--sp-md)">' +
        '<button id="f_buy" style="flex:1;padding:var(--sp-sm);border:none;border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body);font-weight:600;background:var(--up-bg);color:var(--up)">买入</button>' +
        '<button id="f_sell" style="flex:1;padding:var(--sp-sm);border:none;border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body);font-weight:600;background:var(--down-bg);color:var(--down);opacity:0.4">卖出</button>' +
      '</div>' +
      '<div id="f_sell_select" style="display:none;margin-bottom:var(--sp-sm)"><div class="input-group"><label>选择持仓</label><select id="f_sel_stock" style="width:100%"><option value="">— 选择 —</option>' + sellOpts + '</select></div></div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-sm)">' +
        '<div class="input-group"><label>股票代码</label><input id="f_code" value="' + _esc(pf['代码'] || '') + '" style="width:100%"></div>' +
        '<div class="input-group"><label>时间</label><input id="f_time" value="' + _esc(pf['时间'] || _nowTime()) + '" style="width:100%"></div>' +
        '<div class="input-group" style="grid-column:1/-1"><label>标的名称</label><input id="f_stock" value="' + _esc(pf['标的'] || '') + '" style="width:100%"></div>' +
        '<div class="input-group"><label>价格</label><input id="f_price" type="number" step="0.01" value="' + (pf['价格'] || '') + '" style="width:100%"></div>' +
        '<div class="input-group" id="f_qty_row"><label>数量(股)</label><input id="f_qty" type="number" value="' + (pf['数量'] || '100') + '" style="width:100%"></div>' +
        '<div class="input-group" id="f_win_row"><label>窗口</label><select id="f_win" style="width:100%"><option value="W1">W1</option><option value="W2">W2</option></select></div>' +
        '<div class="input-group" style="grid-column:1/-1"><label>交易理由</label><input id="f_reason" value="' + _esc(pf['原因'] || '') + '" style="width:100%"></div>' +
      '</div>' +
      '<div style="display:flex;gap:var(--sp-sm);margin-top:var(--sp-md)">' +
        '<button id="f_save" style="flex:1;background:var(--info);color:var(--text-inverse);border:none;padding:var(--sp-sm);border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body)">确认</button>' +
        '<button id="f_cancel" style="flex:1;background:var(--bg-base);color:var(--text-primary);border:1px solid var(--border);padding:var(--sp-sm);border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body)">取消</button>' +
      '</div>' +
      '<div id="f_error" style="display:none;color:var(--danger);font-size:var(--fs-small);margin-top:var(--sp-xs)"></div></div>';
    document.body.appendChild(o);

    var buyBtn2 = o.querySelector('#f_buy'), sellBtn2 = o.querySelector('#f_sell');
    var sellSelect2 = o.querySelector('#f_sell_select'), qtyRow2 = o.querySelector('#f_qty_row'), winRow2 = o.querySelector('#f_win_row');
    var qtyLabel2 = qtyRow2.querySelector('label');

    if (pf && pf.code) {
      var fCode = o.querySelector('#f_code');
      var fStock = o.querySelector('#f_stock');
      var fWin = o.querySelector('#f_win');
      var fReason = o.querySelector('#f_reason');
      if (fCode) fCode.value = pf.code || '';
      if (fStock) fStock.value = pf.name || '';
      if (pf.window && fWin && fWin.options) {
        for (var wi = 0; wi < fWin.options.length; wi++) {
          if (fWin.options[wi].value === pf.window) { fWin.options[wi].selected = true; break; }
        }
      }
      if (fReason) fReason.value = pf.evidence || '';
    }

    function toggle(buy) {
      buyBtn2.style.opacity = buy ? '1' : '0.4';
      sellBtn2.style.opacity = buy ? '0.4' : '1';
      sellSelect2.style.display = buy ? 'none' : '';
      qtyLabel2.textContent = buy ? '数量(股)' : '卖出数量';
      winRow2.style.display = buy ? '' : 'none';
    }
    buyBtn2.onclick = function() { toggle(true); };
    sellBtn2.onclick = function() { toggle(false); };

    o.querySelector('#f_sel_stock').onchange = function() {
      var opt = this.selectedOptions[0];
      if (!opt || !opt.value) return;
      o.querySelector('#f_stock').value = opt.value;
      o.querySelector('#f_code').value = opt.dataset.code || '';
      o.querySelector('#f_price').value = opt.dataset.price || '';
      o.querySelector('#f_qty').value = opt.dataset.qty || '';
    };

    o.querySelector('#f_cancel').onclick = function() { self._pendingEvtId = null; o.remove(); };
    o.querySelector('#f_save').onclick = function() {
      // pending 防重复点击
      if (self._pending) return;
      var saveBtn = o.querySelector('#f_save');
      var g = function(id) { return (o.querySelector('#' + id) || {}).value || ''; };
      var buy = buyBtn2.style.opacity !== '0.4';
      var stock = g('f_stock'), code = g('f_code'), reason = g('f_reason');
      var act = buy ? (g('f_win') === 'W1' ? 'W1追涨' : 'W2买入') : '卖出';

      // 前端校验：在发请求前阻断非法输入
      var validation = _validateTradeEntry({
        time: g('f_time'), action: act, stock: stock, code: code,
        price: g('f_price'), qty: g('f_qty'), window: g('f_win'), reason: reason
      }, buy);
      var errBox = o.querySelector('#f_error');
      if (!validation.ok) {
        if (errBox) {
          errBox.textContent = validation.error;
          errBox.style.display = '';
        }
        return;
      }
      if (errBox) {
        errBox.textContent = '';
        errBox.style.display = 'none';
      }

      // event_id：首次生成，重试复用
      if (!self._pendingEvtId) {
        self._pendingEvtId = 'w15-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
      }
      var entry = validation.entry;
      entry['event_id'] = self._pendingEvtId;
      entry['input_source'] = 'manual_backfill';
      entry['confirmed_by'] = 'yimu';
      entry['audit_note'] = reason || '手工补录成交';

      // 锁定按钮
      self._pending = true;
      saveBtn.disabled = true;
      saveBtn.textContent = '提交中...';
      saveBtn.style.opacity = '0.6';

      _bridgeSync(entry, function onSuccess() {
        self._pending = false;
        self._pendingEvtId = null;
        o.remove();
      }, function onError(errMsg) {
        self._pending = false;
        saveBtn.disabled = false;
        saveBtn.textContent = '确认';
        saveBtn.style.opacity = '';
        // 把后端错误写到 f_error 并显示
        var errBox = o.querySelector('#f_error');
        if (errBox && errMsg) {
          errBox.textContent = errMsg;
          errBox.style.display = '';
        }
        // 保留表单 + event_id 供重试
      });
    };
    o.addEventListener('click', function(e) { if (e.target === o) { self._pendingEvtId = null; o.remove(); } });
  }
}

function _validateTradeEntry(raw, buy) {
  var time = String(raw.time || '').trim();
  var stock = String(raw.stock || '').trim();
  var code = String(raw.code || '').trim();
  var priceRaw = String(raw.price || '').trim();
  var qtyRaw = String(raw.qty || '').trim();
  var action = String(raw.action || '').trim();
  var windowName = buy ? String(raw.window || '').trim() : '—';
  var reason = String(raw.reason || '').trim();

  if (!/^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$/.test(time)) {
    return { ok: false, error: '时间格式非法，请输入 HH:MM' };
  }
  if (!stock) return { ok: false, error: '标的名称不能为空' };
  if (!code) return { ok: false, error: '代码不能为空' };

  var price = Number(priceRaw);
  if (!Number.isFinite(price) || price <= 0) {
    return { ok: false, error: '价格必须为有限正数' };
  }
  if (!/^[1-9]\d*$/.test(qtyRaw)) {
    return { ok: false, error: '数量必须为正整数' };
  }
  var qty = Number(qtyRaw);
  if (!Number.isSafeInteger(qty) || qty <= 0) {
    return { ok: false, error: '数量必须为正整数' };
  }

  return {
    ok: true,
    entry: {
      '时间': time,
      '动作': action,
      '标的': stock,
      '代码': code,
      '价格': price,
      '数量': qty,
      '窗口': windowName,
      '原因': reason
    }
  };
}

function _nowTime() {
  var d = new Date();
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}

function _bridgeSync(entry, onSuccess, onError) {
  var gate = _w15WriteGate();
  if (!gate.canWrite) {
    if (onError) onError(gate.reason);
    return;
  }
  if (location.protocol === 'file:') { if (onSuccess) onSuccess(); return; }
  fetch('/api/sync', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ entry: entry })
  }).then(function(r) {
    return r.ok ? r.json() : r.json().then(function(e) {
      e._httpStatus = r.status; throw e;
    });
  }).then(function(resp) {
    if (!resp || !resp.ok) {
      var errMsg = '成交写入失败: ' + ((resp && resp.error) || '未知错误');
      if (typeof showToast === 'function') showToast(errMsg);
      _setSyncStatus('error', errMsg);
      if (onError) onError(errMsg);
    } else {
      var okMsg = '已写入云端 · 成交 #' + (resp.trade_id || '?');
      if (typeof showToast === 'function') showToast(okMsg);
      _setSyncStatus('ok', okMsg);
      if (onSuccess) onSuccess(resp);
    }
  }).catch(function(e) {
    var isReadonly = e && e.error === 'readonly_dev_preview';
    var errMsg;
    if (isReadonly) {
      errMsg = '本地预览只读，请用 8088 实盘录入';
    } else if (e && e.message) {
      errMsg = '写入失败: ' + e.message;
    } else {
      errMsg = '网络错误，成交未保存';
    }
    if (typeof showToast === 'function') showToast(errMsg);
    _setSyncStatus('error', errMsg);
    if (onError) onError(errMsg);
  });
}
function _setSyncStatus(type, msg) {
  var el = document.getElementById('w15_sync_status');
  if (!el) return;
  el.textContent = msg;
  el.style.display = '';
  el.style.color = type === 'ok' ? 'var(--info)' : 'var(--danger)';
}

WidgetRegistry.register('W15', PositionsWidget);
