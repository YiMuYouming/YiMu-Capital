// widgets/position-calc.js — W03 三层仓位计 (v2.0: 订阅 risk.熔断触发 + risk.连亏天数)
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
    var firstLimit = exec['首笔上限'] || '—';

    var meltdown = R['熔断触发'];
    var loseStreak = R['连亏天数'] || 0;

    // 熔断/连亏覆盖
    var blocked = false;
    var blockReason = '';
    if (meltdown) { blocked = true; blockReason = '熔断触发，仓位归零'; }
    else if (loseStreak >= 2) { blocked = true; blockReason = '连亏' + loseStreak + '天，强制空仓'; }

    var html = '';

    // Layer 1
    html += '<div class="layer-row' + (blocked?' layer-blocked':'') + '">' +
      '<span class="layer-label">第一层</span>' +
      '<span class="layer-value ' + (blocked?'danger':'info') + '">' + (blocked?'0':totalCap) + '%</span>' +
      '<span class="layer-reason">总仓位上限' + (blocked?' — '+blockReason:'') + '</span>' +
      '</div>';

    // Layer 2
    html += '<div class="layer-row' + (blocked?' layer-blocked':'') + '">' +
      '<span class="layer-label">第二层</span>' +
      '<span class="layer-value up">' + (blocked?'0%':lbActual+'%') + '</span>' +
      '<span class="layer-value down" style="margin-left:var(--sp-sm)">' + (blocked?'0%':trActual+'%') + '</span>' +
      '<span class="layer-reason">连板 | 趋势</span>' +
      '</div>';

    // Layer 3
    html += '<div class="layer-row' + (blocked?' layer-blocked':'') + '">' +
      '<span class="layer-label">第三层</span>' +
      '<span class="layer-value">W1/W2</span>' +
      '<span class="layer-reason">首笔上限: ' + firstLimit + '%</span>' +
      '</div>';

    // Actual capital
    var totalCapital = 1000000; // placeholder
    var actualMoney = blocked ? 0 : Math.round(totalCapital * totalCap / 100 * Math.max(lbActual, trActual) / 100);
    html += '<div style="margin-top:var(--sp-sm);padding:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-sm);text-align:center">' +
      '<span style="font-size:var(--fs-label);color:var(--text-secondary)">实际可用</span><br>' +
      '<span style="font-family:var(--font-mono);font-size:var(--fs-kpi);font-weight:700;color:' + (blocked?'var(--danger)':'var(--info)') + '">' +
      (blocked?'—':actualMoney.toLocaleString()) + '</span>' +
      '</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W03', PositionCalcWidget);
