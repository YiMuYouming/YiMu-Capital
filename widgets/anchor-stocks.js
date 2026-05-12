// widgets/anchor-stocks.js — W18 锚定股状态 (v2.2 实时涨幅+颜色标记)
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

    var quotes = (data && data.live_quotes) || {};
    // 从自选池建名称→代码映射
    var nameToCode = {};
    ['lianban_pool', 'trend_pool'].forEach(function(k) {
      (data[k] || []).forEach(function(s) {
        var n = s['标的'];
        var c = s['代码'];
        if (n && c) nameToCode[n] = c;
      });
    });

    function lampStyle(lamp) {
      if (lamp === 'green') return { border: 'var(--info)', bg: 'rgba(59,130,246,0.06)', dot: '🟢', label: '正常' };
      if (lamp === 'red') return { border: 'var(--danger)', bg: 'rgba(255,59,48,0.05)', dot: '🔴', label: '危险' };
      return { border: 'var(--warn)', bg: 'rgba(255,149,0,0.05)', dot: '🟠', label: '关注' };
    }

    var html = '<div style="display:flex;gap:var(--sp-sm);flex-wrap:wrap">';
    anchors.forEach(function(a) {
      var name = a['标的'] || '—';
      var code = a['代码'] || nameToCode[name] || '';
      var live = quotes[code] || {};
      var chg = live['涨幅'];
      var chgStr = (chg && chg !== '—') ? chg : '—';
      var chgCls = '';
      if (chgStr.charAt(0) === '+') chgCls = 'up';
      else if (chgStr.charAt(0) === '-') chgCls = 'down';

      var lamp = a['灯'] || 'yellow';
      var st = lampStyle(lamp);
      var status = a['状态'] || '—';
      var win = a['窗口'] || '';

      html += '<div style="flex:1;min-width:180px;padding:var(--sp-sm) var(--sp-md);background:var(--bg-base);border-radius:var(--radius-md);border-left:3px solid ' + st.border + '">' +
        // 第一行：灯 + 名称 + 窗口标签 + 涨幅
        '<div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-sm)">' +
          '<span style="font-weight:700;font-size:13px;color:var(--text-primary)">' + st.dot + ' ' + name +
            (code ? ' <span style="font-size:10px;color:var(--text-disabled)">' + code + '</span>' : '') +
            (win ? ' <span style="font-size:10px;padding:0 4px;border-radius:2px;background:var(--bg-hover);color:var(--text-secondary)">'+win+'</span>' : '') +
          '</span>' +
          '<span class="' + chgCls + '" style="font-size:14px;font-weight:600;white-space:nowrap">' + chgStr + '</span>' +
        '</div>' +
        // 第二行：状态 + 影响
        '<div style="font-size:12px;color:var(--text-secondary);margin-top:3px">' + status + '</div>' +
        '<div style="font-size:11px;color:var(--text-disabled);margin-top:1px">→ ' + (a['影响'] || '—') + '</div>' +
        '</div>';
    });
    html += '</div>';

    // 图例
    html += '<div style="font-size:11px;color:var(--text-disabled);margin-top:var(--sp-xs)">' +
      '<span style="border-left:3px solid var(--danger);padding-left:4px">危险</span> ' +
      '<span style="border-left:3px solid var(--warn);padding-left:4px;margin-left:6px">关注</span> ' +
      '<span style="border-left:3px solid var(--info);padding-left:4px;margin-left:6px">正常</span>' +
      '</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W18', AnchorStocksWidget);
