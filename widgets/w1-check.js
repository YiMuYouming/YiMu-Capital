// widgets/w1-check.js — W08 W1早盘确认（对齐W09动态标题）
'use strict';

class W1CheckWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var decision = (data && data.decision) || {};
    var morning = decision['早盘'] || {};

    var checks = morning['方向确认'] || morning['条件列表'] || [];
    if (!checks.length) {
      body.innerHTML = '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled)">早盘数据待录入</div>';
      return;
    }

    // 统计
    var passCount = 0, failCount = 0, pendingCount = 0;
    checks.forEach(function(c) {
      if (c['状态']==='pass') passCount++;
      else if (c['状态']==='fail') failCount++;
      else pendingCount++;
    });
    var allPass = failCount===0 && pendingCount===0;
    var hasFail = failCount > 0;
    var hasPending = pendingCount > 0;

    // 动态标题
    var statusText, statusColor;
    if (allPass)      { statusText = '✅ '+passCount+'/'+checks.length+' 确认通过 — W1可追'; statusColor = 'var(--up)'; }
    else if (hasFail) { statusText = '❌ '+failCount+'项不满足，'+passCount+'/'+checks.length+' 通过 — W1关闭'; statusColor = 'var(--danger)'; }
    else              { statusText = '⏳ '+passCount+'/'+checks.length+' 通过，'+pendingCount+'项待确认 — 等待确认'; statusColor = 'var(--warn)'; }

    var html = '';

    html += '<div style="padding:var(--sp-sm) var(--sp-md);margin-bottom:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md)">' +
      '<div style="font-size:var(--fs-subtitle);font-weight:700;color:'+statusColor+';margin-bottom:var(--sp-xs)">'+statusText+'</div>' +
      '<div style="font-size:var(--fs-body);color:var(--text-secondary);margin-bottom:var(--sp-sm)">'+(morning['W1出手条件']||'')+'</div>';

    checks.forEach(function(c) {
      var icon = c['状态']==='pass'?'✅':c['状态']==='fail'?'❌':'⏳';
      var verdict = (c['判定']||'').replace(/[✅❌⏳]+$/g,'').trim();
      html += '<div style="display:flex;align-items:center;gap:var(--sp-sm);padding:2px 0;font-size:var(--fs-body)">' +
        '<span style="width:20px">'+icon+'</span>' +
        '<span style="flex:1">'+c['指标']+'</span>' +
        '<span style="color:var(--text-secondary)">'+verdict+'</span></div>';
    });

    html += '</div>';

    // ===== 下半部：实时观察 =====
    var manual = DataStore.manualData.getAll();
    var liveQ = (data && data.live_quotes) || {};
    var lianbanPool = (data && data.lianban_pool) || [];
    var codes = [manual['W1观察1']||'', manual['W1观察2']||'', manual['W1观察3']||''];

    html += '<div style="display:flex;gap:var(--sp-sm);margin-bottom:var(--sp-sm)">' +
      codes.map(function(c,i) { return '<input type="text" id="w1_code'+(i+1)+'" placeholder="代码'+(i+1)+'" value="'+c+'" style="flex:1;min-width:0;background:var(--bg-input);border:1px solid var(--border-light);color:var(--text-primary);padding:2px var(--sp-sm);border-radius:var(--radius-sm);font-size:var(--fs-body);font-family:var(--font-mono)">'; }).join('') +
      '<button id="w1_apply" style="background:var(--info);color:#fff;border:none;padding:2px var(--sp-sm);border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body);white-space:nowrap">确认</button>' +
      '</div>';

    var hasData = false;
    codes.forEach(function(code) {
      if (!code) return;
      var q = liveQ[code] || {};
      var poolItem = lianbanPool.find(function(p) { return p['代码'] === code; });
      var name = (poolItem||{})['标的'] || code;
      var curPrice = parseFloat(q['最新价']) || parseFloat((poolItem||{})['最新价']) || parseFloat((poolItem||{})['收盘价']) || 0;
      var chg = q['涨幅'] || (poolItem||{})['涨幅'] || '—';
      var chgNum = parseFloat(String(chg).replace('%','').replace('+',''));
      var chgCls = isNaN(chgNum) ? '' : chgNum>0?'up':chgNum<0?'down':'';

      hasData = true;
      html += '<div style="padding:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md);border-left:3px solid var(--up);margin-bottom:var(--sp-sm)">' +
        '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px">' +
          '<span style="font-size:var(--fs-subtitle);font-weight:700">'+name+'</span>' +
          '<span style="font-size:var(--fs-label);color:var(--text-disabled);font-family:var(--font-mono)">'+code+'</span></div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:2px var(--sp-md);font-size:var(--fs-body)">' +
          '<div style="display:flex;justify-content:space-between"><span style="color:var(--text-secondary)">现价</span><span style="font-family:var(--font-mono);font-weight:600;color:var(--'+chgCls+')">'+(curPrice||'—')+'</span></div>' +
          '<div style="display:flex;justify-content:space-between"><span style="color:var(--text-secondary)">涨幅</span><span style="font-family:var(--font-mono);font-weight:600;color:var(--'+chgCls+')">'+chg+'</span></div>' +
          '<div style="display:flex;justify-content:space-between"><span style="color:var(--text-secondary)">量比</span><span style="font-family:var(--font-mono);font-weight:600">'+(q['量比']||(poolItem||{})['量比']||'—')+'</span></div>' +
          '<div style="display:flex;justify-content:space-between"><span style="color:var(--text-secondary)">换手</span><span style="font-family:var(--font-mono);font-weight:600">'+(q['换手']||(poolItem||{})['换手']||'—')+'</span></div>' +
        '</div></div>';
    });

    if (!hasData) {
      html += '<div style="padding:var(--sp-sm);text-align:center;color:var(--text-disabled);font-size:var(--fs-body)">输入代码后点确认</div>';
    }

    body.innerHTML = html;

    // 事件
    var self = this;
    var btn = body.querySelector('#w1_apply');
    if (btn) btn.addEventListener('click', function() {
      for (var i=1; i<=3; i++) {
        DataStore.manualData.set('W1观察'+i, (body.querySelector('#w1_code'+i)||{}).value||'');
      }
      self._renderBody();
    });
    for (var i=1; i<=3; i++) {
      var el = body.querySelector('#w1_code'+i);
      if (el) el.addEventListener('keydown', function(e) { if (e.key==='Enter'&&btn) btn.click(); });
    }

    this.updateTimestamp();
  }
}

WidgetRegistry.register('W08', W1CheckWidget);
