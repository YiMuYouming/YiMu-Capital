// widgets/style-detect.js — W02 风格检测卡 v2.3 (适配 style_detect V0.3)
'use strict';

class StyleDetectWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var ST = (data && data.style) || {};

    var score = ST['总分'] || 0;
    var mode = ST['风格'] || '—';
    var conf = ST['置信度'] || 0;
    var modeCls = mode.indexOf('连板') >= 0 ? 'up'
      : mode.indexOf('趋势') >= 0 ? 'down'
      : 'info';
    var lbPct = ST['连板占比'] || 0;
    var trPct = ST['趋势占比'] || 0;
    var lbSignal = ST['连板信号强度'] || 0;
    var trSignal = ST['趋势信号强度'] || 0;
    var lbsDesc = ST['连板信号描述'] || '';
    var trsDesc = ST['趋势信号描述'] || '';
    var daysInRegime = ST['持续天数'] || 0;
    var cap = ST['总仓位上限'] || 0;
    var jjl1 = ST['一进二晋级率'];
    var jjl2 = ST['二进三晋级率'];
    var jjl3 = ST['三进四晋级率'];
    var warnings = ST['预警'] || [];

    var html = '';

    // === 第一行：分数 + 风格标签 + 置信度 ===
    html += '<div style="display:flex;align-items:baseline;gap:var(--sp-sm);margin-bottom:var(--sp-xs)">' +
      '<span style="font-family:var(--font-mono);font-size:36px;font-weight:700;color:var(--' + modeCls + ');line-height:1">' + score + '</span>' +
      '<span class="tag ' + modeCls + '" style="font-size:var(--fs-body);padding:2px 8px;font-weight:600">' + mode + '</span>' +
      '<span style="font-size:var(--fs-label);color:var(--text-disabled)">置信' + conf + '%</span>' +
      (daysInRegime ? '<span style="font-size:var(--fs-label);color:var(--text-disabled)">· 持续' + daysInRegime + '天</span>' : '') +
      '</div>';

    // === 分配比例条（trading-core 插值表）===
    html += '<div style="display:flex;height:6px;border-radius:3px;overflow:hidden;margin-bottom:var(--sp-xs)">' +
      '<div style="width:' + lbPct + '%;background:var(--up);min-width:' + (lbPct > 0 ? '2px' : '0') + '"></div>' +
      '<div style="width:' + trPct + '%;background:var(--down);min-width:' + (trPct > 0 ? '2px' : '0') + '"></div>' +
      '</div>' +
      '<div style="display:flex;justify-content:space-between;font-size:var(--fs-body);color:var(--text-secondary);margin-bottom:var(--sp-sm)">' +
      '<span>资金：连板 <b class="up" style="font-family:var(--font-mono)">' + lbPct + '%</b></span>' +
      '<span>趋势 <b class="down" style="font-family:var(--font-mono)">' + trPct + '%</b></span>' +
      (cap ? '<span style="font-size:var(--fs-label);color:var(--text-disabled)">仓位上限' + cap + '%</span>' : '') +
      '</div>';

    // === 四维度进度条（V0.3: 25/35/25/15 = 100）===
    var dims = [
      {label:'量能', val:ST['dim1_量能']||0, max:25},
      {label:'连板', val:ST['dim2_连板生态']||0, max:35},
      {label:'趋势', val:ST['dim3_趋势']||0, max:25},
      {label:'情绪', val:ST['dim4_情绪广度']||0, max:15},
    ];
    dims.forEach(function(dim) {
      var pct = Math.min(100, Math.round(dim.val / dim.max * 100));
      var color = dim.val >= dim.max * 0.6 ? 'good' : (dim.val >= dim.max * 0.3 ? 'warn' : 'danger');
      html += '<div style="display:flex;align-items:center;gap:var(--sp-xs);margin-bottom:1px">' +
        '<span style="font-size:var(--fs-body);width:28px;color:var(--text-secondary)">' + dim.label + '</span>' +
        '<div class="progress-bar" style="flex:1"><div class="progress-fill ' + color + '" style="width:' + pct + '%"></div></div>' +
        '<span style="font-family:var(--font-mono);font-size:var(--fs-body);width:32px;text-align:right">' + dim.val + '/' + dim.max + '</span>' +
        '</div>';
    });

    // === 分层晋级率（trading-core 硬卡判定输入）===
    if (jjl1 != null || jjl2 != null || jjl3 != null) {
      html += '<div style="margin-top:var(--sp-sm);padding:var(--sp-xs) var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-sm)">' +
        '<div style="font-size:var(--fs-label);color:var(--text-disabled);margin-bottom:2px">分层晋级率</div>' +
        '<div style="display:flex;gap:var(--sp-sm);font-size:var(--fs-body)">';

      var tiers = [
        {label:'一进二', val:jjl1, gate:15, gateLabel:'15%'},
        {label:'二进三', val:jjl2, gate:20, gateLabel:'20%'},
        {label:'三进四+', val:jjl3, gate:35, gateLabel:'35%'},
      ];
      tiers.forEach(function(t) {
        if (t.val == null) return;
        var pass = t.val >= t.gate;
        html += '<div style="flex:1;text-align:center">' +
          '<div style="font-size:var(--fs-label);color:var(--text-disabled)">' + t.label + '</div>' +
          '<div style="font-family:var(--font-mono);font-weight:600;color:var(--' + (pass ? 'up' : 'danger') + ')">' +
            t.val.toFixed(1) + '%</div>' +
          '<div style="font-size:9px;color:var(--text-disabled)">阈值' + t.gateLabel + '</div>' +
          '</div>';
      });

      html += '</div></div>';
    }

    // === 信号描述（连板/趋势独立判断）===
    if (lbsDesc || trsDesc) {
      html += '<div style="display:flex;gap:var(--sp-xs);margin-top:var(--sp-xs);font-size:var(--fs-label)">' +
        '<span style="color:var(--up)">' + lbsDesc + '</span>' +
        '<span style="color:var(--text-disabled)">|</span>' +
        '<span style="color:var(--down)">' + trsDesc + '</span>' +
        '</div>';
    }

    // === 预警 ===
    warnings.forEach(function(w) {
      html += '<div style="margin-top:var(--sp-xs);padding:var(--sp-xs) var(--sp-sm);background:var(--warn-bg);border:1px solid var(--warn);border-radius:var(--radius-sm);font-size:var(--fs-body);color:var(--warn)">⚠ ' + w + '</div>';
    });

    // === 硬卡/熔断（规则引擎判定）===
    var exec = ST['实际执行'] || {};
    if (exec['原因'] || exec['原因2']) {
      html += '<div style="margin-top:var(--sp-xs);padding:var(--sp-xs) var(--sp-sm);background:var(--danger-bg);border:1px solid var(--danger);border-radius:var(--radius-sm);font-size:var(--fs-body);line-height:1.4">' +
        '<div style="color:var(--danger);font-weight:700">' + (exec['原因']||'') + '</div>' +
        (exec['原因2'] ? '<div style="color:var(--danger);font-size:var(--fs-label);margin-top:1px">' + exec['原因2'] + '</div>' : '') +
        '</div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W02', StyleDetectWidget);
