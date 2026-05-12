// widgets/sector-heat.js — W10 板块热力图 (v2.2 名称映射+类型色标)
'use strict';

class SectorHeatWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var sectors = (data && data.sectors) || [];
    var live = (data && data.live_sectors) || {};

    if (!sectors.length) {
      body.innerHTML = '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled)">板块数据未录入</div>';
      return;
    }

    // 类型样式
    function typeStyle(t) {
      var s = {};
      if (!t) { s.border = '2px solid var(--border-light)'; s.badge = 'var(--text-disabled)'; return s; }
      if (t.indexOf('主线') >= 0 && t.indexOf('趋势') >= 0) {
        s.border = '2px solid var(--info)'; s.badge = 'var(--info)'; s.bg = 'rgba(59,130,246,0.06)';
      } else if (t.indexOf('主线') >= 0) {
        s.border = '2px solid var(--up)'; s.badge = 'var(--up)'; s.bg = 'rgba(255,59,48,0.05)';
      } else if (t.indexOf('支线') >= 0) {
        s.border = '2px solid var(--warn)'; s.badge = 'var(--warn)'; s.bg = 'rgba(255,149,0,0.05)';
      } else if (t === '退潮' || t.indexOf('退潮') >= 0) {
        s.border = '2px solid var(--text-disabled)'; s.badge = 'var(--text-disabled)'; s.opacity = 0.5;
      } else {
        s.border = '2px solid var(--border-light)'; s.badge = 'var(--text-secondary)';
      }
      return s;
    }

    // 别名 → 大板块名 归一化
    var ALIAS = {
      'CPO': 'CPO/光通信', '光通信': 'CPO/光通信', 'CPO/光通信': 'CPO/光通信',
      '半导体': '半导体', '半导体/存储': '半导体', '半导体/封装': '半导体',
      '半导体/设备': '半导体', '半导体/算力': '半导体', '半导体产业链': '半导体',
      '电力': '电力',
      'PCB': 'PCB', 'PCB链': 'PCB', 'CPO/PCB': 'CPO/光通信', // PCB偏CPO侧归入光通信
      '机器人': '机器人',
    };
    function normalizeName(name) {
      if (!name) return '';
      if (ALIAS[name]) return ALIAS[name];
      // 斜杠前缀匹配
      var idx = name.indexOf('/');
      if (idx >= 0) {
        var prefix = name.substring(0, idx);
        if (ALIAS[prefix]) return ALIAS[prefix];
      }
      return name;
    }

    // 匹配实时数据
    function matchLive(name) {
      var n = normalizeName(name);
      if (live[n]) return live[n];
      if (live[name]) return live[name];
      var keys = Object.keys(live);
      for (var i = 0; i < keys.length; i++) {
        if (n.indexOf(keys[i]) >= 0 || keys[i].indexOf(n) >= 0) return live[keys[i]];
      }
      return null;
    }

    var html = '';
    sectors.forEach(function(s) {
      var name = s['板块'] || '—';
      var type = s['类型'] || '';
      var liveS = matchLive(name) || {};
      var st = typeStyle(type);
      var chg = liveS['涨跌幅'];
      var chgNum = parseFloat(chg);
      var chgStr = (!isNaN(chgNum) ? (chgNum >= 0 ? '+' : '') + chgNum.toFixed(2) + '%' : '—');
      var chgCls = chgNum >= 0 ? 'up' : (chgNum < 0 ? 'down' : '');

      html += '<div style="padding:var(--sp-sm) var(--sp-md);border-radius:var(--radius-md);margin-bottom:var(--sp-xs);' +
        'border:' + st.border + ';' + (st.bg ? 'background:' + st.bg + ';' : '') + (st.opacity ? 'opacity:' + st.opacity + ';' : '') + '">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-sm)">' +

        // 左侧：板块名+标签
        '<div style="flex:1;min-width:0">' +
          '<span style="font-weight:700;font-size:13px;color:var(--text-primary)">' + name + '</span> ' +
          '<span style="font-size:11px;padding:1px 6px;border-radius:3px;background:' + st.badge + '1a;color:' + st.badge + ';font-weight:600">' + type + '</span>' +
          '<div style="font-size:11px;color:var(--text-secondary);margin-top:2px">' +
            (s['梯队'] ? s['梯队'] + '梯队' : '') +
            (s['龙头'] ? ' · ' + s['龙头'] : '') +
            (s['状态'] ? ' · ' + s['状态'] : '') +
          '</div>' +
        '</div>' +

        // 右侧：实时数据
        '<div style="display:flex;gap:var(--sp-md);text-align:right;flex-shrink:0">' +
          '<div><div style="font-size:10px;color:var(--text-disabled)">涨跌</div>' +
            '<div class="' + chgCls + '" style="font-size:14px;font-weight:600">' + chgStr + '</div></div>' +
          '<div><div style="font-size:10px;color:var(--text-disabled)">涨停数</div>' +
            '<div style="font-size:14px;color:var(--text-primary)">' + (s['涨停数'] != null ? s['涨停数'] : '—') + '</div></div>' +
        '</div>' +

        '</div></div>';
    });

    html += '<div style="font-size:12px;color:var(--text-disabled);margin-top:var(--sp-xs)">' +
      '<span style="border-left:3px solid var(--up);padding-left:4px">主线</span> ' +
      '<span style="border-left:3px solid var(--info);padding-left:4px;margin-left:6px">趋势主线</span> ' +
      '<span style="border-left:3px solid var(--warn);padding-left:4px;margin-left:6px">强支线</span> ' +
      '<span style="border-left:3px solid var(--text-disabled);padding-left:4px;margin-left:6px">退潮</span>' +
      '</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W10', SectorHeatWidget);
