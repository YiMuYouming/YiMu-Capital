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

    var positionPctText = pnl.pos_pct == null
      ? (num(pnl.mv) !== null && num(pnl.total_asset) ? (num(pnl.mv) / num(pnl.total_asset) * 100).toFixed(1) + '%' : '—')
      : num(pnl.pos_pct).toFixed(1) + '%';

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
    var blocks = Array.isArray(rule.blocks) ? rule.blocks : [];
    if (!rt.healthConfirmed) {
      risks.push({ id: 'R1', title: '状态未确认', detail: '健康门禁未确认前不显示可交易', source: sourceLabel('rule_state/api_health'), tone: 'danger' });
    } else if (!tradeAllowed || blocks.length) {
      risks.push({ id: 'R1', title: '交易阻断', detail: blocks.length ? text(blocks[0].message || blocks[0].code, '规则阻断') : '交易入口被健康门禁关闭', source: sourceLabel('rule_state/api_health'), tone: 'danger' });
    } else {
      risks.push({ id: 'R1', title: '交易入口允许', detail: '未发现关键阻断', source: sourceLabel('rule_state/api_health'), tone: 'neutral' });
    }
    var cap = rule.caps && rule.caps.total_pct;
    risks.push({ id: 'R2', title: '仓位上限', detail: cap == null ? '仓位上限不可用' : '当前规则仓位上限 ' + cap + '%', source: sourceLabel('rule_state'), tone: cap === 0 ? 'danger' : 'neutral' });

    return { generated_at: rt.now, situation: situation, evidence: evidence, alerts: alerts, risks: risks };
  }

  var api = { build: build };
  root.EvidenceSummary = api;
  if (root.window) root.window.EvidenceSummary = api;
  if (typeof globalThis !== 'undefined') globalThis.EvidenceSummary = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
