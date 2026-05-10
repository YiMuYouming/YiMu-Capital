// widgets/w2-check.js — W09 W2实时观察（实时条件判定）
'use strict';

function autoEvalW2(check, data) {
  var name = check['指标'] || '';
  var code = check['代码'] || '';
  var liveQ = (data && data.live_quotes && data.live_quotes[code]) || {};
  var li = (data && data.live_index) || {};

  // 大盘方向
  if (name.indexOf('大盘') >= 0) {
    var szChg = parseFloat(String(li['上证涨幅']||'0').replace('%','').replace('+',''));
    if (!isNaN(szChg) && szChg > 0) return { status: 'pass', verdict: '上证 '+li['上证涨幅']+' 站20日线 ✅' };
    else if (!isNaN(szChg)) return { status: 'fail', verdict: '上证 '+li['上证涨幅']+' ❌' };
  }

  // 板块状态
  if (name.indexOf('板块') >= 0 && code) {
    var sectorData = (data && data.live_sectors) || {};
    // 从 pool 中找板块名
    var poolItem = (data && data.trend_pool || []).find(function(p) { return p['代码'] === code; });
    var sector = sectorData[(poolItem||{})['板块']] || {};
    var scChg = parseFloat(sector['涨跌幅']) || 0;
    var ma5Status = sector['5日线'] || '—';
    if (scChg > 0 && ma5Status === '站上') return { status: 'pass', verdict: '板块涨 '+scChg.toFixed(1)+'% 站5日线 ✅' };
    else if (scChg > 0) return { status: 'pending', verdict: '板块涨 '+scChg.toFixed(1)+'% 5日线待确认 ⏳' };
    else return { status: 'fail', verdict: '板块 '+scChg.toFixed(1)+'% ❌' };
  }

  // 个股回踩
  if (name.indexOf('回踩') >= 0 && code) {
    var curPrice = parseFloat(liveQ['最新价']) || 0;
    var ma5 = parseFloat((data && data.trend_pool || []).find(function(p){return p['代码']===code;})||{}).MA5 || 0;
    var volRatio = parseFloat(liveQ['量比']) || 99;
    if (curPrice > 0 && ma5 > 0) {
      var dist = (curPrice - ma5) / ma5 * 100;
      var shrink = volRatio < 1;
      if (dist <= 2 && shrink) return { status: 'pass', verdict: '距MA5 '+dist.toFixed(1)+'% 缩量 ✅' };
      else if (dist <= 2) return { status: 'pending', verdict: '距MA5 '+dist.toFixed(1)+'% 量比'+volRatio+' ⏳' };
      else return { status: 'pending', verdict: '距MA5 '+dist.toFixed(1)+'% 等回踩 ⏳' };
    }
  }

  return null;
}

class W2CheckWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;

    var decision = (data && data.decision) || {};
    var mid = decision['盘中'] || {};
    var liveQ = (data && data.live_quotes) || {};
    var trendPool = (data && data.trend_pool) || [];
    var manual = DataStore.manualData.getAll();

    var html = '';

    // 上半部：条件清单（实时判定）
    var checks = mid['W2出手条件'] || mid['条件列表'] || [];
    if (checks.length) {
      var passCount = 0, failCount = 0, pendingCount = 0;
      var evaluated = checks.map(function(c) {
        var result = autoEvalW2(c, data);
        var status = result ? result.status : c['状态'];
        var verdict = result ? result.verdict : (c['判定']||'').replace(/[✅❌⏳]+$/g,'').trim();
        if (status === 'pass') passCount++;
        else if (status === 'fail') failCount++;
        else pendingCount++;
        return { label: c['指标'], verdict: verdict, status: status, auto: !!result };
      });

      var allPass = failCount===0 && pendingCount===0;
      var hasFail = failCount > 0;

      var statusText, statusColor;
      if (allPass)      { statusText = '✅ '+passCount+'/'+checks.length+' 条件通过 — W2可吸'; statusColor = 'var(--down)'; }
      else if (hasFail) { statusText = '❌ '+failCount+'项不满足 — W2关闭'; statusColor = 'var(--danger)'; }
      else              { statusText = '⏳ '+passCount+'/'+checks.length+' 通过，'+pendingCount+'项待确认 — 等待企稳'; statusColor = 'var(--warn)'; }

      html += '<div style="padding:var(--sp-sm) var(--sp-md);margin-bottom:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md)">' +
        '<div style="font-size:var(--fs-subtitle);font-weight:700;color:'+statusColor+';margin-bottom:var(--sp-xs)">'+statusText+'</div>' +
        '<div style="font-size:var(--fs-body);color:var(--text-secondary);margin-bottom:var(--sp-sm)">'+(mid['W2出手时机']||'')+'</div>';

      evaluated.forEach(function(c) {
        var icon = c.status==='pass'?'✅':c.status==='fail'?'❌':'⏳';
        html += '<div style="display:flex;align-items:center;gap:var(--sp-sm);padding:2px 0;font-size:var(--fs-body)">' +
          '<span style="width:20px">'+icon+'</span>' +
          '<span style="flex:1">'+c.label+(c.auto?' <span style=\"font-size:var(--fs-label);color:var(--info)\">实时</span>':'')+'</span>' +
          '<span style="color:var(--text-secondary)">'+c.verdict+'</span></div>';
      });

      html += '</div>';
    }

    // 下半部：实时观察
    var codes = [manual['W2观察1']||'', manual['W2观察2']||'', manual['W2观察3']||''];

    html += '<div style="display:flex;gap:var(--sp-sm);margin-bottom:var(--sp-sm)">' +
      codes.map(function(c,i) { return '<input type="text" id="w2_code'+(i+1)+'" placeholder="代码'+(i+1)+'" value="'+c+'" style="flex:1;min-width:0;background:var(--bg-input);border:1px solid var(--border-light);color:var(--text-primary);padding:2px var(--sp-sm);border-radius:var(--radius-sm);font-size:var(--fs-body);font-family:var(--font-mono)">'; }).join('') +
      '<button id="w2_apply" style="background:var(--info);color:#fff;border:none;padding:2px var(--sp-sm);border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body);white-space:nowrap">确认</button>' +
      '</div>';

    codes.forEach(function(code) {
      if (!code) return;
      var q = liveQ[code] || {};
      var poolItem = trendPool.find(function(p) { return p['代码'] === code; });
      var name = (poolItem||{})['标的'] || code;
      var curPrice = parseFloat(q['最新价']) || parseFloat((poolItem||{})['最新价']) || 0;
      var chg = q['涨幅'] || (poolItem||{})['涨幅'] || '—';
      var chgNum = parseFloat(String(chg).replace('%','').replace('+',''));
      var chgCls = isNaN(chgNum) ? '' : chgNum>0?'up':chgNum<0?'down':'';

      html += '<div style="padding:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md);border-left:3px solid var(--down);margin-bottom:var(--sp-sm)">' +
        '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px">' +
          '<span style="font-size:var(--fs-subtitle);font-weight:700">'+name+'</span>' +
          '<span style="font-size:var(--fs-label);color:var(--text-disabled);font-family:var(--font-mono)">'+code+'</span></div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:2px var(--sp-md);font-size:var(--fs-body)">' +
          '<div><span style="color:var(--text-secondary)">现价</span> <span style="font-family:var(--font-mono);font-weight:600;color:var(--'+chgCls+')">'+(curPrice||'—')+'</span></div>' +
          '<div><span style="color:var(--text-secondary)">涨幅</span> <span style="font-family:var(--font-mono);font-weight:600;color:var(--'+chgCls+')">'+chg+'</span></div>' +
          '<div><span style="color:var(--text-secondary)">量比</span> <span style="font-family:var(--font-mono);font-weight:600">'+(q['量比']||(poolItem||{})['量比']||'—')+'</span></div>' +
          '<div><span style="color:var(--text-secondary)">换手</span> <span style="font-family:var(--font-mono);font-weight:600">'+(q['换手']||(poolItem||{})['换手']||'—')+'</span></div>' +
        '</div></div>';
    });

    body.innerHTML = html;

    var self = this, btn = body.querySelector('#w2_apply');
    if (btn) btn.addEventListener('click', function() {
      for (var i=1; i<=3; i++) DataStore.manualData.set('W2观察'+i, (body.querySelector('#w2_code'+i)||{}).value||'');
      self._renderBody();
    });
    for (var i=1; i<=3; i++) {
      var el = body.querySelector('#w2_code'+i);
      if (el) el.addEventListener('keydown', function(e) { if (e.key==='Enter'&&btn) btn.click(); });
    }

    this.updateTimestamp();
  }
}

WidgetRegistry.register('W09', W2CheckWidget);
