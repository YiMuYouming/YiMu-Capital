// widgets/risk-panel.js — W14 账户风控
'use strict';

class RiskPanelWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var R = (data && data.risk) || {};

    function riskColor(val, thresholds) {
      if (val == null) return '';
      if (thresholds && val >= thresholds[1]) return 'danger';
      if (thresholds && val >= thresholds[0]) return 'warn';
      return 'info';
    }

    var items = [
      {label:'当日盈亏', val:(R['当日盈亏']!=null?R['当日盈亏']+'%':'—'), cls:(R['当日盈亏']>0?'up':R['当日盈亏']<0?'down':''), sub:(R['当日盈亏金额']!=null?R['当日盈亏金额']:'')},
      {label:'周累计回撤', val:(R['周累计回撤']!=null?R['周累计回撤']+'%':'—'), cls:riskColor(R['周累计回撤'],[3,6])},
      {label:'月累计回撤', val:(R['月累计回撤']!=null?R['月累计回撤']+'%':'—'), cls:riskColor(R['月累计回撤'],[6,10])},
      {label:'连亏天数', val:(R['连亏天数']!=null?R['连亏天数']+'天':'—'), cls:(R['连亏天数']>=2?'danger':'info')},
      {label:'单日熔断', val:(R['单日熔断线']!=null?R['单日熔断线']+'%':'—'), cls:(R['熔断触发']?'danger':'info'), sub:(R['熔断触发']?'⚠️ 已触发':'✅ 安全')},
      {label:'周回撤', val:(R['周回撤预警']!=null?R['周回撤预警']+'%':'—'), cls:(R['周回撤触发']?'danger':'info'), sub:(R['周回撤触发']?'⚠️ 已触发':'✅ 安全')},
    ];

    var html = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-sm)">';
    items.forEach(function(item) {
      html += '<div class="kpi-card">' +
        '<div class="kpi-label">' + item.label + '</div>' +
        '<div class="kpi-value ' + (item.cls||'') + '" style="font-size:16px">' + item.val + '</div>' +
        (item.sub ? '<div class="kpi-verdict ' + (item.cls||'') + '">' + item.sub + '</div>' : '') +
        '</div>';
    });
    html += '</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W14', RiskPanelWidget);
