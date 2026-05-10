// widgets/w2-check.js — W09 W2低吸条件（对齐W08）
'use strict';

class W2CheckWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var decision = (data && data.decision) || {};
    var mid = decision['盘中'] || {};

    if (!mid['当前状态']) {
      body.innerHTML = '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled)">盘中数据待录入</div>';
      return;
    }

    var allPass = true, hasPending = false;
    var checks = mid['W2出手条件'] || mid['条件列表'] || [];

    var html = '';

    // 当前状态 + 时机
    html += '<div style="padding:var(--sp-sm) var(--sp-md);margin-bottom:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md);font-size:var(--fs-body)">' +
      '<div style="font-size:var(--fs-subtitle);font-weight:700;color:var(--down);margin-bottom:var(--sp-xs)">'+(mid['当前状态']||'—')+'</div>' +
      '<div style="color:var(--text-secondary)">'+(mid['W2出手时机']||'')+'</div>' +
      '</div>';

    // 条件清单
    checks.forEach(function(c) {
      if (c['状态'] === 'pending') { allPass = false; hasPending = true; }
      else if (c['状态'] !== 'pass') { allPass = false; }
      var icon = c['状态']==='pass'?'✅':c['状态']==='fail'?'❌':'⏳';
      var verdict = c['判定']||'';
      // 去掉末尾重复的 ✅❌⏳
      verdict = verdict.replace(/[✅❌⏳]+$/g, '').trim();
      html += '<div style="display:flex;align-items:center;gap:var(--sp-sm);padding:4px 0;font-size:var(--fs-body)">' +
        '<span style="width:20px">'+icon+'</span>' +
        '<span style="flex:1">'+c['指标']+'</span>' +
        '<span style="color:var(--text-secondary)">'+verdict+'</span>' +
        '</div>';
    });

    // 结论
    html += '<div style="margin-top:var(--sp-sm);padding:var(--sp-sm);border-radius:var(--radius-sm);text-align:center;font-size:var(--fs-subtitle);font-weight:700;' +
      (allPass?'border:1px solid var(--down);color:var(--down)">✅ W2可吸':hasPending?'border:1px solid var(--warn);color:var(--warn)">⏳ 等待企稳':'border:1px solid var(--danger);color:var(--danger)">❌ W2关闭') +
      '</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W09', W2CheckWidget);
