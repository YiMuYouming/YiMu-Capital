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
    var execReason = exec['原因'] || '';
    var execReason2 = exec['原因2'] || '';

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

    // 从报数面板读总资产（万元），默认 100 万
    var manual = DataStore.manualData.getAll();
    var totalAsset = parseFloat(manual['总资产']) || 100; // 万元
    var totalCapital = totalAsset * 10000; // 转为元
    // 连板/趋势占比是总资产的%，直接乘
    var lbMoney = blocked ? 0 : Math.round(totalCapital * lbActual / 100);
    var trMoney = blocked ? 0 : Math.round(totalCapital * trActual / 100);
    var sumMoney = lbMoney + trMoney;

    html += '<div style="margin-top:var(--sp-sm);padding:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-sm)">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px">' +
        '<div><span style="font-size:var(--fs-body);color:var(--text-secondary)">连板可用</span>' +
        '<div style="font-size:var(--fs-label);color:var(--text-disabled)">' + (totalAsset*10000).toLocaleString() + '×' + lbActual + '%</div></div>' +
        '<span style="font-family:var(--font-mono);font-size:var(--fs-body);font-weight:600;color:var(--up)">' + (lbMoney > 0 ? lbMoney.toLocaleString() : '0') + '</span>' +
      '</div>' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">' +
        '<div><span style="font-size:var(--fs-body);color:var(--text-secondary)">趋势可用</span>' +
        '<div style="font-size:var(--fs-label);color:var(--text-disabled)">' + (totalAsset*10000).toLocaleString() + '×' + trActual + '%</div></div>' +
        '<span style="font-family:var(--font-mono);font-size:var(--fs-body);font-weight:600;color:var(--down)">' + (trMoney > 0 ? trMoney.toLocaleString() : '0') + '</span>' +
      '</div>' +
      '<div style="border-top:1px solid var(--border-light);padding-top:4px;display:flex;justify-content:space-between;align-items:center">' +
        '<span style="font-size:var(--fs-body);font-weight:600">合计</span>' +
        '<span style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700;color:' + (blocked?'var(--danger)':'var(--info)') + '">' + sumMoney.toLocaleString() + '</span>' +
      '</div>' +
      '</div>';

    // 备注：硬卡/熔断/周五原因
    var notes = [];
    if (execReason) notes.push(execReason);
    if (execReason2) notes.push(execReason2);
    if (notes.length) {
      html += '<div style="margin-top:var(--sp-xs);padding:var(--sp-xs) var(--sp-sm);font-size:var(--fs-body);color:var(--text-secondary);line-height:1.5">' +
        '<span style="color:var(--text-disabled)">备注：</span>' + notes.join('；') +
        '</div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W03', PositionCalcWidget);
