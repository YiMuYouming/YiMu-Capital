// widgets/w2-check.js — W09 W2低吸+午盘复核 (v2.0 扩展)
'use strict';

class W2CheckWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var decision = (data && data.decision) || {};
    var mid = decision['盘中'] || {};

    if (!mid['当前状态']) {
      body.innerHTML = '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled)">盘中等数据录入</div>';
      return;
    }

    var allPass = true;
    var hasPending = false;

    var html = '';

    // === W2 低吸区 ===
    html += '<div style="font-size:var(--fs-header);font-weight:600;margin-bottom:var(--sp-sm);color:var(--info)">W2 低吸</div>';

    html += '<div style="padding:var(--sp-sm);margin-bottom:var(--sp-sm);background:var(--info-bg);border-radius:var(--radius-sm);font-size:var(--fs-body);color:var(--info)">' +
      (mid['W2出手时机']||'—') + '</div>';

    var checks = mid['W2出手条件'] || mid['条件列表'] || [];
    html += '<div class="check-list">';
    checks.forEach(function(c) {
      if (c['状态'] === 'pending') { allPass = false; hasPending = true; }
      else if (c['状态'] !== 'pass') { allPass = false; }
      html += '<div class="check-item ' + c['状态'] + '">' +
        '<span>' + (c['状态']==='pass'?'✅':c['状态']==='pending'?'⏳':'❌') + '</span>' +
        '<span>' + c['指标'] + '</span>' +
        '<span style="font-size:var(--fs-label);color:var(--text-secondary)">' + c['判定'] + '</span>' +
        '</div>';
    });
    html += '</div>';

    html += '<div style="margin-top:var(--sp-sm);padding:var(--sp-sm);border-radius:var(--radius-sm);text-align:center;font-weight:600;' +
      (allPass?'border:1px solid var(--down);color:var(--down)">✅ W2可吸':'border:1px solid var(--warn);color:var(--warn)">⏳ 等待企稳') +
      '</div>';

    // === 午盘复核区 (v2.0 扩展) ===
    var vRev = mid['V反检测'] || {};
    html += '<div style="margin-top:var(--sp-md);padding-top:var(--sp-sm);border-top:1px solid var(--border-light)">' +
      '<div style="font-size:var(--fs-header);font-weight:600;margin-bottom:var(--sp-sm);color:var(--special)">午盘复核 (13:00)</div>';

    // V反检测
    html += '<div style="padding:var(--sp-sm);margin-bottom:var(--sp-sm);background:var(--special-bg);border-radius:var(--radius-sm)">' +
      '<div class="kpi-label">V反检测</div>' +
      '<div style="font-size:var(--fs-body)">场景: ' + (vRev['场景']||'不适用') + '</div>' +
      '<div style="font-size:var(--fs-body)">状态: ' + (vRev['当前状态']||'—') + '</div>' +
      '</div>';

    // 双冰检测 (v2.0 新增)
    html += '<div style="padding:var(--sp-sm);margin-bottom:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-sm)">' +
      '<div class="kpi-label">双冰检测</div>' +
      '<div style="font-size:var(--fs-body)">前日情绪: ' + ((data&&data.sentiment&&data.sentiment['昨日情绪']!=null) ? data.sentiment['昨日情绪']+'%' : '—') + '</div>' +
      '<div style="font-size:var(--fs-body)">今日午盘: ' + ((data&&data.sentiment&&data.sentiment['情绪值']!=null) ? data.sentiment['情绪值']+'%' : '—') + '</div>' +
      '<div style="font-size:var(--fs-label);margin-top:2px;color:var(--text-secondary)">前日冰点+今日冰点→双冰信号</div>' +
      '</div>';

    // 复核结论
    html += '<div style="padding:var(--sp-sm);border-radius:var(--radius-sm);text-align:center;font-size:var(--fs-body);color:var(--special);background:var(--special-bg)">' +
      (mid['当前状态']||'—') + '</div>';

    html += '</div>';
    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W09', W2CheckWidget);
