// widgets/timeline.js — W01 时段时间线
'use strict';

class TimelineWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;

    var segments = [
      {label:'竞价',      start:{h:9,m:15}, end:{h:9,m:30},  color:'#ffa726'},
      {label:'W1窗口',   start:{h:9,m:30}, end:{h:10,m:0},  color:'#ef5350'},
      {label:'上午观察',  start:{h:10,m:0}, end:{h:11,m:30}, color:'#5c9ce6'},
      {label:'午盘复盘',  start:{h:11,m:30},end:{h:13,m:0},  color:'#ab47bc'},
      {label:'下午观察',  start:{h:13,m:0}, end:{h:14,m:0},  color:'#5c9ce6'},
      {label:'W2窗口',   start:{h:14,m:0}, end:{h:14,m:45}, color:'#66bb6a'},
      {label:'尾盘观察',  start:{h:14,m:45},end:{h:15,m:0},  color:'#9aa0a6'}
    ];

    // 调试模式：URL 加 ?time=HH:MM
    var debugMatch = location.search.match(/[?&]time=(\d{1,2}):(\d{2})/);
    var now = new Date();
    var nowH, nowM;
    if (debugMatch) {
      nowH = parseInt(debugMatch[1]); nowM = parseInt(debugMatch[2]);
      now.setHours(nowH, nowM, 0, 0);
    } else {
      nowH = now.getHours(); nowM = now.getMinutes();
    }
    var nowHM = nowH * 60 + nowM;

    // 周末判断：优先读数据 weekday
    var meta = (data && data.meta) || {};
    var weekday = meta['weekday'] || '';
    var isWeekend = weekday === '周六' || weekday === '周日';
    if (!weekday) {
      var sysDay = now.getDay();
      isWeekend = sysDay === 0 || sysDay === 6;
    }

    var totalStart = 9*60+15;  // 9:15
    var totalEnd = 15*60;      // 15:00
    var totalDuration = totalEnd - totalStart;

    // 找到当前时段
    var current = null;
    for (var i = 0; i < segments.length; i++) {
      var s = segments[i];
      var sStart = s.start.h * 60 + s.start.m;
      var sEnd = s.end.h * 60 + s.end.m;
      if (nowHM >= sStart && nowHM < sEnd) {
        current = { idx: i, start: sStart, end: sEnd, label: s.label, color: s.color };
        break;
      }
    }

    // 全天进度
    var dayProgress = 0;
    if (nowHM >= totalEnd) dayProgress = 100;
    else if (nowHM > totalStart) dayProgress = Math.round((nowHM - totalStart) / totalDuration * 100);

    var isBefore = nowHM < totalStart;
    var isAfter = nowHM >= totalEnd;

    // === 渲染 ===
    var html = '';

    // 左侧：状态区
    html += '<div style="display:flex;align-items:center;height:100%;gap:var(--sp-lg)">';

    // 状态文字 + 倒计时
    html += '<div style="min-width:150px">';
    if (isWeekend) {
      html += '<div style="font-size:var(--fs-subtitle);font-weight:700;color:var(--text-disabled)">休市</div>';
      html += '<div style="font-size:var(--fs-body);color:var(--text-disabled)">周末</div>';
    } else if (isBefore) {
      var minToOpen = totalStart - nowHM;
      html += '<div style="font-size:var(--fs-subtitle);font-weight:700;color:var(--warn)">盘前准备</div>';
      html += '<div style="font-size:var(--fs-body);color:var(--text-secondary)">距开盘 ' + Math.floor(minToOpen/60) + '时' + (minToOpen%60) + '分</div>';
    } else if (isAfter) {
      html += '<div style="font-size:var(--fs-subtitle);font-weight:700;color:var(--text-disabled)">已闭市</div>';
      html += '<div style="font-size:var(--fs-body);color:var(--text-disabled)">明日 9:15 开盘</div>';
    } else if (current) {
      var remaining = current.end - nowHM;
      var rmStr = remaining >= 60 ? Math.floor(remaining/60) + '时' + (remaining%60) + '分' : remaining + '分钟';
      html += '<div style="font-size:20px;font-weight:700;color:' + current.color + ';line-height:1.2">' + current.label + '</div>';
      html += '<div style="font-size:var(--fs-body);margin-top:2px">' +
        '<span style="color:var(--text-secondary)">剩余 </span>' +
        '<span style="font-weight:700;color:var(--text-primary);font-family:var(--font-mono);font-variant-numeric:tabular-nums">' + rmStr + '</span>' +
        '</div>';
      html += '<div style="font-size:var(--fs-label);color:var(--text-disabled);margin-top:1px">' +
        fmtHM(current.start) + ' — ' + fmtHM(current.end) + '</div>';
    }
    html += '</div>';

    // 右侧：进度条 + 百分比
    html += '<div style="flex:1;min-width:240px">';

    // 色条
    html += '<div style="display:flex;height:8px;border-radius:4px;overflow:hidden;gap:1px;margin-bottom:6px">';
    segments.forEach(function(s, i) {
      var sDur = (s.end.h*60+s.end.m) - (s.start.h*60+s.start.m);
      var op = 1;
      if (isWeekend || isAfter) op = 0.25;
      else if (i < (current||{}).idx) op = 0.35;
      else if (i === (current||{}).idx) op = 1;
      else op = 0.2;
      html += '<div style="flex:' + sDur + ';background:' + s.color + ';opacity:' + op + ';min-width:2px;border-radius:1px" title="' + s.label + ' ' + fmtHM(s.start.h*60+s.start.m) + '-' + fmtHM(s.end.h*60+s.end.m) + '"></div>';
    });
    html += '</div>';

    // 时段标签
    html += '<div style="display:flex;font-size:var(--fs-micro);color:var(--text-disabled)">';
    segments.forEach(function(s, i) {
      var sDur = (s.end.h*60+s.end.m) - (s.start.h*60+s.start.m);
      var isCur = i === (current||{}).idx;
      html += '<div style="flex:' + sDur + ';text-align:center;min-width:0;overflow:hidden;white-space:nowrap;' + (isCur ? 'color:var(--text-primary);font-weight:600' : '') + '">' + s.label + '</div>';
    });
    html += '</div>';

    // 全天进度
    var pctCls = dayProgress >= 80 ? 'danger' : dayProgress >= 50 ? 'warn' : 'info';
    html += '<div style="display:flex;align-items:center;justify-content:flex-end;margin-top:4px;gap:var(--sp-sm)">' +
      '<span style="font-size:var(--fs-label);color:var(--text-secondary)">全天进度</span>' +
      '<span style="font-family:var(--font-mono);font-size:var(--fs-body);font-weight:700;color:var(--' + pctCls + ')">' + dayProgress + '%</span>' +
      '</div>';

    html += '</div></div>';

    body.innerHTML = html;
    this.updateTimestamp();

    // 每 30 秒自刷新（倒计时需要高频更新），首次挂载时启动
    if (!this._hasTimer) {
      this._hasTimer = true;
      var self = this;
      var tid = setInterval(function() { if (!isDragging) self._renderBody(); }, 30000);
      this._timers.push(tid);
    }
  }
}

function fmtHM(minutes) {
  var h = Math.floor(minutes / 60);
  var m = minutes % 60;
  return h + ':' + (m < 10 ? '0' : '') + m;
}

WidgetRegistry.register('W01', TimelineWidget);
