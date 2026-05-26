// widgets/position-calc.js — W03 三层仓位计 (v3.0 rule_state 驱动)
'use strict';

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
    var firstEntryPct = rsCaps.first_entry_pct != null ? rsCaps.first_entry_pct : 10;

    // 全局阻断：tradable=false 或 scope=all 的 blocks
    var globallyBlocked = RS ? !RS.tradable : false;
    var allScopeCodes = rsBlocks.filter(function(b){ return b.scope === 'all'; })
                               .map(function(b){ return b.code; });
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

    // ===== Layer 1: 总仓位上限 =====
    var l1Val = globallyBlocked ? 0 : totalCap;
    var l1Color = globallyBlocked ? 'danger' : 'info';
    html += '<div class="layer-row' + (globallyBlocked?' layer-blocked':'') + '">' +
      '<span class="layer-label">第一层</span>' +
      '<span class="layer-value ' + l1Color + '">' + l1Val + '%</span>' +
      '<span class="layer-reason">上限' + totalCap + '%' +
        ' | 基础' + baseCap + '%' +
        (globallyBlocked ? ' — ' + allScopeCodes.join('、') + '→空仓' : '') +
        (rsBlocks.length && !globallyBlocked ? ' — ' + blockReasons.join('；') : '') +
      '</span></div>';

    // ===== Layer 2: 风格分配 =====
    html += '<div class="layer-row' + (globallyBlocked?' layer-blocked':'') + '">' +
      '<span class="layer-label">第二层</span>' +
      '<span class="layer-value up">' + (globallyBlocked?'0':lbPct) + '%</span>' +
      '<span class="layer-value down" style="margin-left:var(--sp-sm)">' + (globallyBlocked?'0':trPct) + '%</span>' +
      '<span class="layer-reason">连板 | 趋势' +
        ' | 首笔上限' + firstEntryPct + '%</span></div>';

    // ===== Layer 3: W1/W2 窗口 =====
    var w1 = rsWindows.w1 || {};
    var w2 = rsWindows.w2 || {};
    var w1Open = w1.buy_allowed;
    var w2Open = w2.buy_allowed;
    var w1Label = w1.buy_allowed ? '追涨/回踩' : ('关闭' + (w1.in_session ? '' : '（非W1）'));
    var w2Label = w2.buy_allowed ? '低吸/回踩' : ('关闭' + (w2.in_session ? '' : '（非W2）'));
    html += '<div class="layer-row' + (globallyBlocked?' layer-blocked':'') + '">' +
      '<span class="layer-label">第三层</span>' +
      '<span class="layer-value ' + (w1Open?'up':'text-disabled') + '" style="font-size:var(--fs-body)">W1 ' + w1Label + '</span>' +
      '<span class="layer-value ' + (w2Open?'down':'text-disabled') + '" style="font-size:var(--fs-body);margin-left:var(--sp-sm)">W2 ' + w2Label + '</span>' +
      '<span class="layer-reason">W1:' + (w1.in_session?'盘中':'休') + ' W2:' + (w2.in_session?'盘中':'休') +
        (w1.blocks && w1.blocks.length ? ' W1阻断:' + w1.blocks.join(',') : '') +
        (w2.blocks && w2.blocks.length ? ' W2阻断:' + w2.blocks.join(',') : '') +
      '</span></div>';

    // ===== 金额计算 =====
    var newCap = Math.max(0, maxPosition - currentPosVal);
    var lbMoney = globallyBlocked ? 0 : Math.round(newCap * lbPct / 100);
    var trMoney = globallyBlocked ? 0 : Math.round(newCap * trPct / 100);
    var sumMoney = lbMoney + trMoney;

    html += '<div style="margin-top:var(--sp-sm);padding:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-sm)">' +
      '<div style="font-size:var(--fs-label);color:var(--text-disabled);margin-bottom:var(--sp-xs)">'+
        '总仓位上限'+totalCap+'% = '+maxPosition.toLocaleString()+' | 已持仓'+currentPosVal.toLocaleString()+' | 可新开'+newCap.toLocaleString()+'</div>'+
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px">' +
        '<div><span style="font-size:var(--fs-body);color:var(--text-secondary)">连板可新开</span>' +
        '<div style="font-size:var(--fs-label);color:var(--text-disabled)">可新开'+newCap.toLocaleString()+'×'+lbPct+'%</div></div>' +
        '<span style="font-family:var(--font-mono);font-size:var(--fs-body);font-weight:600;color:var(--up)">'+(lbMoney>0?lbMoney.toLocaleString():'0')+'</span>' +
      '</div>' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">' +
        '<div><span style="font-size:var(--fs-body);color:var(--text-secondary)">趋势可新开</span>' +
        '<div style="font-size:var(--fs-label);color:var(--text-disabled)">可新开'+newCap.toLocaleString()+'×'+trPct+'%</div></div>' +
        '<span style="font-family:var(--font-mono);font-size:var(--fs-body);font-weight:600;color:var(--down)">'+(trMoney>0?trMoney.toLocaleString():'0')+'</span>' +
      '</div>' +
      '<div style="border-top:1px solid var(--border-light);padding-top:4px;display:flex;justify-content:space-between;align-items:center">' +
        '<span style="font-size:var(--fs-body);font-weight:600">可新开合计</span>' +
        '<span style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700;color:'+(globallyBlocked?'var(--danger)':'var(--info)')+'">'+sumMoney.toLocaleString()+'</span>' +
      '</div></div>';

    // 阻断详情
    if (rsBlocks.length) {
      html += '<div style="margin-top:var(--sp-xs);font-size:var(--fs-body)">';
      rsBlocks.forEach(function(b){ html += '<div style="color:var(--'+(b.scope==='all'?'danger':'warn')+');padding:2px 0"><b>'+b.code+'</b>: '+b.message+'</div>'; });
      html += '</div>';
    }
    if (rsWarnings.length) {
      rsWarnings.forEach(function(w){ html += '<div style="color:var(--warn);font-size:var(--fs-body)">⚠ '+w.message+'</div>'; });
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W03', PositionCalcWidget);
