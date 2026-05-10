// widgets/climax-guard.js — W07 高潮保护
'use strict';

class ClimaxGuardWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;

    var S = (data && data.sentiment) || {};
    var auction = (data && data.decision && data.decision['竞价']) || {};
    var moodVal = S['竞价情绪值'] || auction['竞价情绪值'] || '—';
    var moodNum = parseFloat(moodVal) || 0;

    var level = '', w1Status = '正常', w2Status = '正常', triggered = false;

    if (moodNum >= 90)      { level = '一级保护(≥90%)'; w1Status = '全关'; w2Status = '全关'; triggered = true; }
    else if (moodNum >= 85) { level = '二级保护(85-90%)'; w1Status = '全关'; w2Status = '降半仓'; triggered = true; }
    else if (moodNum >= 80) { level = '三级保护(80-85%)'; w1Status = '降半仓'; w2Status = '正常'; triggered = true; }
    else                    { level = '未触发(<80%)'; }

    var html = '';

    // 大号情绪值 + 标签
    html += '<div style="text-align:center;padding:var(--sp-sm)">' +
      '<div style="font-family:var(--font-mono);font-size:var(--fs-kpi);font-weight:700;color:'+(triggered?'var(--danger)':'var(--down)')+';line-height:1.2">'+moodVal+'</div>' +
      '<div style="font-size:var(--fs-body);color:var(--text-secondary);margin-top:4px">竞价情绪值</div>' +
      '</div>';

    // 保护级别
    html += '<div style="margin-top:var(--sp-sm)">' +
      '<div class="kpi-card" style="margin-bottom:var(--sp-xs)">' +
        '<div class="kpi-label">保护级别</div>' +
        '<div style="font-size:var(--fs-subtitle);font-weight:700;color:var(--'+(triggered?'danger':'info')+')">'+level+'</div>' +
      '</div>';

    // W1 / W2 状态
    html += '<div style="display:flex;gap:var(--sp-xs)">' +
      '<div class="kpi-card" style="flex:1">' +
        '<div class="kpi-label">W1 窗口</div>' +
        '<div style="font-size:var(--fs-subtitle);font-weight:700;color:var(--'+(w1Status==='正常'?'info':'danger')+')">'+w1Status+'</div>' +
      '</div>' +
      '<div class="kpi-card" style="flex:1">' +
        '<div class="kpi-label">W2 窗口</div>' +
        '<div style="font-size:var(--fs-subtitle);font-weight:700;color:var(--'+(w2Status==='正常'?'info':'danger')+')">'+w2Status+'</div>' +
      '</div>' +
      '</div></div>';

    // 状态文字
    html += '<div style="margin-top:var(--sp-sm);padding:var(--sp-xs);text-align:center;font-size:var(--fs-body);font-weight:600;color:var(--'+(triggered?'danger':'down')+')">'+
      (triggered ? '⚠️ 高潮保护触发' : '✅ 未触发') +
      '</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W07', ClimaxGuardWidget);
