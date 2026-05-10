// widgets/anchor-stocks.js — W18 锚定股状态 (v2.1 新增)
'use strict';

class AnchorStocksWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var anchors = (data && data.decision && data.decision['锚定股状态']) || [];

    if (!anchors.length) {
      body.innerHTML = '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled)">锚定股数据未录入</div>';
      this.updateTimestamp();
      return;
    }

    var lightMap = {green:'info',red:'danger',orange:'warn'};
    function dot(lamp) { return lamp === 'green' ? '🔵' : lamp === 'red' ? '🔴' : '🟠'; }
    function barColor(lamp) { return lamp === 'green' ? 'var(--info)' : lamp === 'red' ? 'var(--danger)' : 'var(--warn)'; }

    var html = '<div style="display:flex;gap:var(--sp-sm);flex-wrap:wrap">';
    anchors.forEach(function(a) {
      html += '<div style="flex:1;min-width:200px;padding:var(--sp-sm) var(--sp-md);background:var(--bg-base);border-radius:var(--radius-md);border-left:3px solid ' + barColor(a['灯']) + '">' +
        '<div style="font-weight:600;font-size:var(--fs-body)">' + dot(a['灯']) + ' ' + (a['标的'] || '—') + '</div>' +
        '<div style="font-size:var(--fs-label);color:var(--text-secondary);margin-top:2px">' + (a['状态'] || '—') + '</div>' +
        '<div style="font-size:var(--fs-label);color:var(--text-secondary)">→ ' + (a['影响'] || '—') + '</div>' +
        '</div>';
    });
    html += '</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W18', AnchorStocksWidget);
