// widgets/style-detect.js — W02 风格检测卡 v2.3 (适配 style_detect V0.3)
'use strict';

class StyleDetectWidget extends YiMuWidget {
  _esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  _formatWanYi(value) {
    var n = Number(value);
    if (!isFinite(n) || n <= 0) return '';
    if (n >= 10000) {
      return (n / 10000).toFixed(2).replace(/\.?0+$/, '') + '万亿';
    }
    return Math.round(n) + '亿';
  }

  _styleTone(mode) {
    if (mode.indexOf('连板') >= 0 && mode.indexOf('趋势') < 0) return 'lb';
    if (mode.indexOf('趋势') >= 0 && mode.indexOf('连板') < 0) return 'tr';
    return 'mixed';
  }

  render(data) {
    var body = this.getBody();
    if (!body) return;
    var esc = this._esc;
    var ST = (data && data.style) || {};
    var meta = (data && data.meta) || {};

    var score = ST['总分'] || 0;
    var mode = ST['风格'] || '—';
    var conf = ST['置信度'] || 0;
    var tone = this._styleTone(mode);
    var toneColor = tone === 'lb' ? 'var(--up-deep)' : (tone === 'tr' ? 'var(--info)' : 'var(--accent-purple)');
    var toneBg = tone === 'lb' ? 'var(--up-bg)' : (tone === 'tr' ? 'var(--info-bg)' : 'var(--accent-purple-bg)');
    var toneBorder = tone === 'lb' ? 'rgba(220,38,38,0.16)' : (tone === 'tr' ? 'rgba(37,99,235,0.16)' : 'rgba(124,58,237,0.16)');
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
    var marketVolume = this._formatWanYi(ST['_iwencai_全市场成交额']);
    var updated = meta.updated ? String(meta.updated).slice(11, 16) : '';

    var html = '';

    // === 顶部：每日基线 + 分数 + 风格标签 ===
    html += '<div class="style-detect-head">' +
      '<div class="style-detect-main">' +
        '<div class="style-detect-label">每日基线' + (updated ? ' · ' + esc(updated) : '') + '</div>' +
        '<div class="style-detect-score-row">' +
          '<span class="style-detect-score" style="color:' + toneColor + '">' + score + '</span>' +
          '<span class="style-chip" style="font-size:var(--fs-body);padding:2px 8px;border-radius:var(--radius-sm);font-weight:700;color:' + toneColor + ';background:' + toneBg + ';border:1px solid ' + toneBorder + ';white-space:nowrap">' + esc(mode) + '</span>' +
        '</div>' +
      '</div>' +
      '<div class="style-detect-side">' +
        '<div>置信 <b style="font-family:var(--font-mono);color:var(--text-secondary)">' + conf + '%</b></div>' +
        (daysInRegime ? '<div>持续 <b style="font-family:var(--font-mono);color:var(--text-secondary)">' + daysInRegime + '</b> 天</div>' : '') +
      '</div>' +
      '</div>';

    // === 分配比例条（trading-core 插值表）===
    html += '<div style="display:flex;height:6px;border-radius:3px;overflow:hidden;margin-bottom:var(--sp-xs)">' +
      '<div style="width:' + lbPct + '%;background:var(--up);min-width:' + (lbPct > 0 ? '2px' : '0') + '"></div>' +
      '<div style="width:' + trPct + '%;background:var(--info);min-width:' + (trPct > 0 ? '2px' : '0') + '"></div>' +
      '</div>' +
      '<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--sp-xs);font-size:var(--fs-body);color:var(--text-secondary);margin-bottom:var(--sp-sm)">' +
      '<span>连板 <b class="up" style="font-family:var(--font-mono)">' + lbPct + '%</b></span>' +
      '<span>趋势 <b class="info" style="font-family:var(--font-mono)">' + trPct + '%</b></span>' +
      '<span style="text-align:right">基线仓位 <b style="font-family:var(--font-mono);color:var(--text-primary)">' + cap + '%</b></span>' +
      '</div>';

    html += '<div style="display:flex;justify-content:space-between;gap:var(--sp-sm);font-size:var(--fs-label);color:var(--text-disabled);margin-bottom:var(--sp-xs)">' +
      '<span>成交额 ' + (marketVolume || '—') + '</span>' +
      '<span>信号强度：连板 ' + lbSignal + ' / 趋势 ' + trSignal + '</span>' +
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
        '<span style="color:var(--up)">' + esc(lbsDesc) + '</span>' +
        '<span style="color:var(--text-disabled)">|</span>' +
        '<span style="color:var(--down)">' + esc(trsDesc) + '</span>' +
        '</div>';
    }

    // === 预警 ===
    warnings.forEach(function(w) {
      html += '<div class="ui-note style-detect-warning"><b>预警</b><span>' + esc(w) + '</span></div>';
    });

    // === 硬卡/熔断（规则引擎判定）===
    var exec = ST['实际执行'] || {};
    if (exec['原因'] || exec['原因2']) {
      html += '<div class="ui-degraded style-detect-exec-block">' +
        '<strong>' + esc(exec['原因']||'执行限制') + '</strong>' +
        (exec['原因2'] ? '<span>' + esc(exec['原因2']) + '</span>' : '') +
        '</div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W02', StyleDetectWidget);
