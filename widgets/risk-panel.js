// widgets/risk-panel.js — W14 账户风控 v3.0 (实时持仓联动)
'use strict';

function _w14Esc(v) {
  return String(v == null ? '' : v).replace(/[&<>"']/g, function(ch) {
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch];
  });
}

function _w14Num(v, fallback) {
  var n = parseFloat(v);
  return isFinite(n) ? n : (fallback || 0);
}

function _w14PctText(v) {
  var n = _w14Num(v, 0);
  return Math.round(n * 100) / 100;
}

function _w14RuleText(code) {
  var map = {
    DATA_UNTRUSTED: '数据不可信',
    SENTIMENT_STALE: '情绪数据过期',
    DAY_STOP: '单日熔断',
    LOSS_STREAK: '连亏空仓',
    DOUBLE_ICE: '连续双冰',
    CLIMAX_STOP: '极端高潮',
    CLIMAX_REDUCE: '高潮降仓',
    FRIDAY_W1: '旧周五W1提示',
    FRIDAY_TREND_CAP: '旧周五趋势提示',
    'WIN-ICE-W1-001': '冰点W1关闭',
    'WIN-ICE-POLAR-MAINLINE-001': '冰点主线人工复核',
    W1_EMOTION: 'W1情绪不足',
    W1_LIMIT_UP_PROFIT: 'W1涨停收益不足',
    W1_BROKEN_BOARD: 'W1炸板率过高',
    W1_PROMOTION: 'W1晋级率不足',
    W2_ICE: 'W2冰点关闭',
    W2_ICE_RISK: 'W2冰点风险过高',
    W2_BROKEN_BOARD: 'W2炸板率过高',
    LIANBAN_SIDE_CLOSED: '连板侧关闭',
    WEEK_STOP: '周回撤停止',
    MONTH_STOP: '月回撤停止'
  };
  return map[code] || '规则阻断';
}

function _w14SafeRuleLabel(code) {
  var label = _w14RuleText(code);
  return /[<>]/.test(String(label)) ? '规则阻断' : label;
}

function _w14SafeMessage(msg, code) {
  if (msg == null || /[<>]/.test(String(msg))) return _w14SafeRuleLabel(code);
  return msg;
}

function _w14BlockKind(block) {
  var code = block && block.code;
  if (code === 'DATA_UNTRUSTED' || code === 'SENTIMENT_STALE') return 'system';
  if (block && (block.scope === 'w1' || block.scope === 'w2' || block.scope === 'lianban')) return 'trade';
  return 'account';
}

function _w14Chip(block) {
  var kind = _w14BlockKind(block);
  var label = _w14SafeRuleLabel(block && block.code);
  if (block && block.code === 'DATA_UNTRUSTED') label = '收盘/行情状态';
  if (block && block.code === 'SENTIMENT_STALE') label = '情绪快照状态';
  return '<span class="w14-chip w14-chip-' + kind + '">' + _w14Esc(label) + '</span>';
}

class RiskPanelWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var R = (data && data.risk) || {};
    var liveQ = (data && data.live_quotes) || {};
    var pnlLive = (data && data.pnl_live) || {};
    var manual = DataStore.manualData.getAll();

    // 持仓（从账户 SSOT 同源数据）
    var hasSsotPositions = Array.isArray(pnlLive.positions);
    var basePos = JSON.parse(JSON.stringify(hasSsotPositions ? pnlLive.positions : ((data && data.positions) || [])));
    var P = basePos;
    try {
      var mp = JSON.parse(manual['_positions'] || 'null');
      if (!hasSsotPositions && mp && mp.length) {
        mp.forEach(function(m) {
          var idx = P.findIndex(function(p) { return p['标的'] === m['标的']; });
          if (idx >= 0) P[idx] = m; else P.push(m);
        });
      }
    } catch(e) {}

    // 注入实时现价
    P.forEach(function(p) {
      var q = liveQ[p['代码']] || {};
      var lp = parseFloat(q['最新价']) || 0;
      if (lp > 0) p['现价'] = lp;
    });

    // 计算实时盈亏
    var totalMV = 0, totalCost = 0;
    var activePos = P.filter(function(p) { var s=p['状态']||''; return s.indexOf('清')<0 && s.indexOf('删')<0; });
    activePos.forEach(function(p) {
      var qty = parseFloat(p['数量']) || 0;
      var cost = parseFloat(p['成本']) || 0;
      var price = parseFloat(p['现价']) || parseFloat(p['成本']) || 0;
      totalMV += price * qty;
      totalCost += cost * qty;
    });
    var realTimePnl = totalMV - totalCost;
    var realTimePnlPct = totalCost > 0 ? (realTimePnl / totalCost * 100) : 0;

    // 账户口径优先使用日内快照，避免过期基线把仓位显示成 100%。
    // pnlLive.cash=0 / mv=0 / total_asset=0 是合法值，用 != null 判断。
    if (pnlLive.mv != null && !isNaN(parseFloat(pnlLive.mv))) {
      totalMV = parseFloat(pnlLive.mv);
    }
    var totalAsset = pnlLive.total_asset != null && !isNaN(parseFloat(pnlLive.total_asset))
                  ? parseFloat(pnlLive.total_asset)
                  : parseFloat(((data && data.pnl) || {})['总资产'] || '0') || totalMV;
    var positionRatio = totalAsset > 0 ? (totalMV / totalAsset * 100) : 0;
    var availFund = pnlLive.cash != null && !isNaN(parseFloat(pnlLive.cash))
                  ? parseFloat(pnlLive.cash)
                  : (totalAsset - totalMV);

    // 风控基线
    var meltdownLine = parseFloat(R['单日熔断线']) || -3;
    var weekWarnLine = parseFloat(R['周回撤预警']) || 6;
    var monthWarnLine = parseFloat(R['月回撤预警']) || 10;
    var loseDays = parseInt(R['连亏天数']) || 0;
    var meltdown = R['熔断触发'];
    var weekDD = parseFloat(R['周累计回撤']) || 0;
    var monthDD = parseFloat(R['月累计回撤']) || 0;

    function money(v) {
      if (Math.abs(v) >= 1e4) return (v/1e4).toFixed(1)+'万';
      return v.toFixed(0);
    }
    function pct(v, plus) {
      if (v == null) return '—';
      return (plus && v>0?'+':'')+v.toFixed(2)+'%';
    }

    var html = '';

    // ===== rule_state 实时风控（Gate 1A）=====
    var RS = (data && data.rule_state) || null;
    var rsBlocks = RS ? (RS.blocks || []) : [];
    var rsWarnings = RS ? (RS.warnings || []) : [];
    var rsCaps = RS ? (RS.caps || {}) : {};
    var capTotal = RS && rsCaps.total_pct != null ? _w14PctText(rsCaps.total_pct) : null;
    var baseTotal = RS && rsCaps.base_total_pct != null ? _w14PctText(rsCaps.base_total_pct) : null;
    var sideLianban = RS && rsCaps.lianban_side_cap_pct != null ? _w14PctText(rsCaps.lianban_side_cap_pct) : null;
    var sideTrend = RS && rsCaps.trend_side_cap_pct != null ? _w14PctText(rsCaps.trend_side_cap_pct) : null;
    var firstEntry = RS && rsCaps.first_entry_pct != null ? _w14PctText(rsCaps.first_entry_pct) : null;
    var accountCap = RS && rsCaps.account_cap_pct != null ? _w14PctText(rsCaps.account_cap_pct) : null;
    var opportunityCap = RS && rsCaps.opportunity_cap_pct != null ? _w14PctText(rsCaps.opportunity_cap_pct) : null;
    var earnedCap = RS && rsCaps.earned_cap_pct != null ? _w14PctText(rsCaps.earned_cap_pct) : null;
    var singleStockCap = RS && rsCaps.single_stock_cap_pct != null ? _w14PctText(rsCaps.single_stock_cap_pct) : null;
    var availableAdd = RS && rsCaps.available_add_pct != null ? _w14PctText(rsCaps.available_add_pct) : null;
    var positionMode = String(rsCaps.position_control_mode || 'legacy');
    var addBlockReason = String(rsCaps.add_block_reason || '');

    var gateState = !RS ? '不可确认' : (RS.tradable ? (rsBlocks.length || rsWarnings.length ? '提示' : '可交易') : '阻断');
    var gateClass = !RS ? 'is-unknown' : (RS.tradable ? ((rsBlocks.length || rsWarnings.length) ? 'is-watch' : 'is-ready') : 'is-blocked');
    html += '<div class="w14-command ' + gateClass + '">' +
      '<div class="w14-command-head"><span><i>R0</i> 风控门禁</span><b>' + gateState + '</b></div>' +
      '<div class="w14-command-grid">' +
        '<div><span>交易状态</span><b>' + gateState + '</b><em>' + (!RS ? '等待 rule_state 返回' : (RS.tradable ? ((rsBlocks.length || rsWarnings.length) ? '局部受限，按窗口规则执行' : '可按窗口条件继续判断') : '禁止新开仓')) + '</em></div>' +
        '<div><span>执行仓位</span><b>' + (capTotal != null ? capTotal + '%' : '—') + '</b><em>' + (positionMode === 'earned_mainline' ? ('盈利 ' + (earnedCap != null ? earnedCap + '%' : '—') + ' / 可加 ' + (availableAdd != null ? availableAdd + '%' : '—') + (addBlockReason === 'floating_loss' ? ' / 浮亏不加' : '')) : ('基线 ' + (baseTotal != null ? baseTotal + '%' : '—') + ' / 首笔 ' + (firstEntry != null ? firstEntry + '%' : '—'))) + '</em></div>' +
        '<div><span>风险来源</span><b>' + rsBlocks.length + '</b><em>阻断 ' + rsBlocks.length + ' / 提示 ' + rsWarnings.length + '</em></div>' +
      '</div>' +
    '</div>';

    if (RS) {
      if (rsBlocks.length || rsWarnings.length) {
        var groups = {account: [], system: [], trade: []};
        rsBlocks.forEach(function(b){ groups[_w14BlockKind(b)].push(b); });
        html += '<div class="w14-gate">';
        html += '<div class="w14-gate-head"><span>' + (RS.tradable ? '规则约束' : '禁止开仓') + '</span><b>执行仓位 ' + (capTotal != null ? capTotal + '%' : '—') + '</b></div>';
        if (groups.account.length) {
          html += '<div class="w14-gate-row"><span>账户风控</span><div>' + groups.account.map(_w14Chip).join('') + '</div></div>';
        }
        if (groups.system.length) {
          html += '<div class="w14-gate-row"><span>系统状态</span><div>' + groups.system.map(_w14Chip).join('') + '</div></div>';
        }
        if (groups.trade.length) {
          html += '<div class="w14-gate-row"><span>交易条件</span><div>' + groups.trade.map(_w14Chip).join('') + '</div></div>';
        }
        if (rsWarnings.length) {
          html += '<div class="w14-gate-row"><span>提示</span><div>' + rsWarnings.map(function(w){ return '<span class="w14-chip w14-chip-trade">'+_w14Esc(_w14SafeMessage(w.message, w.code))+'</span>'; }).join('') + '</div></div>';
        }
        html += '</div>';
      }
      html += '<div class="w14-cap-line">基线 '+(baseTotal!=null?baseTotal+'%':'—')+
        ' | 连板侧 '+(sideLianban!=null?sideLianban+'%':'—')+
        ' | 趋势侧 '+(sideTrend!=null?sideTrend+'%':'—')+
        ' | 首笔 '+(firstEntry!=null?firstEntry+'%':'—')+
        (positionMode === 'earned_mainline' ?
          ' | 账户 '+(accountCap!=null?accountCap+'%':'—')+
          ' | 主线 '+(opportunityCap!=null?opportunityCap+'%':'—')+
          ' | 盈利 '+(earnedCap!=null?earnedCap+'%':'—')+
          ' | 单票 '+(singleStockCap!=null?singleStockCap+'%':'—') : '')+
        '</div>';
    }

    // === 持仓累计浮盈（大字）===
    var pnlCls = realTimePnl > 0 ? 'up' : realTimePnl < 0 ? 'down' : '';
    html += '<div class="w14-pnl-card">'+
      '<div style="font-size:var(--fs-label);color:var(--text-disabled)">持仓累计浮盈</div>'+
      '<div class="'+pnlCls+'" style="font-family:var(--font-mono);font-size:22px;font-weight:700">'+(realTimePnl>=0?'+':'')+money(realTimePnl)+'</div>'+
      '<div class="'+pnlCls+'" style="font-size:var(--fs-body)">'+pct(realTimePnlPct, true)+'</div>'+
      '</div>';

    // === 持仓概况 ===
    html += '<div class="w14-kpi-grid">'+
      '<div class="kpi-card"><div class="kpi-label">持仓市值</div>'+
        '<div class="kpi-value" style="font-size:14px">'+money(totalMV)+'</div></div>'+
      '<div class="kpi-card"><div class="kpi-label">可用资金</div>'+
        '<div class="kpi-value" style="font-size:14px">'+money(availFund)+'</div></div>'+
      '<div class="kpi-card"><div class="kpi-label">仓位</div>'+
        '<div class="kpi-value" style="font-size:14px;color:'+(positionRatio>80?'var(--danger)':positionRatio>50?'var(--warn)':'var(--info)')+'">'+positionRatio.toFixed(0)+'%</div></div>'+
      '<div class="kpi-card"><div class="kpi-label">持仓数</div>'+
        '<div class="kpi-value" style="font-size:14px">'+activePos.length+'只</div></div>'+
      '</div>';

    // === 风控线（实时 rule_state 驱动，旧 daily risk 仅供数值引用）===
    html += '<div class="w14-section-title">风控线</div><div class="w14-risk-lines">';

    if (!RS) {
      html += '<div class="ui-degraded"><strong>规则状态不可用</strong><span>无法确认实时风控结论。</span></div>';
    } else {
      // 从 rule_state 取实时阻断结论
      var dayStopBlock = rsBlocks.filter(function(b){ return b.code === 'DAY_STOP'; });
      var lossStreakBlock = rsBlocks.filter(function(b){ return b.code === 'LOSS_STREAK'; });
      var lossStreakWarn = rsWarnings.filter(function(w){ return w.code === 'LOSS_STREAK'; });
      var dayHit = dayStopBlock.length > 0;
      var streakHit = lossStreakBlock.length > 0;
      var streakWarn = !streakHit && lossStreakWarn.length > 0;
      var lossDaysDisplay = loseDays;
      if (streakHit && lossStreakBlock[0].evidence && lossStreakBlock[0].evidence.loss_streak != null) {
        lossDaysDisplay = _w14Num(lossStreakBlock[0].evidence.loss_streak, loseDays);
      } else if (streakWarn && lossStreakWarn[0].evidence && lossStreakWarn[0].evidence.loss_streak != null) {
        lossDaysDisplay = _w14Num(lossStreakWarn[0].evidence.loss_streak, loseDays);
      }

      html += '<div class="w14-risk-line">'+
        '<span>单日熔断</span>'+
        '<b>阈值 -3%</b>'+
        '<em class="' + (dayHit ? 'danger' : 'info') + '">'+(dayHit?'已触发':'未触发')+'</em></div>';

      html += '<div class="w14-risk-line">'+
        '<span>连亏天数</span>'+
        '<b>'+lossDaysDisplay+'天</b>'+
        '<em class="' + (streakHit ? 'danger' : streakWarn ? 'warn' : 'info') + '">'+
          (streakHit?'强制空仓':streakWarn?'提示':'正常')+
        '</em></div>';
    }

    // 周回撤（rule_state 不覆盖，保留 baseline 字段 + 数据引用）
    var weekAbs = Math.abs(weekDD);
    var wCls = weekAbs >= weekWarnLine ? 'danger' : weekAbs > 3 ? 'warn' : 'info';
    html += '<div class="w14-risk-line">'+
      '<span>周回撤</span>'+
      '<b>'+pct(weekDD)+' / '+weekWarnLine+'%</b>'+
      '<em class="'+wCls+'">'+(weekAbs>=weekWarnLine?'已触发':'—')+'</em></div>';

    // 月回撤
    var monthAbs = Math.abs(monthDD);
    var mCls = monthAbs >= monthWarnLine ? 'danger' : monthAbs > 5 ? 'warn' : 'info';
    html += '<div class="w14-risk-line">'+
      '<span>月回撤</span>'+
      '<b>'+pct(monthDD)+' / '+monthWarnLine+'%</b>'+
      '<em class="'+mCls+'">'+(monthAbs>=monthWarnLine?'已触发':'—')+'</em></div>';
    html += '</div>';

    // ===== 止损提醒（只读，优先 SSOT 止损字段，规则兜底明确标记）=====
    var slAlerts = [];
    activePos.forEach(function(p) {
      var cost = parseFloat(p['成本']) || 0;
      var price = parseFloat(p['现价']) || parseFloat(p['成本']) || 0;
      var qty = parseFloat(p['数量']) || 0;
      if (!cost || !price || !qty) return;
      var ssotSl = parseFloat(p['止损']);
      var hasSsotSl = !isNaN(ssotSl) && ssotSl > 0;
      var slPrice = hasSsotSl ? ssotSl : (cost * 0.93);
      var slSource = hasSsotSl ? '' : ' (规则推算)';
      var isNearSl = price <= slPrice * 1.02 && price > slPrice;
      var isHitSl = price <= slPrice;
      if (isHitSl || isNearSl) {
        var pnlPct = ((price - cost) / cost * 100);
        slAlerts.push({
          name: p['标的'] || '—', code: p['代码'] || '',
          cost: cost, price: price, sl: slPrice,
          pnlPct: pnlPct, hit: isHitSl, source: slSource
        });
      }
    });
    if (slAlerts.length > 0) {
      html += '<div style="margin-top:var(--sp-sm);border-top:1px solid var(--border-light);padding-top:var(--sp-sm)">' +
        '<div style="font-size:11px;font-weight:700;color:var(--danger);margin-bottom:4px">止损提醒</div>';
      slAlerts.forEach(function(a) {
        html += '<div class="' + (a.hit ? 'sl-alert' : '') + '" style="' + (a.hit ? '' : 'font-size:11px;padding:2px 8px;color:var(--warn);') + '">' +
          (a.hit ? '止损触发 · ' : '接近止损 · ') + a.name + ' ' + a.code +
          ' 成本' + a.cost.toFixed(2) + ' 现价' + a.price.toFixed(2) +
          ' 止损' + a.sl.toFixed(2) + a.source + ' 浮亏' + (a.pnlPct >= 0 ? '+' : '') + a.pnlPct.toFixed(2) + '%' +
          '</div>';
      });
      html += '</div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W14', RiskPanelWidget);
