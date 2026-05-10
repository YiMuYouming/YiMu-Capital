// widgets/style-detect.js — W02 风格检测卡
'use strict';

class StyleDetectWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var ST = (data && data.style) || {};

    var score = ST['总分'] || 0;
    var mode = ST['风格'] || '—';
    var modeCls = mode === '连板' ? 'up' : mode === '趋势' ? 'down' : 'info';
    var lbPct = ST['连板占比'] || 0;
    var trPct = ST['趋势占比'] || 0;

    var html = '';

    // 紧凑：分数+标签 一行
    html += '<div style="display:flex;align-items:center;gap:var(--sp-sm);margin-bottom:var(--sp-sm)">' +
      '<span style="font-family:var(--font-mono);font-size:36px;font-weight:700;color:var(--' + modeCls + ');line-height:1">' + score + '</span>' +
      '<span class="tag ' + (mode==='连板'?'up':mode==='趋势'?'down':'info') + '" style="font-size:var(--fs-subtitle);padding:2px 10px">' + mode + '</span>' +
      '</div>';

    // 分配比例条
    html += '<div style="display:flex;height:6px;border-radius:3px;overflow:hidden;margin-bottom:var(--sp-xs)">' +
      '<div style="width:'+lbPct+'%;background:var(--up)"></div>' +
      '<div style="width:'+trPct+'%;background:var(--down)"></div>' +
      '</div>' +
      '<div style="display:flex;justify-content:space-between;font-size:var(--fs-label);color:var(--text-secondary);margin-bottom:var(--sp-sm)">' +
      '<span class="up">连板 '+lbPct+'%</span><span class="down">趋势 '+trPct+'%</span>' +
      '</div>';

    // 三维度
    var dims = [
      {label:'量能',val:ST['dim1_量能']||0,max:30},
      {label:'连板',val:ST['dim2_连板生态']||0,max:40},
      {label:'趋势',val:ST['dim3_趋势']||0,max:30},
    ];
    dims.forEach(function(dim) {
      var pct = Math.min(100, Math.round(dim.val / dim.max * 100));
      html += '<div style="display:flex;align-items:center;gap:var(--sp-xs);margin-bottom:1px">' +
        '<span style="font-size:var(--fs-label);text-transform:uppercase;letter-spacing:var(--ls-label);width:24px;color:var(--text-secondary)">'+dim.label+'</span>' +
        '<div class="progress-bar" style="flex:1"><div class="progress-fill '+(dim.val>=dim.max*0.6?'good':'warn')+'" style="width:'+pct+'%"></div></div>' +
        '<span style="font-family:var(--font-mono);font-size:var(--fs-label);width:22px;text-align:right">'+dim.val+'</span>' +
        '</div>';
    });

    // 硬卡/熔断警告
    var exec = ST['实际执行'] || {};
    if (exec['原因'] || exec['原因2']) {
      html += '<div style="margin-top:var(--sp-sm);padding:var(--sp-xs) var(--sp-sm);background:var(--danger-bg);border:1px solid var(--danger);border-radius:var(--radius-sm);font-size:var(--fs-body);line-height:1.4">' +
        '<div style="color:var(--danger);font-weight:700">⚠️ ' + (exec['原因']||'') + '</div>' +
        (exec['原因2'] ? '<div style="color:var(--danger);font-size:var(--fs-label);margin-top:1px">' + exec['原因2'] + '</div>' : '') +
        '</div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W02', StyleDetectWidget);
