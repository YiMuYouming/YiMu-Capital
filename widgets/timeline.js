// widgets/timeline.js — W01 时段时间线 (v2.1.1 C方案: 当前时段+倒计时+全天进度条)
'use strict';

class TimelineWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;

    var segments = [
      {label:'竞价',    start:{h:9,m:5},  end:{h:9,m:30},  color:'#ffa726'},
      {label:'W1追涨', start:{h:9,m:30}, end:{h:10,m:0},  color:'#ef5350'},
      {label:'观察期',  start:{h:10,m:0}, end:{h:13,m:0},  color:'#5c9ce6'},
      {label:'午盘复核',start:{h:13,m:0}, end:{h:14,m:0},  color:'#ab47bc'},
      {label:'W2低吸', start:{h:14,m:0}, end:{h:14,m:45}, color:'#66bb6a'},
      {label:'闭窗',    start:{h:14,m:45},end:{h:15,m:0},  color:'#9aa0a6'},
    ];

    // 调试模式：URL 加 ?time=10:00 模拟任意时间
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

    // 找到当前时段
    var current = null, next = null;
    var totalStart = 9*60+5;  // 9:05
    var totalEnd = 15*60;     // 15:00
    var totalDuration = totalEnd - totalStart;

    for (var i = 0; i < segments.length; i++) {
      var s = segments[i];
      var sStart = s.start.h * 60 + s.start.m;
      var sEnd = s.end.h * 60 + s.end.m;
      if (nowHM >= sStart && nowHM < sEnd) {
        current = { idx: i, start: sStart, end: sEnd, label: s.label, color: s.color };
      }
      if (!current && !next && nowHM < sStart) {
        next = { idx: i, start: sStart, end: sEnd, label: s.label, color: s.color };
      }
    }

    // 全天进度
    var dayProgress = 0;
    if (nowHM < totalStart) dayProgress = 0;
    else if (nowHM >= totalEnd) dayProgress = 100;
    else dayProgress = Math.round((nowHM - totalStart) / totalDuration * 100);

    // 判断状态——优先读数据中的 weekday，调试时模拟场景
    var meta = (data && data.meta) || {};
    var weekday = meta['weekday'] || '';
    var isWeekend = weekday === '周六' || weekday === '周日';
    // 无数据时用系统时间判断
    if (!weekday) {
      var sysDay = now.getDay();
      isWeekend = sysDay === 0 || sysDay === 6;
    }
    var isClosed = nowHM >= totalEnd || nowHM < totalStart;

    var html = '';

    if (isWeekend) {
      // 周末
      html += '<div style="display:flex;align-items:center;justify-content:space-between;height:100%">' +
        '<div><div style="font-size:var(--fs-subtitle);font-weight:700;color:var(--text-disabled)">休市</div>' +
        '<div style="font-size:var(--fs-label);color:var(--text-disabled)">周末</div></div>' +
        '<div style="font-size:var(--fs-label);color:var(--text-disabled)">周一 9:05 开盘</div>' +
        '</div>';
    } else if (isClosed && nowHM < totalStart) {
      // 盘前
      var minToOpen = totalStart - nowHM;
      html += '<div style="display:flex;align-items:center;justify-content:space-between;height:100%">' +
        '<div><div style="font-size:var(--fs-subtitle);font-weight:700;color:var(--warn)">盘前准备</div>' +
        '<div style="font-size:var(--fs-label);color:var(--text-secondary)">距竞价 ' + Math.floor(minToOpen/60) + '时' + (minToOpen%60) + '分</div></div>' +
        _progressBar(segments, 0, -1) +
        '</div>';
    } else if (current) {
      // 当前在某个时段内
      var remaining = current.end - nowHM;
      var rmH = Math.floor(remaining / 60);
      var rmM = remaining % 60;
      var segProgress = Math.round((nowHM - current.start) / (current.end - current.start) * 100);
      var rmStr = rmH > 0 ? rmH + '时' + rmM + '分' : rmM + '分钟';

      html += '<div style="display:flex;align-items:center;justify-content:space-between;height:100%;gap:var(--sp-md)">' +
        // 左侧：当前时段 + 倒计时
        '<div style="min-width:140px">' +
        '<div style="font-size:var(--fs-subtitle);font-weight:700;color:' + current.color + '">' + current.label + '</div>' +
        '<div style="font-size:var(--fs-body)"><span style="color:var(--text-secondary)">剩余 </span><span style="font-weight:600;color:var(--text-primary)">' + rmStr + '</span></div>' +
        '<div style="font-size:var(--fs-label);color:var(--text-disabled);margin-top:1px">' +
          _fmtTime(current.start) + ' - ' + _fmtTime(current.end) +
        '</div></div>' +
        // 右侧：全天进度条
        _progressBar(segments, current.idx, dayProgress) +
        '</div>';
    } else {
      // 已闭市
      html += '<div style="display:flex;align-items:center;justify-content:space-between;height:100%">' +
        '<div><div style="font-size:var(--fs-subtitle);font-weight:700;color:var(--text-disabled)">已闭市</div>' +
        '<div style="font-size:var(--fs-label);color:var(--text-disabled)">明日 9:05 开盘</div></div>' +
        _progressBar(segments, -1, 100) +
        '</div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

function _fmtTime(minutes) {
  var h = Math.floor(minutes / 60);
  var m = minutes % 60;
  return h + ':' + (m < 10 ? '0' : '') + m;
}

function _progressBar(segments, activeIdx, dayPct) {
  var html = '<div style="flex:1;min-width:200px">' +
    '<div style="display:flex;height:8px;border-radius:4px;overflow:hidden;gap:1px;margin-bottom:4px">';

  segments.forEach(function(s, i) {
    var sDur = (s.end.h*60+s.end.m) - (s.start.h*60+s.start.m);
    var cls = '';
    if (i < activeIdx) cls = 'opacity:0.35';
    else if (i === activeIdx) cls = 'opacity:1';
    else cls = 'opacity:0.2';
    html += '<div style="flex:' + sDur + ';background:' + s.color + ';' + cls + ';min-width:2px;border-radius:1px" title="' + s.label + ' ' + _fmtTime(s.start.h*60+s.start.m) + '-' + _fmtTime(s.end.h*60+s.end.m) + '"></div>';
  });

  html += '</div>';

  // 标签
  html += '<div style="display:flex;font-size:var(--fs-micro);color:var(--text-disabled)">';
  segments.forEach(function(s, i) {
    var sDur = (s.end.h*60+s.end.m) - (s.start.h*60+s.start.m);
    var cls = i === activeIdx ? 'color:var(--text-primary);font-weight:600' : '';
    html += '<div style="flex:' + sDur + ';text-align:center;min-width:0;overflow:hidden;white-space:nowrap;' + cls + '">' + s.label + '</div>';
  });
  html += '</div>';

  // 进度百分比
  html += '<div style="font-size:var(--fs-micro);color:var(--text-disabled);text-align:right;margin-top:2px">全天进度 ' + dayPct + '%</div>';

  html += '</div>';
  return html;
}

WidgetRegistry.register('W01', TimelineWidget);
