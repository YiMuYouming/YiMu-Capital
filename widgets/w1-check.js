// widgets/w1-check.js — W08 W1早盘确认
'use strict';

class W1CheckWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var decision = (data && data.decision) || {};
    var morning = decision['早盘'] || {};

    if (!morning['当前状态']) {
      body.innerHTML = '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled)">早盘数据待录入</div>';
      return;
    }

    var allPass = true, hasFail = false;
    var checks = morning['方向确认'] || morning['条件列表'] || [];

    var html = '';

    // 当前状态
    html += '<div style="padding:var(--sp-sm) var(--sp-md);margin-bottom:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md);font-size:var(--fs-body)">' +
      '<div style="font-size:var(--fs-subtitle);font-weight:700;color:var(--info);margin-bottom:var(--sp-xs)">'+(morning['当前状态']||'—')+'</div>' +
      '<div style="color:var(--text-secondary)">'+(morning['W1出手条件']||'')+'</div>' +
      '</div>';

    // 检查清单
    checks.forEach(function(c) {
      if (c['状态'] === 'fail') { allPass = false; hasFail = true; }
      else if (c['状态'] !== 'pass') { allPass = false; }
      var icon = c['状态']==='pass'?'✅':c['状态']==='fail'?'❌':'⏳';
      var cls = c['状态']==='pass'?'pass':c['状态']==='fail'?'fail':'pending';
      var verdict = c['判定']||'';
      verdict = verdict.replace(/[✅❌⏳]+$/g, '').trim();
      html += '<div style="display:flex;align-items:center;gap:var(--sp-sm);padding:4px 0;font-size:var(--fs-body)">' +
        '<span style="width:20px">'+icon+'</span>' +
        '<span style="flex:1">'+c['指标']+'</span>' +
        '<span style="color:var(--text-secondary)">'+verdict+'</span>' +
        '</div>';
    });

    // 结论
    html += '<div style="margin-top:var(--sp-sm);padding:var(--sp-sm);border-radius:var(--radius-sm);text-align:center;font-size:var(--fs-subtitle);font-weight:700;' +
      (allPass?'border:1px solid var(--down);color:var(--down)">✅ W1可追':hasFail?'border:1px solid var(--danger);color:var(--danger)">❌ W1关闭':'border:1px solid var(--warn);color:var(--warn)">⏳ 等待确认') +
      '</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W08', W1CheckWidget);
