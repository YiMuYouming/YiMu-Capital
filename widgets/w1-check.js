// widgets/w1-check.js — W08 W1早盘确认（对齐W09动态标题）
'use strict';

class W1CheckWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var decision = (data && data.decision) || {};
    var morning = decision['早盘'] || {};

    var checks = morning['方向确认'] || morning['条件列表'] || [];
    if (!checks.length) {
      body.innerHTML = '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled)">早盘数据待录入</div>';
      return;
    }

    // 统计
    var passCount = 0, failCount = 0, pendingCount = 0;
    checks.forEach(function(c) {
      if (c['状态']==='pass') passCount++;
      else if (c['状态']==='fail') failCount++;
      else pendingCount++;
    });
    var allPass = failCount===0 && pendingCount===0;
    var hasFail = failCount > 0;
    var hasPending = pendingCount > 0;

    // 动态标题
    var statusText, statusColor;
    if (allPass)      { statusText = '✅ '+passCount+'/'+checks.length+' 确认通过 — W1可追'; statusColor = 'var(--up)'; }
    else if (hasFail) { statusText = '❌ '+failCount+'项不满足，'+passCount+'/'+checks.length+' 通过 — W1关闭'; statusColor = 'var(--danger)'; }
    else              { statusText = '⏳ '+passCount+'/'+checks.length+' 通过，'+pendingCount+'项待确认 — 等待确认'; statusColor = 'var(--warn)'; }

    var html = '';

    html += '<div style="padding:var(--sp-sm) var(--sp-md);margin-bottom:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md)">' +
      '<div style="font-size:var(--fs-subtitle);font-weight:700;color:'+statusColor+';margin-bottom:var(--sp-xs)">'+statusText+'</div>' +
      '<div style="font-size:var(--fs-body);color:var(--text-secondary);margin-bottom:var(--sp-sm)">'+(morning['W1出手条件']||'')+'</div>';

    checks.forEach(function(c) {
      var icon = c['状态']==='pass'?'✅':c['状态']==='fail'?'❌':'⏳';
      var verdict = (c['判定']||'').replace(/[✅❌⏳]+$/g,'').trim();
      html += '<div style="display:flex;align-items:center;gap:var(--sp-sm);padding:2px 0;font-size:var(--fs-body)">' +
        '<span style="width:20px">'+icon+'</span>' +
        '<span style="flex:1">'+c['指标']+'</span>' +
        '<span style="color:var(--text-secondary)">'+verdict+'</span></div>';
    });

    html += '</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W08', W1CheckWidget);
