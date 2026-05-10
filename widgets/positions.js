// widgets/positions.js — W15 持仓明细
'use strict';

class PositionsWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var P = (data && data.positions) || [];

    if (!P.length) {
      body.innerHTML = '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-secondary)">当前空仓</div>';
      return;
    }

    var html = '<table class="data-table"><thead><tr>' +
      '<th>标的</th><th>方向</th><th>成本</th><th>现价</th><th>浮盈%</th><th>止损</th><th>状态</th>' +
      '</tr></thead><tbody>';

    P.forEach(function(pos) {
      var fpCls = (pos['浮盈']||0) > 0 ? 'up' : (pos['浮盈']||0) < 0 ? 'down' : '';
      html += '<tr>' +
        '<td>'+(pos['标的']||'—')+' <span style="font-size:var(--fs-label);color:var(--text-disabled)">'+(pos['代码']||'')+'</span></td>' +
        '<td>'+(pos['方向']||'—')+'</td>' +
        '<td>'+(pos['成本']||'—')+'</td>' +
        '<td>'+(pos['现价']||'—')+'</td>' +
        '<td class="'+fpCls+'">'+(pos['浮盈']!=null?(pos['浮盈']>0?'+':'')+pos['浮盈']+'%':'—')+'</td>' +
        '<td>'+(pos['止损']||'—')+'</td>' +
        '<td>'+(pos['状态']||'—')+'</td>' +
        '</tr>';
    });
    html += '</tbody></table>';
    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W15', PositionsWidget);
