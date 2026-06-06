// widgets/midday-review.js — W19 午盘复核（V反检测+双冰）v2.0 rule_state 驱动
'use strict';

class MiddayReviewWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var decision = (data && data.decision) || {};
    var mid = decision['盘中'] || {};
    var vRev = mid['V反检测'] || {};
    var RS = (data && data.rule_state) || null;
    var rsBlocks = (RS && RS.blocks) || [];

    // ===== 双冰检测：rule_state DOUBLE_ICE 为唯一权威结论 =====
    var doubleIceBlock = rsBlocks.filter(function(b){ return b.code === 'DOUBLE_ICE'; });

    if (!vRev['场景'] && !doubleIceBlock.length && !RS) {
      body.innerHTML = '<div class="ui-empty"><div class="ui-empty-title">午盘数据待录入</div><div class="ui-empty-detail">等待 V 反检测与 rule_state 复核数据。</div></div>';
      return;
    }

    var html = '';

    // V反检测（保留原有逻辑，来自决策面板录入）
    html += '<div style="padding:var(--sp-sm) var(--sp-md);margin-bottom:var(--sp-sm);background:var(--special-bg);border-radius:var(--radius-md);border:1px solid var(--special)">' +
      '<div style="font-size:var(--fs-body);font-weight:600;color:var(--special);margin-bottom:var(--sp-sm)">V反检测</div>' +
      '<div style="font-size:var(--fs-body);color:var(--text-secondary);margin-bottom:4px">场景：'+(vRev['场景']||'—')+'</div>' +
      '<div style="font-size:var(--fs-subtitle);font-weight:700;color:var(--special)">'+(vRev['当前状态']||'—')+'</div>' +
      (vRev['午盘复核(13:00)'] ? '<div style="margin-top:var(--sp-xs);font-size:var(--fs-body);color:var(--text-secondary)">'+(vRev['午盘复核(13:00)'])+'</div>' : '') +
      '</div>';

    // 双冰检测（来源：rule_state DOUBLE_ICE）
    var dbTriggered = doubleIceBlock.length > 0;
    var dbEvidence = doubleIceBlock.length > 0 ? doubleIceBlock[0].evidence || {} : {};
    var yesterdayMood = dbEvidence.previous_emotion_pct != null ? dbEvidence.previous_emotion_pct : '—';
    var todayMood = dbEvidence.emotion_pct != null ? dbEvidence.emotion_pct : '—';

    html += '<div style="padding:var(--sp-sm) var(--sp-md);background:var(--bg-base);border-radius:var(--radius-md);border:1px solid '+(dbTriggered?'var(--warn)':'var(--border-light)')+'">' +
      '<div style="font-size:var(--fs-body);font-weight:600;color:var(--text-primary);margin-bottom:var(--sp-sm)">双冰检测</div>' +
      '<div style="display:flex;justify-content:space-between;padding:3px 0;font-size:var(--fs-body)">' +
        '<span style="color:var(--text-secondary)">前日情绪</span>' +
        '<span style="font-family:var(--font-mono);font-weight:600;color:'+(yesterdayMood!=='—'&&yesterdayMood<20?'var(--warn)':'var(--text-primary)')+'">'+(yesterdayMood!=='—'?yesterdayMood+'%':'—')+'</span>' +
      '</div>' +
      '<div style="display:flex;justify-content:space-between;padding:3px 0;font-size:var(--fs-body)">' +
        '<span style="color:var(--text-secondary)">今日情绪</span>' +
        '<span style="font-family:var(--font-mono);font-weight:600;color:'+(todayMood!=='—'&&todayMood<20?'var(--warn)':'var(--text-primary)')+'">'+(todayMood!=='—'?todayMood+'%':'—')+'</span>' +
      '</div>' +
      '<div style="margin-top:var(--sp-sm);padding-top:var(--sp-xs);border-top:1px solid var(--border-light);text-align:center;font-size:var(--fs-subtitle);font-weight:700;color:var(--'+(dbTriggered?'warn':RS?'info':'text-disabled')+')">'+
        (RS ? (dbTriggered ? '双冰信号 (rule_state)' : '无双冰 (rule_state)') : '规则状态不可用') +
      '</div>' +
      '<div style="font-size:10px;color:var(--text-disabled);text-align:center;margin-top:2px">来源: '+(RS?'rule_state':'不可确认')+'</div>' +
      '</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W19', MiddayReviewWidget);
