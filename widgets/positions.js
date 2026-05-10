// widgets/positions.js — W15 持仓明细 (v2.1 补清仓记录)
'use strict';

class PositionsWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var P = (data && data.positions) || [];

    if (!P.length) {
      body.innerHTML = '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-secondary)">当前空仓</div>';
      this.updateTimestamp();
      return;
    }

    // 拆分活跃持仓和清仓记录
    var active = [], cleared = [];
    P.forEach(function(p) {
      var s = p['状态'] || '';
      if (s.indexOf('清仓') >= 0 || s.indexOf('卖出') >= 0 || s.indexOf('已清') >= 0) {
        cleared.push(p);
      } else {
        active.push(p);
      }
    });

    var html = '';

    // 活跃持仓表格
    if (active.length) {
      html += '<table class="data-table"><thead><tr>' +
        '<th>标的</th><th>方向</th><th>成本</th><th>现价</th><th>浮盈%</th><th>止损</th><th>状态</th>' +
        '</tr></thead><tbody>';
      active.forEach(function(pos) {
        var fp = parseFloat(pos['浮盈']) || 0;
        var fpCls = fp > 0 ? 'up' : fp < 0 ? 'down' : '';
        html += '<tr>' +
          '<td><strong>' + (pos['标的'] || '—') + '</strong> <span style="font-size:var(--fs-label);color:var(--text-disabled)">' + (pos['代码'] || '') + '</span></td>' +
          '<td>' + (pos['方向'] || '—') + '</td>' +
          '<td>' + (pos['成本'] || '—') + '</td>' +
          '<td>' + (pos['现价'] || '—') + '</td>' +
          '<td class="' + fpCls + '">' + (fp !== 0 ? (fp > 0 ? '+' : '') + fp.toFixed(2) + '%' : '0.00%') + '</td>' +
          '<td>' + (pos['止损'] || '—') + '</td>' +
          '<td>' + (pos['状态'] || '持有') + '</td>' +
          '</tr>';
      });
      html += '</tbody></table>';
    } else {
      html += '<div style="padding:var(--sp-sm);text-align:center;color:var(--text-secondary);font-size:var(--fs-body)">当前无活跃持仓</div>';
    }

    // 清仓记录
    if (cleared.length) {
      html += '<div style="margin-top:var(--sp-md);padding-top:var(--sp-sm);border-top:1px solid var(--border-light)">' +
        '<div class="kpi-label" style="margin-bottom:var(--sp-sm)">清仓记录</div>';
      cleared.forEach(function(p) {
        var pl = parseFloat(p['盈亏']) || 0;
        var plCls = pl > 0 ? 'up' : pl < 0 ? 'down' : '';
        var sellPrice = p['卖出价'] || '—';
        html += '<div style="padding:var(--sp-sm);margin-bottom:var(--sp-xs);background:var(--bg-base);border-radius:var(--radius-sm);font-size:var(--fs-body)">' +
          '<strong>' + (p['标的'] || '') + '</strong> <span class="tag tag-sell" style="background:var(--danger-bg);color:var(--danger)">' + (p['状态'] || '已清') + '</span> ' +
          '<span style="color:var(--text-secondary)">成本 ' + (p['成本'] || '—') + ' → 卖出 ' + sellPrice + '</span> ' +
          '<span class="' + plCls + '" style="font-weight:600">' + (pl !== 0 ? (pl > 0 ? '+' : '') + pl.toFixed(2) + '%' : '0.00%') + '</span>' +
          (p['清仓原因'] ? '<div style="color:var(--text-secondary);font-size:var(--fs-label);margin-top:2px">' + p['清仓原因'] + '</div>' : '') +
          '</div>';
      });
      html += '</div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W15', PositionsWidget);
