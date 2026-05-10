// widgets/climax-guard.js — W07 高潮保护 (v2.0: 统一竞价情绪值)
'use strict';

class ClimaxGuardWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;

    var S = (data && data.sentiment) || {};
    var auction = (data && data.decision && data.decision['竞价']) || {};
    var moodVal = S['竞价情绪值'] || auction['竞价情绪值'] || '—';
    var moodNum = parseFloat(moodVal) || 0;

    var level = '';
    var w1Status = '正常';
    var w2Status = '正常';
    var triggered = false;

    if (moodNum >= 90) { level = '一级保护(≥90%)'; w1Status = '全关'; w2Status = '全关'; triggered = true; }
    else if (moodNum >= 85) { level = '二级保护(85-90%)'; w1Status = '全关'; w2Status = '降半仓'; triggered = true; }
    else if (moodNum >= 80) { level = '三级保护(80-85%)'; w1Status = '降半仓'; w2Status = '正常'; triggered = true; }
    else { level = '未触发(<80%)'; }

    var html = '';
    html += '<div style="text-align:center;padding:var(--sp-sm)">' +
      '<div style="font-family:var(--font-mono);font-size:32px;font-weight:700;color:' + (triggered?'var(--danger)':'var(--down)') + '">' + moodVal + '</div>' +
      '<div style="font-size:var(--fs-label);color:var(--text-secondary);margin-top:2px">竞价情绪值</div>' +
      '</div>';

    html += '<div style="margin-top:var(--sp-sm)">' +
      '<div class="kpi-card" style="margin-bottom:var(--sp-xs)"><div class="kpi-label">保护级别</div><div class="kpi-verdict ' + (triggered?'danger':'info') + '">' + level + '</div></div>' +
      '<div style="display:flex;gap:var(--sp-xs)">' +
      '<div class="kpi-card" style="flex:1"><div class="kpi-label">W1</div><div class="kpi-verdict ' + (w1Status==='正常'?'info':'danger') + '">' + w1Status + '</div></div>' +
      '<div class="kpi-card" style="flex:1"><div class="kpi-label">W2</div><div class="kpi-verdict ' + (w2Status==='正常'?'info':'danger') + '">' + w2Status + '</div></div>' +
      '</div></div>';

    if (triggered) {
      html += '<div style="margin-top:var(--sp-sm);padding:var(--sp-sm);background:var(--danger-bg);border-radius:var(--radius-sm);font-size:var(--fs-label);color:var(--danger);text-align:center">⚠️ 高潮保护触发</div>';
    } else {
      html += '<div style="margin-top:var(--sp-sm);font-size:var(--fs-label);color:var(--down);text-align:center">✅ 未触发</div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W07', ClimaxGuardWidget);
