// widgets/timeline.js — W01 时段时间线
'use strict';

class TimelineWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;

    var segments = [
      {label:'竞价',      start:{h:9,m:15}, end:{h:9,m:30},  color:'var(--warn)'},
      {label:'W1窗口',   start:{h:9,m:30}, end:{h:10,m:0},  color:'var(--danger)'},
      {label:'上午观察',  start:{h:10,m:0}, end:{h:11,m:30}, color:'var(--info)'},
      {label:'午盘复盘',  start:{h:11,m:30},end:{h:13,m:0},  color:'var(--special)'},
      {label:'下午观察',  start:{h:13,m:0}, end:{h:14,m:0},  color:'var(--info)'},
      {label:'W2窗口',   start:{h:14,m:0}, end:{h:14,m:45}, color:'var(--down)'},
      {label:'尾盘观察',  start:{h:14,m:45},end:{h:15,m:0},  color:'var(--text-disabled)'}
    ];

    // 调试模式：URL 加 ?time=HH:MM
    var search = (typeof location !== 'undefined' && location.search) ? location.search : '';
    var debugMatch = search.match(/[?&]time=(\d{1,2}):(\d{2})/);
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
    html += '<div class="time-line timeline-shell">';

    // 状态文字 + 倒计时
    html += '<div class="timeline-status">';
    if (isWeekend) {
      html += '<div class="timeline-status-title timeline-muted">休市</div>';
      html += '<div class="timeline-status-sub timeline-muted">周末</div>';
    } else if (isBefore) {
      var minToOpen = totalStart - nowHM;
      html += '<div class="timeline-status-title timeline-warn">盘前准备</div>';
      html += '<div class="timeline-status-sub">距开盘 ' + Math.floor(minToOpen/60) + '时' + (minToOpen%60) + '分</div>';
    } else if (isAfter) {
      html += '<div class="timeline-status-title timeline-muted">已闭市</div>';
      html += '<div class="timeline-status-sub timeline-muted">明日 9:15 开盘</div>';
    } else if (current) {
      var remaining = current.end - nowHM;
      var rmStr = remaining >= 60 ? Math.floor(remaining/60) + '时' + (remaining%60) + '分' : remaining + '分钟';
      html += '<div class="timeline-status-title" style="color:' + current.color + '">' + current.label + '</div>';
      html += '<div class="timeline-status-sub">' +
        '<span>剩余 </span>' +
        '<b>' + rmStr + '</b>' +
        '</div>';
      html += '<div class="timeline-window">' +
        fmtHM(current.start) + ' — ' + fmtHM(current.end) + '</div>';
    }
    html += '</div>';

    // 右侧：进度条 + 百分比
    html += '<div class="timeline-main">';

    // 色条
    html += '<div class="timeline-track">';
    segments.forEach(function(s, i) {
      var sDur = (s.end.h*60+s.end.m) - (s.start.h*60+s.start.m);
      var op = 1;
      if (isWeekend || isAfter) op = 0.25;
      else if (i < (current||{}).idx) op = 0.35;
      else if (i === (current||{}).idx) op = 1;
      else op = 0.2;
      html += '<div class="timeline-slice" style="flex:' + sDur + ';background:' + s.color + ';opacity:' + op + '" title="' + s.label + ' ' + fmtHM(s.start.h*60+s.start.m) + '-' + fmtHM(s.end.h*60+s.end.m) + '"></div>';
    });
    html += '</div>';

    // 时段标签
    html += '<div class="timeline-label-row">';
    segments.forEach(function(s, i) {
      var sDur = (s.end.h*60+s.end.m) - (s.start.h*60+s.start.m);
      var isCur = i === (current||{}).idx;
      html += '<div class="timeline-label' + (isCur ? ' is-current' : '') + '" style="flex:' + sDur + '">' + s.label + '</div>';
    });
    html += '</div>';

    // 全天进度
    var pctCls = dayProgress >= 80 ? 'danger' : dayProgress >= 50 ? 'warn' : 'info';
    html += '<div class="timeline-progress-row">' +
      '<span>全天进度</span>' +
      '<b class="' + pctCls + '">' + dayProgress + '%</b>' +
      '</div>';

    html += '</div></div>';

    body.innerHTML = html;
    this.updateTimestamp();

    // 每 30 秒自刷新（倒计时需要高频更新），首次挂载时启动
    if (!this._hasTimer) {
      this._hasTimer = true;
      var self = this;
      var tid = setInterval(function() {
        if (typeof isDragging === 'undefined' || !isDragging) self._renderBody();
      }, 30000);
      if (!this._timers) this._timers = [];
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
