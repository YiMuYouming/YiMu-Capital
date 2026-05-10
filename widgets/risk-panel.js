// widgets/risk-panel.js — W14 账户风控 (v2.1 补全字段)
'use strict';

class RiskPanelWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var R = (data && data.risk) || {};

    var dayPnl = parseFloat(R['当日盈亏']) || 0;
    var dayAmt = parseFloat(R['当日盈亏金额']) || 0;
    var weekDD = parseFloat(R['周累计回撤']) || 0;
    var monthDD = parseFloat(R['月累计回撤']) || 0;
    var loseDays = parseInt(R['连亏天数']) || 0;
    var meltdown = R['熔断触发'];
    var weekHit = R['周回撤触发'];

    function pctStr(v) { return (v != null ? (v > 0 ? '+' : '') + v.toFixed(2) + '%' : '—'); }

    var html = '';

    // 当日盈亏
    var pnlCls = dayPnl > 0 ? 'up' : dayPnl < 0 ? 'down' : '';
    html += '<div class="kpi-card" style="margin-bottom:var(--sp-sm)">' +
      '<div class="kpi-label">当日盈亏</div>' +
      '<div class="kpi-value ' + pnlCls + '" style="font-size:18px">' + pctStr(R['当日盈亏']) + '</div>' +
      '<div class="kpi-verdict ' + pnlCls + '">' + (dayAmt !== 0 ? (dayAmt/10000).toFixed(2) + '万' : '') + '</div>' +
      '</div>';

    // 周回撤 + 进度条
    var wCls = weekDD > 6 ? 'danger' : weekDD > 3 ? 'warn' : 'info';
    html += '<div class="kpi-card" style="margin-bottom:var(--sp-sm)">' +
      '<div class="kpi-label">周累计回撤</div>' +
      '<div class="kpi-value ' + wCls + '" style="font-size:16px">' + pctStr(R['周累计回撤']) + '</div>' +
      '<div class="progress-bar" style="margin-top:2px"><div class="progress-fill ' + wCls + '" style="width:' + Math.min(100, weekDD/10*100) + '%"></div></div>' +
      '</div>';

    // 月回撤 + 进度条
    var mCls = monthDD > 10 ? 'danger' : monthDD > 5 ? 'warn' : 'info';
    html += '<div class="kpi-card" style="margin-bottom:var(--sp-sm)">' +
      '<div class="kpi-label">月累计回撤</div>' +
      '<div class="kpi-value ' + mCls + '" style="font-size:16px">' + pctStr(R['月累计回撤']) + '</div>' +
      '<div class="progress-bar" style="margin-top:2px"><div class="progress-fill ' + mCls + '" style="width:' + Math.min(100, monthDD/15*100) + '%"></div></div>' +
      '</div>';

    // 连亏天数
    var lCls = loseDays >= 2 ? 'danger' : 'info';
    html += '<div class="kpi-card" style="margin-bottom:var(--sp-sm)">' +
      '<div class="kpi-label">连亏天数</div>' +
      '<div class="kpi-value ' + lCls + '" style="font-size:16px">' + loseDays + '天</div>' +
      (loseDays >= 2 ? '<div class="kpi-verdict danger">⚠️ 触发空仓</div>' : '') +
      '</div>';

    // 单日熔断
    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-sm)">' +
      '<div class="kpi-card"><div class="kpi-label">单日熔断</div>' +
      '<div class="kpi-value" style="font-size:14px;color:' + (meltdown ? 'var(--danger)' : 'var(--info)') + '">' + (R['单日熔断线'] != null ? R['单日熔断线'] + '%' : '—') + '</div>' +
      '<div class="kpi-verdict ' + (meltdown ? 'danger' : 'info') + '">' + (meltdown ? '⚠️ 已触发' : '✅ 安全') + '</div></div>' +
      // 周回撤预警
      '<div class="kpi-card"><div class="kpi-label">周回撤预警</div>' +
      '<div class="kpi-value" style="font-size:14px;color:' + (weekHit ? 'var(--danger)' : 'var(--info)') + '">' + (R['周回撤预警'] != null ? R['周回撤预警'] + '%' : '—') + '</div>' +
      '<div class="kpi-verdict ' + (weekHit ? 'danger' : 'info') + '">' + (weekHit ? '⚠️ 已触发' : '✅ 安全') + '</div></div>' +
      '</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W14', RiskPanelWidget);
