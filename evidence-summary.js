// evidence-summary.js — S0/E/A/R summary for external AI workflows
'use strict';

(function(root) {
  function num(v) {
    if (v === null || v === undefined || v === '') return null;
    var n = Number(String(v).replace(/,/g, '').replace('%', ''));
    return isNaN(n) ? null : n;
  }
  function text(v, fallback) {
    if (v === null || v === undefined || v === '') return fallback || '—';
    return String(v);
  }
  function signedPct(v) {
    var n = num(v);
    if (n === null) return '—';
    return (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
  }
  function moneyWan(v) {
    var n = num(v);
    if (n === null) return '—';
    return (n / 10000).toFixed(1) + '万';
  }
  function toneForPct(v) {
    var n = num(v);
    if (n === null || n === 0) return 'neutral';
    return n > 0 ? 'up' : 'down';
  }
  function connectionLabel(status) {
    var map = {
      live: '实时',
      polling: '轮询',
      delayed: '延迟',
      stale: '过期',
      dead: '断开',
      close_snapshot: '收盘快照'
    };
    return map[status] || text(status, '—');
  }
  function sourceLabel(source) {
    var map = {
      topbar: '系统',
      'rule_state/api_health': '规则',
      rule_state: '规则',
      pnl_live: '账户',
      EvidenceSummary: '摘要'
    };
    return map[source] || source || '';
  }
  function freshnessLabel(level) {
    var map = {
      delayed: '延迟',
      stale: '过期',
      dead: '过期'
    };
    return map[level] || level || '';
  }
  function activePositions(pnl) {
    var list = Array.isArray(pnl.positions) ? pnl.positions : [];
    return list.filter(function(p) {
      var st = String(p['状态'] || p.status || '');
      return st.indexOf('清') < 0 && st.indexOf('删') < 0;
    });
  }
  function pickCorePosition(pnl) {
    var list = activePositions(pnl);
    if (!list.length) return null;
    return list.slice().sort(function(a, b) {
      return (num(b['市值'] || b.market_value) || 0) - (num(a['市值'] || a.market_value) || 0);
    })[0];
  }
  function ticketCounts(tickets) {
    var counts = { pending: 0, executable: 0, blocked: 0, done: 0, total: 0 };
    (Array.isArray(tickets) ? tickets : []).forEach(function(t) {
      counts.total += 1;
      var st = String(t.status || '').toLowerCase();
      if (st === 'draft' || st === 'confirmed') counts.pending += 1;
      else if (st === 'executable') counts.executable += 1;
      else if (st === 'blocked' || st === 'audit_degraded') counts.blocked += 1;
      else if (st === 'filled' || st === 'partially_filled' || st === 'closed' || st === 'closed_with_conflict' || st === 'cancelled') counts.done += 1;
    });
    return counts;
  }
  function ruleCodeLabel(code) {
    var map = {
      DATA_UNTRUSTED: '数据不可信',
      SENTIMENT_STALE: '情绪数据过期',
      DAY_STOP: '单日熔断',
      LOSS_STREAK: '连亏空仓',
      DOUBLE_ICE: '连续双冰',
      CLIMAX_STOP: '极端高潮',
      CLIMAX_REDUCE: '高潮降仓',
      FRIDAY_W1: '旧周五 W1 提示',
      FRIDAY_TREND_CAP: '旧周五趋势提示',
      W1_EMOTION: 'W1 情绪不足',
      W1_LIMIT_UP_PROFIT: 'W1 涨停收益不足',
      W1_BROKEN_BOARD: 'W1 炸板过高',
      W1_PROMOTION: 'W1 晋级率不足',
      W2_ICE_RISK: 'W2 冰点风险',
      W2_BROKEN_BOARD: 'W2 炸板过高',
      LIANBAN_SIDE_CLOSED: '连板侧关闭',
      WEEK_STOP: '周回撤停止',
      MONTH_STOP: '月回撤停止'
    };
    return map[code] || code || '规则阻断';
  }
  function primaryBlock(rule) {
    var blocks = Array.isArray(rule && rule.blocks) ? rule.blocks : [];
    return blocks[0] || null;
  }
  function phaseFrom(rule, quoteStatus, now) {
    if (quoteStatus === 'close_snapshot') return { id: 'close', label: '收盘快照', detail: '复盘对账，不做实时开仓判断' };
    var windows = (rule && rule.windows) || {};
    if (windows.w1 && windows.w1.in_session) return { id: 'w1', label: 'W1 早盘', detail: '09:30-10:00 追涨/强回踩核对' };
    if (windows.w2 && windows.w2.in_session) return { id: 'w2', label: 'W2 尾盘', detail: '14:00-14:50 低吸/趋势确认' };
    var d = now ? new Date(now) : new Date();
    var h = d.getHours();
    var m = d.getMinutes();
    var mins = h * 60 + m;
    if (mins >= 9 * 60 + 15 && mins < 9 * 60 + 30) return { id: 'auction', label: '竞价', detail: '核对 9:25/9:28 快照' };
    if (mins >= 9 * 60 + 30 && mins < 11 * 60 + 30) return { id: 'morning', label: '盘中观察', detail: '优先核对 W15/W14/W09' };
    if (mins >= 11 * 60 + 30 && mins < 13 * 60) return { id: 'midday', label: '午盘复核', detail: '复核上午动作和风险' };
    if (mins >= 13 * 60 && mins < 14 * 60) return { id: 'afternoon', label: '盘中观察', detail: '等待 W2 或票据闭环' };
    if (mins >= 14 * 60 && mins < 15 * 60) return { id: 'late', label: '尾盘闭环', detail: '核对 W2、票据和收盘风险' };
    return { id: 'off', label: '非交易时段', detail: '以复盘和对账为主' };
  }
  function gate(id, title, state, value, detail, target) {
    return { id: id, title: title, state: state, value: value || '—', detail: detail || '', target: target || '' };
  }
  function action(id, title, target, reason, tone) {
    return { id: id, title: title, target: target, reason: reason || '', tone: tone || 'neutral' };
  }

  function normalizeRuntime(runtime) {
    runtime = runtime || {};
    var confirmed = runtime.healthConfirmed === true;
    var label = text(runtime.healthLabel, runtime.healthCritical ? '阻断' : (confirmed ? '正常' : '未确认'));
    return {
      healthLabel: label === '—' && !confirmed ? '未确认' : label,
      healthCritical: runtime.healthCritical === true,
      healthConfirmed: confirmed,
      tradeEntryAllowed: runtime.tradeEntryAllowed === true,
      connectionStatus: text(runtime.connectionStatus, '—'),
      quoteHealthStatus: runtime.quoteHealthStatus || '',
      now: runtime.now || new Date().toISOString()
    };
  }

  function build(data, runtime) {
    data = data || {};
    var rt = normalizeRuntime(runtime);
    var pnl = data.pnl_live || {};
    var rule = data.rule_state || {};
    var sentiment = data.sentiment || {};
    var iw = data.iwencai || {};
    var tickets = Array.isArray(data.trade_tickets) ? data.trade_tickets : [];
    var core = pickCorePosition(pnl);
    var counts = ticketCounts(tickets);
    var quoteStatus = pnl.quote_status || rt.quoteHealthStatus || rt.connectionStatus;
    var valuationComplete = pnl.valuation_complete !== false;
    var tradeAllowed = rt.healthConfirmed && !rt.healthCritical && rt.tradeEntryAllowed === true && rule.tradable !== false;
    var healthLabel = rt.healthLabel === '—' && rt.healthCritical ? '阻断' : rt.healthLabel;
    var connectionText = connectionLabel(quoteStatus);
    var tradeText = !rt.healthConfirmed ? '状态未确认' : (tradeAllowed ? '可交易' : '交易阻断');
    var phase = phaseFrom(rule, quoteStatus, rt.now);
    var block = primaryBlock(rule);
    var blocks = Array.isArray(rule.blocks) ? rule.blocks : [];
    var warnings = Array.isArray(rule.warnings) ? rule.warnings : [];

    var positionPctText = pnl.pos_pct == null
      ? (num(pnl.mv) !== null && num(pnl.total_asset) ? (num(pnl.mv) / num(pnl.total_asset) * 100).toFixed(1) + '%' : '—')
      : num(pnl.pos_pct).toFixed(1) + '%';
    var positionPctNum = num(positionPctText);
    var cap = rule.caps && rule.caps.total_pct;
    var firstEntry = rule.caps && rule.caps.first_entry_pct;
    var remainingCap = (cap == null || positionPctNum == null) ? null : Math.max(0, num(cap) - positionPctNum);

    var situation = {
      id: 'S0',
      title: '当前总态势',
      summary: tradeText + ' · ' + connectionText + ' · 情绪 ' + (sentiment['情绪值'] == null ? '—' : Math.round(num(sentiment['情绪值'])) + '%'),
      health: { label: healthLabel, critical: rt.healthCritical, confirmed: rt.healthConfirmed },
      trade: { allowed: tradeAllowed },
      connection: { status: quoteStatus, label: connectionText },
      sentiment: { value: num(sentiment['情绪值']), text: sentiment['情绪值'] == null ? '—' : Math.round(num(sentiment['情绪值'])) + '%' },
      pnl: {
        total_asset_text: moneyWan(pnl.total_asset),
        cash_text: moneyWan(pnl.cash),
        position_pct_text: positionPctText,
        pnl_pct_text: signedPct(pnl.pnl_pct),
        pnl_amount_text: moneyWan(pnl.pnl_amount)
      }
    };

    var dataReasons = [];
    if (!rt.healthConfirmed) dataReasons.push('健康未确认');
    if (rt.healthCritical) dataReasons.push(healthLabel || '健康阻断');
    if (!valuationComplete) dataReasons.push(text(pnl.block_reason, '估值未完成'));
    if (quoteStatus === 'close_snapshot') dataReasons.push('收盘快照');
    if (quoteStatus === 'dead') dataReasons.push('行情断开');
    if (quoteStatus === 'stale') dataReasons.push('行情过期');
    var dataState = dataReasons.length ? '阻断' : (quoteStatus === 'delayed' ? '提示' : '通过');
    var dataValue = quoteStatus === 'live' ? '实时' : connectionText;

    var ruleState = (!rt.healthConfirmed || rt.healthCritical || rt.tradeEntryAllowed !== true || rule.tradable === false || blocks.length) ? '阻断' : (warnings.length ? '提示' : '通过');
    var ruleValue = block ? ruleCodeLabel(block.code) : (ruleState === '通过' ? '可交易' : healthLabel);
    var activeWindow = rule.windows && rule.windows.w1 && rule.windows.w1.in_session ? rule.windows.w1 :
      (rule.windows && rule.windows.w2 && rule.windows.w2.in_session ? rule.windows.w2 : null);
    var activeWindowName = rule.windows && rule.windows.w1 && rule.windows.w1.in_session ? 'W1' :
      (rule.windows && rule.windows.w2 && rule.windows.w2.in_session ? 'W2' : '—');
    var windowState = activeWindow ? (activeWindow.buy_allowed ? '通过' : '阻断') : '提示';
    var windowValue = activeWindow ? (activeWindowName + (activeWindow.buy_allowed ? ' 允许' : ' 关闭')) : phase.label;
    var capNum = num(cap);
    var positionState = capNum === 0 ? '阻断' : (capNum == null ? '提示' : (remainingCap != null && remainingCap <= Math.max(num(firstEntry) || 10, 5) ? '提示' : '通过'));
    var positionValue = capNum == null ? '上限 —' : ('上限 ' + capNum + '%');
    var ticketState = counts.blocked > 0 ? '提示' : (counts.executable > 0 ? '通过' : (counts.pending > 0 ? '提示' : '通过'));
    var ticketValue = counts.executable > 0 ? ('可执行 ' + counts.executable) : (counts.done + '/' + counts.total);
    var gates = [
      gate('G1', '数据可信', dataState, dataValue, dataReasons.join(' / ') || '行情与账户估值可用于盘中判断', 'W15'),
      gate('G2', '规则门禁', ruleState, ruleValue, block ? text(block.message, ruleCodeLabel(block.code)) : (warnings.length ? '存在规则提示' : 'rule_state 未发现关键阻断'), 'W14'),
      gate('G3', '窗口状态', windowState, windowValue, activeWindow ? '来自 rule_state.windows' : phase.detail, activeWindowName === 'W1' ? 'W08' : activeWindowName === 'W2' ? 'W09' : ''),
      gate('G4', '仓位空间', positionState, positionValue, '当前仓位 ' + positionPctText + ' / 首笔 ' + (firstEntry == null ? '—' : firstEntry + '%'), 'W14'),
      gate('G5', '票据闭环', ticketState, ticketValue, '待确认 ' + counts.pending + ' / 阻断 ' + counts.blocked + ' / 已闭环 ' + counts.done, 'W24')
    ];

    var commandLabel = '观察等待';
    var commandTone = 'watch';
    var commandReason = '等待窗口、票据或规则信号';
    if (!rt.healthConfirmed) {
      commandLabel = '不可确认';
      commandTone = 'blocked';
      commandReason = '健康门禁未确认';
    } else if (dataState === '阻断' || ruleState === '阻断' || capNum === 0) {
      commandLabel = '禁止开仓';
      commandTone = 'blocked';
      commandReason = block ? ((block.code || 'RULE') + ' / ' + text(block.message, ruleCodeLabel(block.code))) : (dataReasons.join(' / ') || '规则或数据门禁阻断');
    } else if (counts.executable > 0) {
      commandLabel = '可执行票据';
      commandTone = 'ready';
      commandReason = '存在 ' + counts.executable + ' 张可执行票据，先核对 W24';
    } else if (rule.windows && rule.windows.w1 && rule.windows.w1.in_session && rule.windows.w1.buy_allowed) {
      commandLabel = '可核对 W1';
      commandTone = 'ready';
      commandReason = 'W1 窗口开放，按 W08 三件套核对';
    } else if (rule.windows && rule.windows.w2 && rule.windows.w2.in_session && rule.windows.w2.buy_allowed) {
      commandLabel = '可核对 W2';
      commandTone = 'ready';
      commandReason = 'W2 窗口开放，按 W09 趋势/低吸条件核对';
    } else if (counts.pending > 0 || counts.blocked > 0 || warnings.length) {
      commandLabel = '观察等待';
      commandTone = 'warn';
      commandReason = '有票据或规则提示待核对';
    }
    var command = {
      id: 'S0',
      label: commandLabel,
      tone: commandTone,
      reason: commandReason,
      next: commandLabel === '禁止开仓' ? '复核 W14；如需退出，只走人工确认的减仓/清仓' :
        commandLabel === '可执行票据' ? '打开 W24 核对票据与执行链' :
        commandLabel === '可核对 W1' ? '打开 W08，核对早盘三件套与候选' :
        commandLabel === '可核对 W2' ? '打开 W09，核对尾盘候选与仓位空间' :
        '保持观察，等待新鲜数据或窗口信号'
    };

    var evidence = [];
    if (core) {
      var corePct = core.today_pnl_pct != null ? core.today_pnl_pct : core.total_pnl_pct;
      evidence.push({
        id: 'E1',
        title: text(core['标的'] || core.name, '核心持仓'),
        value: signedPct(corePct),
        detail: text(core['代码'] || core.code, '') + ' 市值 ' + moneyWan(core['市值'] || core.market_value) + ' 成本 ' + text(core['成本'] || core['成本价'], '—'),
        source: sourceLabel('W15'),
        tone: toneForPct(corePct)
      });
    } else {
      evidence.push({ id: 'E1', title: '当前空仓或持仓不可用', value: '—', detail: '暂无活动持仓，或账户数据尚未返回', source: sourceLabel('W15'), tone: 'neutral' });
    }
    evidence.push({ id: 'E2', title: '票据闭环', value: counts.done + '/' + counts.total, detail: '待确认 ' + counts.pending + '，可执行 ' + counts.executable + '，阻断 ' + counts.blocked, source: sourceLabel('W24'), tone: counts.blocked > 0 ? 'warn' : 'neutral' });
    var sentimentValue = num(sentiment['情绪值']);
    evidence.push({ id: 'E3', title: '市场情绪', value: situation.sentiment.text, detail: '涨停 ' + text(iw['涨停家数'], '—') + '，跌停 ' + text(iw['跌停家数'], '—'), source: sourceLabel('W04/W05'), tone: sentimentValue === null ? 'neutral' : sentimentValue < 20 ? 'danger' : sentimentValue < 40 ? 'warn' : 'neutral' });
    evidence.push({ id: 'E4', title: '账户收益', value: situation.pnl.pnl_pct_text, detail: '总资产 ' + situation.pnl.total_asset_text + '，可用 ' + situation.pnl.cash_text + '，仓位 ' + situation.pnl.position_pct_text, source: sourceLabel('W22'), tone: toneForPct(pnl.pnl_pct) });

    var alerts = [];
    if (!rt.healthConfirmed) alerts.push({ id: 'A1', title: '健康未确认', detail: '等待 /api/health 返回，主态势按不可交易处理', source: sourceLabel('topbar'), tone: 'danger' });
    else if (healthLabel === '降级' || rt.healthCritical) alerts.push({ id: 'A1', title: rt.healthCritical ? '系统阻断' : '系统降级', detail: rt.healthCritical ? '交易入口关闭，先复核规则和账户状态' : '非关键数据源降级，交易入口仍可按规则判断', source: sourceLabel('topbar'), tone: rt.healthCritical ? 'danger' : 'warn' });
    if (quoteStatus === 'close_snapshot') alerts.push({ id: 'A' + (alerts.length + 1), title: '收盘快照', detail: '当前为非实时行情，适合复盘和对账，不等同于行情断开', source: sourceLabel('W15/W22'), tone: 'neutral' });
    if (!valuationComplete) alerts.push({ id: 'A' + (alerts.length + 1), title: '估值待复核', detail: text(pnl.block_reason, '账户估值尚未完整返回'), source: sourceLabel('pnl_live'), tone: 'warn' });
    var iwFresh = iw._freshness || {};
    if (iwFresh.level === 'stale' || iwFresh.level === 'dead' || iwFresh.level === 'delayed') alerts.push({ id: 'A' + (alerts.length + 1), title: '情绪源' + freshnessLabel(iwFresh.level), detail: '同花顺情绪数据未保持新鲜，参考 W04 降级提示', source: sourceLabel('W04'), tone: iwFresh.level === 'dead' ? 'warn' : 'warn' });
    if (!alerts.length) alerts.push({ id: 'A1', title: '暂无关键异常', detail: '未发现需要优先处理的异常', source: sourceLabel('EvidenceSummary'), tone: 'neutral' });

    var risks = [];
    if (!rt.healthConfirmed) {
      risks.push({ id: 'R1', title: '状态未确认', detail: '健康门禁未确认前不显示可交易', source: sourceLabel('rule_state/api_health'), tone: 'danger' });
    } else if (!tradeAllowed || blocks.length) {
      risks.push({ id: 'R1', title: '交易阻断', detail: blocks.length ? text(blocks[0].message || blocks[0].code, '规则阻断') : '交易入口被健康门禁关闭', source: sourceLabel('rule_state/api_health'), tone: 'danger' });
    } else {
      risks.push({ id: 'R1', title: '交易入口允许', detail: '未发现关键阻断', source: sourceLabel('rule_state/api_health'), tone: 'neutral' });
    }
    risks.push({ id: 'R2', title: '仓位上限', detail: cap == null ? '仓位上限不可用' : '当前规则仓位上限 ' + cap + '%', source: sourceLabel('rule_state'), tone: cap === 0 ? 'danger' : 'neutral' });

    var actionQueue = [];
    if (dataState === '阻断' || ruleState === '阻断' || capNum === 0) {
      actionQueue.push(action('Q1', '复核阻断原因', 'W14', (block ? (block.code + ': ' + text(block.message, ruleCodeLabel(block.code))) : (dataReasons.join(' / ') || '规则门禁阻断')), 'danger'));
    }
    if (counts.executable > 0) {
      actionQueue.push(action('Q' + (actionQueue.length + 1), '核对可执行票据', 'W24', '可执行 ' + counts.executable + ' / 总票据 ' + counts.total, 'ready'));
    }
    if (rule.windows && rule.windows.w1 && rule.windows.w1.in_session) {
      actionQueue.push(action('Q' + (actionQueue.length + 1), '核对 W1 窗口', 'W08', rule.windows.w1.buy_allowed ? 'W1 buy_allowed=true' : 'W1 关闭: ' + (rule.windows.w1.blocks || []).join(','), rule.windows.w1.buy_allowed ? 'ready' : 'danger'));
    }
    if (rule.windows && rule.windows.w2 && rule.windows.w2.in_session) {
      actionQueue.push(action('Q' + (actionQueue.length + 1), '核对 W2 窗口', 'W09', rule.windows.w2.buy_allowed ? 'W2 buy_allowed=true' : 'W2 关闭: ' + (rule.windows.w2.blocks || []).join(','), rule.windows.w2.buy_allowed ? 'ready' : 'danger'));
    }
    if (counts.blocked > 0 || counts.pending > 0) {
      actionQueue.push(action('Q' + (actionQueue.length + 1), '复核票据闭环', 'W24', '待确认 ' + counts.pending + ' / 阻断 ' + counts.blocked, counts.blocked > 0 ? 'warn' : 'neutral'));
    }
    if (core) {
      actionQueue.push(action('Q' + (actionQueue.length + 1), '核对核心持仓', 'W15', text(core['标的'] || core.name, '核心持仓') + ' ' + signedPct(core.today_pnl_pct != null ? core.today_pnl_pct : core.total_pnl_pct) + ' / 仓位 ' + positionPctText, 'neutral'));
    }
    actionQueue.push(action('Q' + (actionQueue.length + 1), '核对市场温度', 'W04', '情绪 ' + situation.sentiment.text + ' / ' + phase.label, 'neutral'));

    return {
      generated_at: rt.now,
      situation: situation,
      command: command,
      phase: phase,
      gates: gates,
      action_queue: actionQueue.slice(0, 5),
      evidence: evidence,
      alerts: alerts,
      risks: risks
    };
  }

  var api = { build: build };
  root.EvidenceSummary = api;
  if (root.window) root.window.EvidenceSummary = api;
  if (typeof globalThis !== 'undefined') globalThis.EvidenceSummary = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
