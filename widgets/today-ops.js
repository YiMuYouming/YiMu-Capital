// widgets/today-ops.js — W17 今日操作记录 (v2.1 新增)
'use strict';

class TodayOpsWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var ops = (data && data.decision && data.decision['今日操作']) || [];

    if (!ops.length) {
      body.innerHTML = '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled)">今日无操作</div>';
      this.updateTimestamp();
      return;
    }

    var html = '<table class="data-table"><thead><tr>' +
      '<th>时间</th><th>动作</th><th>标的</th><th>价格</th><th>盈亏</th><th>原因</th>' +
      '</tr></thead><tbody>';

    ops.forEach(function(o) {
      var pl = String(o['盈亏'] || '');
      var plCls = pl.indexOf('+') >= 0 ? 'up' : pl.indexOf('-') >= 0 ? 'down' : '';
      html += '<tr>' +
        '<td>' + (o['时间'] || '—') + '</td>' +
        '<td><span class="tag" style="background:var(--danger-bg);color:var(--danger)">' + (o['动作'] || '—') + '</span></td>' +
        '<td><strong>' + (o['标的'] || '—') + '</strong></td>' +
        '<td>' + (o['价格'] || '—') + '</td>' +
        '<td class="' + plCls + '" style="font-weight:600">' + pl + '</td>' +
        '<td style="font-size:var(--fs-label);color:var(--text-secondary);max-width:120px;white-space:normal">' + (o['原因'] || '') + '</td>' +
        '</tr>';
    });

    html += '</tbody></table>';
    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W17', TodayOpsWidget);
