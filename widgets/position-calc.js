// widgets/position-calc.js — W03 三层仓位计 (v2.2 可用资金+规则更新)
'use strict';

class PositionCalcWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var ST = (data && data.style) || {};
    var R = (data && data.risk) || {};

    var totalCap = ST['总仓位上限'] || 0;
    var lbPct = ST['连板占比'] || 0;
    var trPct = ST['趋势占比'] || 0;
    var exec = ST['实际执行'] || {};
    var lbActual = exec['连板实际'] != null ? exec['连板实际'] : lbPct;
    var trActual = exec['趋势实际'] != null ? exec['趋势实际'] : trPct;
    var execReason = exec['原因'] || '';
    var execReason2 = exec['原因2'] || '';

    // 第一层：仓位锁定检查
    var meltdown = R['熔断触发'];
    var loseStreak = R['连亏天数'] || 0;
    var weekDrawdown = parseFloat(R['周累计回撤']) || 0;

    var blocked = false;
    var blockReasons = [];
    if (meltdown) { blocked = true; blockReasons.push('单日熔断-3%'); }
    if (loseStreak >= 2) { blocked = true; blockReasons.push('连亏'+loseStreak+'天'); }
    if (weekDrawdown >= 6) { blocked = true; blockReasons.push('周回撤'+weekDrawdown+'%≥6%'); }

    var html = '';

    // ===== Layer 1: 总仓位上限 =====
    var manual = DataStore.manualData.getAll();
    // 总资产来源链：W16 手动录入 → pnl 基线（含真实总资产）
    var totalCapital = parseFloat(manual['总资产'])
                    || parseFloat((data.pnl||{})['总资产'])
                    || 0;
    // 已持仓市值：从实际持仓（状态=持有，排除清仓/删除）实时计算
    var currentPosVal = 0;
    (data.positions||[]).forEach(function(p){
      var s = String(p['状态']||'');
      if (s && s.indexOf('持有') >= 0 && s.indexOf('清') < 0 && s.indexOf('删') < 0) {
        currentPosVal += Math.round((parseFloat(p['数量'])||0)*(parseFloat(p['现价'])||parseFloat(p['成本'])||0));
      }
    });
    var availCash = parseFloat(manual['可用资金'])
                 || parseFloat((data.pnl||{})['可用资金'])
                 || (totalCapital - currentPosVal);
    var currentPosPct = totalCapital > 0 ? Math.round(currentPosVal / totalCapital * 100) : 0;
    var maxPosition = Math.round(totalCapital * (totalCap||0) / 100);
    var availPct = Math.max(0, totalCap - currentPosPct);

    var l1Val = blocked ? 0 : totalCap;
    html += '<div class="layer-row' + (blocked?' layer-blocked':'') + '">' +
      '<span class="layer-label">第一层</span>' +
      '<span class="layer-value ' + (blocked?'danger':'info') + '">' + (blocked?'0':totalCap) + '%</span>' +
      '<span class="layer-reason">上限' + totalCap + '%' +
        ' | 已持<span style=\"color:var(--warn)\">' + currentPosPct + '%</span>' +
        ' | 可用<span style=\"color:var(--up)\">' + availPct + '%</span>' +
        (blocked?' — ' + blockReasons.join('、') + '→空仓' : '') +
      '</span></div>';

    // ===== Layer 2: 风格分配 =====
    var styleNote = execReason2 || execReason || '';
    if (lbPct === 0 && trPct === 0) styleNote = '风格未检测';
    html += '<div class="layer-row' + (blocked?' layer-blocked':'') + '">' +
      '<span class="layer-label">第二层</span>' +
      '<span class="layer-value up">' + (blocked?'0':lbActual) + '%</span>' +
      '<span class="layer-value down" style="margin-left:var(--sp-sm)">' + (blocked?'0':trActual) + '%</span>' +
      '<span class="layer-reason">连板 | 趋势' + (styleNote ? ' — ' + styleNote : '') + '</span></div>';

    // ===== Layer 3: W1/W2 窗口 =====
    var w1Open = !blocked && lbActual > 0;
    var w2Open = !blocked && trActual > 0;
    html += '<div class="layer-row' + (blocked?' layer-blocked':'') + '">' +
      '<span class="layer-label">第三层</span>' +
      '<span class="layer-value ' + (w1Open?'up':'text-disabled') + '" style="font-size:var(--fs-body)">W1 ' + (w1Open?'追涨/回踩':'关闭') + '</span>' +
      '<span class="layer-value ' + (w2Open?'down':'text-disabled') + '" style="font-size:var(--fs-body);margin-left:var(--sp-sm)">W2 ' + (w2Open?'低吸/回踩':'关闭') + '</span>' +
      '<span class="layer-reason">' +
        (blocked?'仓位锁定':(lbActual>0&&trActual>0?'双策略并行':(lbActual>0?'纯连板':'纯趋势'))) +
      '</span></div>';

    // ===== 金额计算（规则: 总资金 × 总仓位上限% × 侧占比%）=====
    var maxPosition = Math.round(totalCapital * (totalCap||0) / 100);
    // 可新开 = 总仓位上限 - 已持仓（不能为负）
    var newCap = Math.max(0, maxPosition - currentPosVal);
    // 分配
    var lbMoney = blocked ? 0 : Math.round(newCap * lbActual / 100);
    var trMoney = blocked ? 0 : Math.round(newCap * trActual / 100);
    var sumMoney = lbMoney + trMoney;

    html += '<div style="margin-top:var(--sp-sm);padding:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-sm)">' +
      '<div style="font-size:var(--fs-label);color:var(--text-disabled);margin-bottom:var(--sp-xs)">'+
        '总仓位上限'+totalCap+'% = '+maxPosition.toLocaleString()+' | 已持仓'+currentPosVal.toLocaleString()+' | 可新开'+newCap.toLocaleString()+'</div>'+
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px">' +
        '<div><span style="font-size:var(--fs-body);color:var(--text-secondary)">连板可新开</span>' +
        '<div style="font-size:var(--fs-label);color:var(--text-disabled)">可新开'+newCap.toLocaleString()+'×'+lbActual+'%</div></div>' +
        '<span style="font-family:var(--font-mono);font-size:var(--fs-body);font-weight:600;color:var(--up)">'+(lbMoney>0?lbMoney.toLocaleString():'0')+'</span>' +
      '</div>' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">' +
        '<div><span style="font-size:var(--fs-body);color:var(--text-secondary)">趋势可新开</span>' +
        '<div style="font-size:var(--fs-label);color:var(--text-disabled)">可新开'+newCap.toLocaleString()+'×'+trActual+'%</div></div>' +
        '<span style="font-family:var(--font-mono);font-size:var(--fs-body);font-weight:600;color:var(--down)">'+(trMoney>0?trMoney.toLocaleString():'0')+'</span>' +
      '</div>' +
      '<div style="border-top:1px solid var(--border-light);padding-top:4px;display:flex;justify-content:space-between;align-items:center">' +
        '<span style="font-size:var(--fs-body);font-weight:600">可新开合计</span>' +
        '<span style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700;color:'+(blocked?'var(--danger)':'var(--info)')+'">'+sumMoney.toLocaleString()+'</span>' +
      '</div></div>';

    // 备注
    var notes = [];
    if (blockReasons.length) notes.push('仓位锁定：'+blockReasons.join('、'));
    if (styleNote && !blockReasons.length) notes.push('风格：'+styleNote);
    if (totalCap) notes.push('总仓位上限'+totalCap+'%');
    if (lbActual+trActual < 100) notes.push('有效仓位'+(lbActual+trActual)+'%（'+(100-lbActual-trActual)+'%预留）');
    if (notes.length) {
      html += '<div style="margin-top:var(--sp-xs);padding:var(--sp-xs) var(--sp-sm);font-size:var(--fs-body);color:var(--text-secondary);line-height:1.5">' +
        '<span style="color:var(--text-disabled)">备注：</span>' + notes.join('；') + '</div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W03', PositionCalcWidget);
