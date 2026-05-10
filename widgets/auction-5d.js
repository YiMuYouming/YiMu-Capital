// widgets/auction-5d.js — W06 竞价5维面板 (v2.0: 统一竞价情绪值路径)
'use strict';

class Auction5DWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var d = (data && data.decision) || {};
    var auction = d['竞价'] || {};

    if (!auction['结论']) {
      body.innerHTML = '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled)">竞价数据未录入</div>';
      return;
    }

    var lightMap = {green:'info',orange:'warn',red:'danger'};
    function light(cls) { return lightMap[cls] || 'warn'; }

    var html = '';

    // Conclusion banner
    html += '<div style="padding:var(--sp-sm);margin-bottom:var(--sp-md);background:var(--bg-base);border-radius:var(--radius-md);text-align:center">' +
      '<div style="font-size:var(--fs-hero);font-weight:700;color:var(--'+(auction['结论'].indexOf('偏多')>=0?'up':'warn')+')">'+auction['结论']+'</div>' +
      '<div style="margin-top:var(--sp-xs);font-size:var(--fs-body);color:var(--text-secondary)">' +
      '高潮保护: '+(auction['高潮保护']||'—')+' | '+(auction['动作']||'')+'</div>' +
      '</div>';

    // 5-column grid
    html += '<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:var(--sp-sm)">';

    // Col 1: 大盘指数
    html += '<div><div class="kpi-label" style="text-align:left">大盘指数</div>';
    (auction['大盘指数']||[]).forEach(function(idx) {
      html += '<div style="font-size:var(--fs-body);padding:1px 0"><span>'+idx['指数']+'</span> <span class="'+light(idx['灯'])+'">'+idx['竞价涨幅']+'</span>' +
        '<br><span style="font-size:var(--fs-micro)">涨<span style="color:var(--up)">'+(idx['涨家']||'—')+'</span> 跌<span style="color:var(--down)">'+(idx['跌家']||'—')+'</span></span></div>';
    });
    html += '</div>';

    // Col 2: 市场情绪
    html += '<div><div class="kpi-label" style="text-align:left">市场情绪</div>';
    (auction['市场情绪']||[]).forEach(function(s) {
      html += '<div style="font-size:var(--fs-body);padding:1px 0">'+s['名称']+': <span class="'+light(s['灯'])+'">'+s['值']+'</span></div>';
    });
    html += '</div>';

    // Col 3: 高标竞价
    html += '<div><div class="kpi-label" style="text-align:left">高标竞价</div>';
    (auction['高标竞价']||[]).forEach(function(g) {
      html += '<div style="font-size:var(--fs-body);padding:1px 0">'+g['名称']+': <span class="'+light(g['灯'])+'">'+g['竞价']+'</span></div>';
    });
    html += '</div>';

    // Col 4: 方向锚定
    html += '<div><div class="kpi-label" style="text-align:left">方向锚定</div>';
    (auction['方向锚定']||[]).forEach(function(fx) {
      html += '<div style="font-size:var(--fs-body);padding:1px 0">'+fx['板块']+': <span class="'+light(fx['灯'])+'">'+fx['竞价']+'</span></div>';
    });
    html += '</div>';

    // Col 5: 锚定股竞价
    html += '<div><div class="kpi-label" style="text-align:left">锚定股竞价</div>';
    (auction['锚定股竞价']||[]).forEach(function(mao) {
      html += '<div style="font-size:var(--fs-body);padding:1px 0">'+mao['标的']+': <span class="'+light(mao['灯'])+'">'+mao['竞价']+'</span></div>';
    });
    html += '</div>';

    html += '</div>';
    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W06', Auction5DWidget);
