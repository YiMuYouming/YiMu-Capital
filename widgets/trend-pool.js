// widgets/trend-pool.js — W13 趋势自选池
'use strict';

class TrendPoolWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var pool = (data && data.trend_pool) || [];

    if (!pool.length) {
      body.innerHTML = '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled)">趋势池数据未录入</div>';
      return;
    }

    var cols = ['标的','板块','角色','操作','买点','涨幅','最新价','MA5','MA20','量比','换手','备注'];
    var keys = ['标的','板块','角色','操作','买点','涨幅','最新价','MA5','MA20','量比','换手','备注'];

    var html = '<table class="data-table"><thead><tr>';
    cols.forEach(function(c) { html += '<th>'+c+'</th>'; });
    html += '</tr></thead><tbody>';

    pool.forEach(function(s) {
      html += '<tr>';
      keys.forEach(function(key, i) {
        var val = s[key] != null ? s[key] : '—';
        var cls = '';
        if (key === '涨幅') {
          var str = String(val);
          cls = str.charAt(0) === '+' ? 'up' : str.charAt(0) === '-' ? 'down' : '';
        }
        if (key === '操作' && String(val).indexOf('买入') >= 0) cls = 'down';
        html += '<td class="' + cls + '">' + val + (i === 0 ? ' <span style="font-size:var(--fs-label);color:var(--text-disabled)">'+(s['代码']||'')+'</span>' : '') + '</td>';
      });
      html += '</tr>';
    });

    html += '</tbody></table>';
    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W13', TrendPoolWidget);
