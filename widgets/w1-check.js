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

    var allPass = true;
    var hasFail = false;
    var checks = morning['方向确认'] || morning['条件列表'] || [];

    var html = '';

    // Condition text
    html += '<div style="padding:var(--sp-sm);margin-bottom:var(--sp-sm);background:var(--info-bg);border-radius:var(--radius-sm);font-size:var(--fs-body);color:var(--info)">' +
      (morning['W1出手条件']||'—') + '</div>';

    // Check list
    html += '<div class="check-list">';
    checks.forEach(function(c) {
      if (c['状态'] === 'pass') {}
      else if (c['状态'] === 'fail') { allPass = false; hasFail = true; }
      else { allPass = false; }

      html += '<div class="check-item ' + c['状态'] + '">' +
        '<span>' + (c['状态']==='pass'?'✅':c['状态']==='fail'?'❌':'⏳') + '</span>' +
        '<span>' + c['指标'] + '</span>' +
        '<span style="font-size:var(--fs-label);color:var(--text-secondary)">' + c['判定'] + '</span>' +
        '</div>';
    });
    html += '</div>';

    // Verdict
    html += '<div style="margin-top:var(--sp-sm);padding:var(--sp-sm);border-radius:var(--radius-sm);text-align:center;font-weight:600;' +
      (allPass?'border:1px solid var(--down);color:var(--down)">✅ W1可追':hasFail?'border:1px solid var(--danger);color:var(--danger)">❌ W1关闭':'border:1px solid var(--warn);color:var(--warn)">⏳ 等待确认') +
      '</div>';

    if (!allPass && !hasFail) {
      html += '<div style="font-size:var(--fs-label);color:var(--text-secondary);text-align:center;margin-top:2px">剩余指标待盘中确认</div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W08', W1CheckWidget);
