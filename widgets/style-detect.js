// widgets/style-detect.js — W02 风格检测卡 (v2.0 新增组件，非迁移)
'use strict';

class StyleDetectWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var ST = (data && data.style) || {};

    var score = ST['总分'] || 0;
    var mode = ST['风格'] || '—';
    var modeCls = mode === '连板' ? 'up' : mode === '趋势' ? 'down' : 'info';

    var html = '';

    // Big score
    html += '<div style="text-align:center;margin-bottom:var(--sp-sm)">' +
      '<div style="font-family:var(--font-mono);font-size:48px;font-weight:700;color:var(--' + modeCls + ')">' + score + '</div>' +
      '<div class="tag ' + (mode==='连板'?'up':mode==='趋势'?'down':'info') + '" style="font-size:var(--fs-subtitle);padding:2px 12px">' + mode + '</div>' +
      '</div>';

    // Three-dim bar chart
    var dims = [
      {label:'量能',val:ST['dim1_量能']||0,pct:30},
      {label:'连板',val:ST['dim2_连板生态']||0,pct:40},
      {label:'趋势',val:ST['dim3_趋势']||0,pct:30},
    ];

    html += '<div style="margin-bottom:var(--sp-sm)">';
    dims.forEach(function(dim) {
      html += '<div style="display:flex;align-items:center;gap:var(--sp-sm);margin-bottom:2px">' +
        '<span style="font-size:var(--fs-label);text-transform:uppercase;letter-spacing:var(--ls-label);width:28px">'+dim.label+'</span>' +
        '<div class="progress-bar" style="flex:1"><div class="progress-fill '+(dim.val>=dim.pct?'good':'warn')+'" style="width:'+Math.min(100,dim.val)+'%"></div></div>' +
        '<span style="font-family:var(--font-mono);font-size:var(--fs-body);width:30px">'+dim.val+'</span>' +
        '</div>';
    });
    html += '</div>';

    // Allocation bar
    var lbPct = ST['连板占比'] || 0;
    var trPct = ST['趋势占比'] || 0;
    html += '<div style="display:flex;height:6px;border-radius:3px;overflow:hidden;margin-bottom:var(--sp-sm)">' +
      '<div style="width:'+lbPct+'%;background:var(--up)"></div>' +
      '<div style="width:'+trPct+'%;background:var(--down)"></div>' +
      '</div>' +
      '<div style="display:flex;justify-content:space-between;font-size:var(--fs-label);color:var(--text-secondary)">' +
      '<span class="up">连板 '+lbPct+'%</span>' +
      '<span class="down">趋势 '+trPct+'%</span>' +
      '</div>';

    // Hard block warning
    var exec = ST['实际执行'] || {};
    if (exec['原因']) {
      html += '<div style="margin-top:var(--sp-sm);padding:var(--sp-sm);background:var(--danger-bg);border-radius:var(--radius-sm);font-size:var(--fs-label);color:var(--danger)">' +
        '⚠️ ' + exec['原因'] + '</div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W02', StyleDetectWidget);
