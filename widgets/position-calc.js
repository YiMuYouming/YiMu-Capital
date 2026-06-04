// widgets/position-calc.js — W03 三层仓位计 (v3.0 rule_state 驱动)
'use strict';

function _w03RuleText(code) {
  var map = {
    DATA_UNTRUSTED: '数据不可信',
    SENTIMENT_STALE: '情绪数据过期',
    DAY_STOP: '单日熔断',
    LOSS_STREAK: '连亏空仓',
    WEEK_STOP: '周回撤停止',
    MONTH_STOP: '月回撤停止',
    DOUBLE_ICE: '连续双冰',
    CLIMAX_STOP: '极端高潮',
    CLIMAX_REDUCE: '高潮降仓',
    FRIDAY_W1: '周五关闭W1',
    FRIDAY_TREND_CAP: '周五趋势上限',
    W1_EMOTION: 'W1情绪不足',
    W1_LIMIT_UP_PROFIT: 'W1涨停收益不足',
    W1_BROKEN_BOARD: 'W1炸板率过高',
    W1_PROMOTION: 'W1晋级率不足',
    W2_ICE: 'W2冰点关闭',
    W2_ICE_RISK: 'W2冰点风险过高',
    W2_BROKEN_BOARD: 'W2炸板率过高',
    LIANBAN_SIDE_CLOSED: '连板侧关闭'
  };
  return map[code] || code || '规则阻断';
}

function _w03Money(n) {
  n = Number(n) || 0;
  return Math.round(n).toLocaleString();
}

function _w03PctRangeMoney(range, totalCapital) {
  var m = String(range || '').match(/(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)/);
  if (!m) return '';
  var low = Math.round((Number(totalCapital) || 0) * Number(m[1]) / 100);
  var high = Math.round((Number(totalCapital) || 0) * Number(m[2]) / 100);
  return _w03Money(low) + '-' + _w03Money(high);
}

function _w03BlockChips(blocks, scope) {
  var items = (blocks || []).filter(function(b){ return b.scope === scope; });
  if (!items.length) return '';
  return items.map(function(b) {
    return '<span class="w03-chip w03-chip-' + (scope === 'all' ? 'risk' : 'warn') + '">' + _w03RuleText(b.code) + '</span>';
  }).join('');
}

function _w03WindowChips(codes) {
  return (codes || []).map(function(code) {
    return '<span class="w03-chip w03-chip-muted">' + _w03RuleText(code) + '</span>';
  }).join('');
}

class PositionCalcWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var ST = (data && data.style) || {};
    var R = (data && data.risk) || {};
    var RS = (data && data.rule_state) || null;

    // ── rule_state 优先（Gate 1A 实时规则引擎） ──
    var rsCaps = (RS && RS.caps) || {};
    var rsBlocks = (RS && RS.blocks) || [];
    var rsWarnings = (RS && RS.warnings) || [];
    var rsWindows = (RS && RS.windows) || {};

    var totalCap = rsCaps.total_pct != null ? rsCaps.total_pct : (ST['总仓位上限'] || 0);
    var baseCap = rsCaps.base_total_pct != null ? rsCaps.base_total_pct : (ST['总仓位上限'] || 0);
    var lbPct = rsCaps.lianban_pct != null ? rsCaps.lianban_pct : (ST['连板占比'] || 0);
    var trPct = rsCaps.trend_pct != null ? rsCaps.trend_pct : (ST['趋势占比'] || 0);
    var baseLbPct = ST['连板占比'] || lbPct || 0;
    var baseTrPct = ST['趋势占比'] || trPct || 0;
    var planTotalCap = ST['总仓位上限'] || baseCap || totalCap || 0;
    var planW2Cap = ST['新开趋势W2上限'] || '';
    var firstEntryPct = rsCaps.first_entry_pct != null ? rsCaps.first_entry_pct : 10;

    // 全局阻断：tradable=false 或 scope=all 的 blocks
    var globallyBlocked = RS ? !RS.tradable : false;
    var allScopeCodes = rsBlocks.filter(function(b){ return b.scope === 'all'; })
                               .map(function(b){ return _w03RuleText(b.code); });
    var blockReasons = rsBlocks.map(function(b){ return b.message; });

    // 缺失 rule_state 时显示不可用
    var rsMissing = !RS;

    // 旧风控字段保持兜底（仅在 rule_state 缺失时使用）
    var meltdown = R['熔断触发'];
    var loseStreak = R['连亏天数'] || 0;
    if (rsMissing && (meltdown || loseStreak >= 2)) {
      globallyBlocked = true;
    }

    var html = '';
    var manual = DataStore.manualData.getAll();
    var pnlLive = (data && data.pnl_live) || {};
    var liveQ = (data && data.live_quotes) || {};

    var totalCapital = pnlLive.total_asset != null && !isNaN(parseFloat(pnlLive.total_asset))
                    ? parseFloat(pnlLive.total_asset)
                    : parseFloat((data.pnl||{})['总资产'] || '0') || 0;
    var currentPosVal = 0;
    (data.positions||[]).forEach(function(p){
      var s = String(p['状态']||'');
      if (s && s.indexOf('持有') >= 0 && s.indexOf('清') < 0 && s.indexOf('删') < 0) {
        var q = liveQ[p['代码']] || {};
        currentPosVal += Math.round((parseFloat(p['数量'])||0)*(parseFloat(q['最新价'])||parseFloat(p['现价'])||parseFloat(p['成本'])||0));
      }
    });
    if (pnlLive.mv != null && !isNaN(parseFloat(pnlLive.mv))) {
      currentPosVal = parseFloat(pnlLive.mv);
    }
    var availCash = pnlLive.cash != null && !isNaN(parseFloat(pnlLive.cash))
                 ? parseFloat(pnlLive.cash)
                 : (totalCapital > 0 && pnlLive.mv != null ? totalCapital - parseFloat(pnlLive.mv) : 0)
                 || parseFloat((data.pnl||{})['可用资金'] || '0')
                 || (totalCapital - currentPosVal);
    var currentPosPct = totalCapital > 0 ? Math.round(currentPosVal / totalCapital * 100) : 0;
    var maxPosition = Math.round(totalCapital * (totalCap||0) / 100);
    var planMaxPosition = Math.round(totalCapital * (planTotalCap||0) / 100);
    var availPct = Math.max(0, totalCap - currentPosPct);

    // ── rule_state 缺失提示 ──
    if (rsMissing) {
      html += '<div style="padding:var(--sp-md);text-align:center;color:var(--danger);font-weight:600">'
        +'规则状态不可用</div>'
        +'<div style="font-size:var(--fs-body);color:var(--text-disabled);text-align:center">后端 rule_state 未生成，实时仓位结论暂停显示</div>';
      body.innerHTML = html;
      this.updateTimestamp();
      return;
    }

    html += '<div class="w03-stack">';

    // ===== Layer 1: 总仓位上限 =====
    html += '<section class="w03-layer' + (globallyBlocked ? ' w03-layer-blocked' : '') + '">' +
      '<div class="w03-layer-head">' +
        '<span class="w03-layer-index">第一层</span>' +
        '<span class="w03-layer-title">总仓位门禁</span>' +
      '</div>' +
      '<div class="w03-layer-main">' +
        '<div><div class="w03-kpi ' + (globallyBlocked ? 'danger' : 'info') + '">' + totalCap + '%</div><div class="w03-caption">执行上限</div></div>' +
        '<div class="w03-metrics">' +
          '<span>基础 <b>' + baseCap + '%</b></span>' +
          (planTotalCap !== baseCap ? '<span>计划 <b>' + planTotalCap + '%</b></span>' : '') +
          '<span>首笔 <b>' + firstEntryPct + '%</b></span>' +
        '</div>' +
      '</div>' +
      (globallyBlocked ? '<div class="w03-note">全局阻断后执行上限归零</div>' : '<div class="w03-note">按实时规则引擎输出执行仓位</div>') +
      '</section>';

    // ===== Layer 2: 风格分配 =====
    html += '<section class="w03-layer' + (globallyBlocked ? ' w03-layer-blocked' : '') + '">' +
      '<div class="w03-layer-head">' +
        '<span class="w03-layer-index">第二层</span>' +
        '<span class="w03-layer-title">风格分配</span>' +
      '</div>' +
      '<div class="w03-split-row">' +
        '<div class="w03-split-item"><span>连板执行</span><b class="up">' + lbPct + '%</b></div>' +
        '<div class="w03-split-item"><span>趋势执行</span><b class="info">' + trPct + '%</b></div>' +
      '</div>' +
      '<div class="w03-track"><i style="width:' + Math.max(0, Math.min(100, baseLbPct)) + '%;background:var(--up)"></i><i style="width:' + Math.max(0, Math.min(100, baseTrPct)) + '%;background:var(--info)"></i></div>' +
      '<div class="w03-note">风格基线 / 计划分配：连板 ' + baseLbPct + '% / 趋势 ' + baseTrPct + '%' + (planW2Cap ? ' / W2 ' + planW2Cap : '') + '</div>' +
      '</section>';

    // ===== Layer 3: W1/W2 窗口 =====
    var w1 = rsWindows.w1 || {};
    var w2 = rsWindows.w2 || {};
    var w1Open = w1.buy_allowed;
    var w2Open = w2.buy_allowed;
    function windowLabel(w, openText, timeText) {
      if (w.buy_allowed) return openText;
      if (!w.in_session) return timeText;
      return '规则限制';
    }
    var w1Label = windowLabel(w1, '追涨/回踩', '09:30-10:00');
    var w2Label = windowLabel(w2, '低吸/回踩', '14:00-14:50');
    html += '<section class="w03-layer' + (globallyBlocked ? ' w03-layer-blocked' : '') + '">' +
      '<div class="w03-layer-head">' +
        '<span class="w03-layer-index">第三层</span>' +
        '<span class="w03-layer-title">交易窗口</span>' +
      '</div>' +
      '<div class="w03-window-grid">' +
        '<div class="w03-window"><span>W1</span><b class="' + (w1Open ? 'up' : 'text-disabled') + '">' + w1Label + '</b><em>' + (w1.in_session ? '盘中' : '待开') + '</em></div>' +
        '<div class="w03-window"><span>W2</span><b class="' + (w2Open ? 'info' : 'text-disabled') + '">' + w2Label + '</b><em>' + (w2.in_session ? '盘中' : '待开') + '</em></div>' +
      '</div>' +
      '</section>';
    html += '</div>';

    // ===== 金额计算 =====
    var newCap = Math.max(0, maxPosition - currentPosVal);
    var planNewCap = Math.max(0, planMaxPosition - currentPosVal);
    var lbMoney = globallyBlocked ? 0 : Math.round(newCap * lbPct / 100);
    var trMoney = globallyBlocked ? 0 : Math.round(newCap * trPct / 100);
    var sumMoney = lbMoney + trMoney;
    var planLbMoney = Math.round(planNewCap * baseLbPct / 100);
    var planTrMoney = Math.round(planNewCap * baseTrPct / 100);
    var w2RangeMoney = _w03PctRangeMoney(planW2Cap, totalCapital);

    html += '<div class="w03-money">' +
      '<div class="w03-money-head">' +
        '<span>金额测算</span>' +
        '<b class="' + (globallyBlocked ? 'danger' : 'info') + '">' + _w03Money(sumMoney) + '</b>' +
      '</div>' +
      '<div class="w03-money-meta">执行上限 ' + totalCap + '% = ' + _w03Money(maxPosition) + ' / 已持仓 ' + _w03Money(currentPosVal) + ' / 当前可新开 ' + _w03Money(newCap) + '</div>' +
      '<div class="w03-money-meta">计划上限 ' + planTotalCap + '% = ' + _w03Money(planMaxPosition) + ' / 计划可新开 ' + _w03Money(planNewCap) + (w2RangeMoney ? ' / W2趋势上限 ' + w2RangeMoney : '') + '</div>' +
      '<div class="w03-money-grid">' +
        '<div><span>连板计划可新开</span><b class="up">' + _w03Money(planLbMoney) + '</b><em>' + _w03Money(planNewCap) + ' × ' + baseLbPct + '%</em></div>' +
        '<div><span>趋势计划可新开</span><b class="info">' + _w03Money(planTrMoney) + '</b><em>' + _w03Money(planNewCap) + ' × ' + baseTrPct + '%</em></div>' +
      '</div></div>';

    // 阻断详情
    if (rsBlocks.length) {
      html += '<div class="w03-blocks">';
      var allChips = _w03BlockChips(rsBlocks, 'all');
      var lianbanChips = _w03BlockChips(rsBlocks, 'lianban');
      var w1Chips = _w03WindowChips(w1.blocks);
      var w2Chips = _w03WindowChips(w2.blocks);
      if (allChips) html += '<div class="w03-block-row"><span>全局门禁</span><div>' + allChips + '</div></div>';
      if (lianbanChips) html += '<div class="w03-block-row"><span>连板侧</span><div>' + lianbanChips + '</div></div>';
      if (w1Chips) html += '<div class="w03-block-row"><span>W1 条件</span><div>' + w1Chips + '</div></div>';
      if (w2Chips) html += '<div class="w03-block-row"><span>W2 条件</span><div>' + w2Chips + '</div></div>';
      html += '</div>';
    }
    if (rsWarnings.length) {
      html += '<div class="w03-blocks">';
      rsWarnings.forEach(function(w){ html += '<div class="w03-block-row"><span>提示</span><div><span class="w03-chip w03-chip-warn">'+w.message+'</span></div></div>'; });
      html += '</div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W03', PositionCalcWidget);
