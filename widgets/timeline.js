// widgets/timeline.js — W01 时段时间线
'use strict';

class TimelineWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;

    var segments = [
      {label:'竞价',start:545,end:570},{label:'W1追涨',start:570,end:600},
      {label:'观察期',start:600,end:780},{label:'午盘复核',start:780,end:840},
      {label:'W2低吸',start:840,end:885},{label:'闭窗',start:885,end:900}
    ];
    var nowHM = new Date().getHours()*60 + new Date().getMinutes();

    var html = '<div class="timeline-bar">';
    segments.forEach(function(s) {
      var cls = nowHM < s.start ? 'future' : nowHM > s.end ? 'done' : 'active';
      var pct = s.end <= s.start ? 0 : Math.min(100, Math.max(0, Math.round((nowHM - s.start)/(s.end - s.start)*100)));
      html += '<div class="timeline-seg ' + cls + '" style="flex:' + (s.end-s.start) + '">' +
        '<span>' + s.label + '</span>' +
        (cls==='active'?'<div class="timeline-seg-fill" style="width:'+pct+'%"></div>':'') +
        '</div>';
    });
    html += '</div>';
    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W01', TimelineWidget);
