// widgets/midday-review.js — W19 午盘复核（V反检测+双冰）
'use strict';

class MiddayReviewWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var decision = (data && data.decision) || {};
    var mid = decision['盘中'] || {};
    var vRev = mid['V反检测'] || {};
    var db = mid['双冰检测'] || {};
    var S = (data && data.sentiment) || {};

    if (!vRev['场景'] && !db['前日情绪']) {
      body.innerHTML = '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled)">午盘数据待录入</div>';
      return;
    }

    var html = '';

    // V反检测
    html += '<div style="padding:var(--sp-sm) var(--sp-md);margin-bottom:var(--sp-sm);background:var(--special-bg);border-radius:var(--radius-md);border:1px solid var(--special)">' +
      '<div style="font-size:var(--fs-body);font-weight:600;color:var(--special);margin-bottom:var(--sp-sm)">V反检测</div>' +
      '<div style="font-size:var(--fs-body);color:var(--text-secondary);margin-bottom:4px">场景：'+(vRev['场景']||'—')+'</div>' +
      '<div style="font-size:var(--fs-subtitle);font-weight:700;color:var(--special)">'+(vRev['当前状态']||'—')+'</div>' +
      (vRev['午盘复核(13:00)'] ? '<div style="margin-top:var(--sp-xs);font-size:var(--fs-body);color:var(--text-secondary)">'+(vRev['午盘复核(13:00)'])+'</div>' : '') +
      '</div>';

    // 双冰检测
    var yesterdayMood = db['前日情绪'] || S['昨日情绪'] || 0;
    var todayMood = db['今日午盘情绪'] || S['情绪值'] || 0;
    var dbTriggered = db['双冰触发'] || (yesterdayMood < 20 && todayMood < 20);

    html += '<div style="padding:var(--sp-sm) var(--sp-md);background:var(--bg-base);border-radius:var(--radius-md);border:1px solid '+(dbTriggered?'var(--warn)':'var(--border-light)')+'">' +
      '<div style="font-size:var(--fs-body);font-weight:600;color:var(--text-primary);margin-bottom:var(--sp-sm)">双冰检测</div>' +
      '<div style="display:flex;justify-content:space-between;padding:3px 0;font-size:var(--fs-body)">' +
        '<span style="color:var(--text-secondary)">前日情绪</span>' +
        '<span style="font-family:var(--font-mono);font-weight:600;color:'+(yesterdayMood<20?'var(--warn)':'var(--text-primary)')+'">'+(yesterdayMood||'—')+'%</span>' +
      '</div>' +
      '<div style="display:flex;justify-content:space-between;padding:3px 0;font-size:var(--fs-body)">' +
        '<span style="color:var(--text-secondary)">今日午盘</span>' +
        '<span style="font-family:var(--font-mono);font-weight:600;color:'+(todayMood<20?'var(--warn)':'var(--text-primary)')+'">'+(todayMood||'—')+'%</span>' +
      '</div>' +
      '<div style="margin-top:var(--sp-sm);padding-top:var(--sp-xs);border-top:1px solid var(--border-light);text-align:center;font-size:var(--fs-subtitle);font-weight:700;color:var(--'+(dbTriggered?'warn':'info')+')">'+
        (dbTriggered ? '⚠️ 双冰信号' : '✅ 无双冰') +
      '</div>' +
      '</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W19', MiddayReviewWidget);
