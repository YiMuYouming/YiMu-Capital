// widgets/auction-5d.js — W06 竞价5维面板
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
    function dot(lamp) { return lamp==='green'?'🔵':lamp==='red'?'🔴':'🟠'; }
    function cls(lamp) { return lightMap[lamp]||'warn'; }
    function chgCls(v) {
      var n = parseFloat(String(v).replace('%',''));
      return isNaN(n) ? '' : n>0?'up':'down';
    }

    var html = '';

    // === 顶部结论条 ===
    var isBull = auction['结论'].indexOf('偏多') >= 0;
    html += '<div style="padding:var(--sp-sm) var(--sp-md);margin-bottom:var(--sp-md);background:var(--bg-base);border-radius:var(--radius-md);border-left:3px solid '+(isBull?'var(--up)':'var(--warn)')+'">' +
      '<div style="display:flex;align-items:baseline;gap:var(--sp-md)">' +
        '<span style="font-size:var(--fs-subtitle);font-weight:700;color:'+(isBull?'var(--up)':'var(--warn)')+'">'+auction['结论']+'</span>' +
        '<span style="font-size:var(--fs-body);color:var(--text-secondary)">高潮保护: '+auction['高潮保护']+'</span>' +
      '</div>' +
      '<div style="margin-top:var(--sp-xs);font-size:var(--fs-body);color:var(--info)">▶ '+(auction['动作']||'')+'</div>' +
      '</div>';

    // === 上排：大盘 + 情绪 ===
    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-md);margin-bottom:var(--sp-md)">';

    // 大盘指数
    html += '<div style="background:var(--bg-base);border-radius:var(--radius-md);padding:var(--sp-sm) var(--sp-md)">' +
      '<div style="font-size:var(--fs-body);font-weight:600;color:var(--text-primary);margin-bottom:var(--sp-sm);padding-bottom:var(--sp-xs);border-bottom:1px solid var(--border-light)">大盘指数</div>';
    (auction['大盘指数']||[]).forEach(function(idx) {
      html += '<div style="display:flex;align-items:center;gap:var(--sp-sm);padding:3px 0;font-size:var(--fs-body)">' +
        '<span>'+dot(idx['灯'])+' <strong>'+idx['指数']+'</strong></span>' +
        '<span style="font-family:var(--font-mono);font-weight:600;color:var(--'+chgCls(idx['竞价涨幅'])+')">'+idx['竞价涨幅']+'</span>' +
        '<span style="font-size:var(--fs-body);color:var(--text-secondary)">涨 <span style="color:var(--up);font-weight:600">'+(idx['涨家']||'—')+'</span> 跌 <span style="color:var(--down);font-weight:600">'+(idx['跌家']||'—')+'</span></span>' +
        '</div>';
    });
    html += '</div>';

    // 市场情绪
    html += '<div style="background:var(--bg-base);border-radius:var(--radius-md);padding:var(--sp-sm) var(--sp-md)">' +
      '<div style="font-size:var(--fs-body);font-weight:600;color:var(--text-primary);margin-bottom:var(--sp-sm);padding-bottom:var(--sp-xs);border-bottom:1px solid var(--border-light)">市场情绪</div>';
    (auction['市场情绪']||[]).forEach(function(s) {
      html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:3px 0;font-size:var(--fs-body)">' +
        '<span>'+dot(s['灯'])+' '+s['名称']+'</span>' +
        '<span style="font-family:var(--font-mono);font-weight:600;color:var(--'+cls(s['灯'])+')">'+s['值']+'</span>' +
        '</div>';
    });
    html += '</div>';

    html += '</div>';

    // === 下排：方向锚定 / 高标竞价 / 锚定股竞价 ===
    html += '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:var(--sp-md)">';

    // 方向锚定
    html += '<div style="background:var(--bg-base);border-radius:var(--radius-md);padding:var(--sp-sm) var(--sp-md)">' +
      '<div style="font-size:var(--fs-body);font-weight:600;color:var(--text-primary);margin-bottom:var(--sp-sm);padding-bottom:var(--sp-xs);border-bottom:1px solid var(--border-light)">方向锚定</div>';
    (auction['方向锚定']||[]).forEach(function(fx) {
      html += '<div style="padding:3px 0;font-size:var(--fs-body)">' +
        '<div style="display:flex;align-items:center;justify-content:space-between">' +
        '<span>'+dot(fx['灯'])+' <strong>'+fx['板块']+'</strong></span>' +
        '<span style="font-size:var(--fs-label);color:var(--text-secondary)">'+fx['竞价']+'</span></div></div>';
    });
    html += '</div>';

    // 高标竞价
    html += '<div style="background:var(--bg-base);border-radius:var(--radius-md);padding:var(--sp-sm) var(--sp-md)">' +
      '<div style="font-size:var(--fs-body);font-weight:600;color:var(--text-primary);margin-bottom:var(--sp-sm);padding-bottom:var(--sp-xs);border-bottom:1px solid var(--border-light)">高标竞价</div>';
    (auction['高标竞价']||[]).forEach(function(g) {
      html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:3px 0;font-size:var(--fs-body)">' +
        '<span>'+dot(g['灯'])+' <strong>'+g['名称']+'</strong></span>' +
        '<span style="font-family:var(--font-mono);font-weight:600;color:var(--'+chgCls(g['竞价'])+')">'+g['竞价']+'</span>' +
        '</div>';
    });
    html += '</div>';

    // 锚定股竞价
    html += '<div style="background:var(--bg-base);border-radius:var(--radius-md);padding:var(--sp-sm) var(--sp-md)">' +
      '<div style="font-size:var(--fs-body);font-weight:600;color:var(--text-primary);margin-bottom:var(--sp-sm);padding-bottom:var(--sp-xs);border-bottom:1px solid var(--border-light)">锚定股竞价</div>';
    (auction['锚定股竞价']||[]).forEach(function(mao) {
      html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:3px 0;font-size:var(--fs-body)">' +
        '<span>'+dot(mao['灯'])+' <strong>'+mao['标的']+'</strong></span>' +
        '<span style="font-family:var(--font-mono);font-weight:600;color:var(--'+chgCls(mao['竞价'])+')">'+mao['竞价']+'</span>' +
        '</div>';
    });
    html += '</div>';

    html += '</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W06', Auction5DWidget);
