// widgets/today-ops.js — W17 今日操作（只读展示，数据源 SSOT trade_records）
'use strict';

function _esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

class TodayOpsWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;

    var pnlLive = (data && data.pnl_live) || {};
    var trades = Array.isArray(pnlLive.trades) ? pnlLive.trades : [];

    var html = '';

    if (!trades.length) {
      html += '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled);font-size:var(--fs-body)">今日无操作（请在 W15 持仓组件中记流水）</div>';
      body.innerHTML = html;
      this.updateTimestamp();
      return;
    }

    html += '<table class="data-table"><thead><tr>' +
      '<th>时间</th><th>动作</th><th>标的</th><th>代码</th><th>价格</th><th>数量</th><th>窗口</th><th>原因</th>' +
      '</tr></thead><tbody>';

    trades.forEach(function(t) {
      var act = t.action || '—';
      var isBuy = act.indexOf('买入') >= 0 || act.indexOf('追') >= 0;
      html += '<tr>' +
        '<td style="font-size:var(--fs-body)">' + _esc(t.trade_time) + '</td>' +
        '<td><span class="tag" style="font-size:var(--fs-body);background:var(--' + (isBuy ? 'up-bg' : 'down-bg') + ');color:var(--' + (isBuy ? 'up' : 'down') + ')">' + _esc(act) + '</span></td>' +
        '<td style="font-size:var(--fs-body);font-weight:600">' + _esc(t.name) + '</td>' +
        '<td style="font-size:var(--fs-body);font-family:var(--font-mono);color:var(--text-secondary)">' + _esc(t.code) + '</td>' +
        '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">' + (t.price != null ? Number(t.price).toFixed(2) : '—') + '</td>' +
        '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">' + _esc(String(t.qty || '—')) + '</td>' +
        '<td style="font-size:var(--fs-body)">' + _esc(t.window || '—') + '</td>' +
        '<td style="font-size:var(--fs-body);color:var(--text-secondary);max-width:120px;white-space:normal">' + _esc(t.reason || '') + '</td>' +
        '</tr>';
    });

    html += '</tbody></table>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W17', TodayOpsWidget);
