// widgets/climax-guard.js — W07 高潮保护 (v2.0 rule_state 驱动)
'use strict';

class ClimaxGuardWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;

    var RS = (data && data.rule_state) || null;

    // ── rule_state 缺失 → 不可确认 ──
    if (!RS) {
      body.innerHTML = '<div class="ui-degraded"><strong>规则状态不可用</strong><span>缺少 rule_state，高潮保护结论不可确认。</span></div>';
      this.updateTimestamp();
      return;
    }

    var rsBlocks = (RS && RS.blocks) || [];
    var rsWarnings = (RS && RS.warnings) || [];

    // 从 rule_state 提取 CLIMAX_STOP 和 CLIMAX_REDUCE
    var climaxStop = rsBlocks.filter(function(b){ return b.code === 'CLIMAX_STOP'; });
    var climaxReduce = rsWarnings.filter(function(w){ return w.code === 'CLIMAX_REDUCE'; });
    var triggered = climaxStop.length > 0 || climaxReduce.length > 0;

    var level = triggered
      ? (climaxStop.length > 0 ? '高潮保护-全关(≥85%)' : '高潮保护-降半仓(80-85%)')
      : '未触发(<80%)';
    // CLIMAX_REDUCE 是总仓位降半，不是仅 W2
    var w1Status = climaxStop.length > 0 ? '全关' : '正常';
    var w2Status = climaxStop.length > 0 ? '全关' : '正常';
    if (climaxReduce.length > 0) {
      w1Status = '降半仓'; w2Status = '降半仓';
    }

    var html = '';

    // 大号情绪值（来自 sentiment 备用，结论不看本地）
    var S = (data && data.sentiment) || {};
    var auction = (data && data.decision && data.decision['竞价']) || {};
    var moodVal = S['竞价情绪值'] || auction['竞价情绪值'] || (RS && RS.market_regime ? RS.market_regime : '—');

    html += '<div style="text-align:center;padding:var(--sp-sm)">' +
      '<div style="font-family:var(--font-mono);font-size:var(--fs-kpi);font-weight:700;color:'+(triggered?'var(--danger)':'var(--down)')+';line-height:1.2">'+moodVal+'</div>' +
      '<div style="font-size:var(--fs-body);color:var(--text-secondary);margin-top:4px">市场状态</div>' +
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

    // 规则来源标注
    html += '<div style="margin-top:var(--sp-sm);text-align:center;font-size:var(--fs-body);font-weight:600;color:var(--'+(triggered?'danger':'down')+')">'+
      (triggered ? '高潮保护触发' : '高潮未触发') +
      '</div>';
    html += '<div style="font-size:10px;color:var(--text-disabled);text-align:center;margin-top:2px">来源: rule_state</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W07', ClimaxGuardWidget);
