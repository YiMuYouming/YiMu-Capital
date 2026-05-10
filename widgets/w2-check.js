// widgets/w2-check.js — W09 W2实时观察
'use strict';

class W2CheckWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;

    // 从 manualData 读取用户输入的代码
    var manual = DataStore.manualData.getAll();
    var code1 = manual['W2观察1'] || '';
    var code2 = manual['W2观察2'] || '';

    var html = '';

    // 输入区
    html += '<div style="display:flex;gap:var(--sp-sm);margin-bottom:var(--sp-sm)">' +
      '<div style="flex:1"><input type="text" id="w2_code1" placeholder="代码1" value="'+code1+'" style="width:100%;background:var(--bg-input);border:1px solid var(--border-light);color:var(--text-primary);padding:var(--sp-xs) var(--sp-sm);border-radius:var(--radius-sm);font-size:var(--fs-body);font-family:var(--font-mono)"></div>' +
      '<div style="flex:1"><input type="text" id="w2_code2" placeholder="代码2" value="'+code2+'" style="width:100%;background:var(--bg-input);border:1px solid var(--border-light);color:var(--text-primary);padding:var(--sp-xs) var(--sp-sm);border-radius:var(--radius-sm);font-size:var(--fs-body);font-family:var(--font-mono)"></div>' +
      '<button id="w2_apply" style="background:var(--info);color:#fff;border:none;padding:var(--sp-xs) var(--sp-sm);border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body);white-space:nowrap">确认</button>' +
      '</div>';

    // 数据展示
    var liveQ = (data && data.live_quotes) || {};
    var trendPool = (data && data.trend_pool) || [];

    [code1, code2].forEach(function(code, idx) {
      if (!code) return;
      var q = liveQ[code] || {};
      var poolItem = trendPool.find(function(p) { return p['代码'] === code; });

      // 从 trend_pool 取静态数据
      var name = (poolItem||{})['标的'] || code;
      var ma5 = (poolItem||{})['MA5'] || '—';
      var ma20 = (poolItem||{})['MA20'] || '—';
      var buyPoint = (poolItem||{})['买点'] || '';
      var curPrice = parseFloat(q['最新价']) || parseFloat((poolItem||{})['最新价']) || parseFloat((poolItem||{})['收盘价']) || 0;
      var chg = q['涨幅'] || (poolItem||{})['涨幅'] || '—';
      var volRatio = q['量比'] || (poolItem||{})['量比'] || '—';
      var turnover = q['换手'] || (poolItem||{})['换手'] || '—';

      // 方向色
      var chgNum = parseFloat(String(chg).replace('%','').replace('+',''));
      var chgCls = isNaN(chgNum) ? '' : chgNum > 0 ? 'up' : chgNum < 0 ? 'down' : '';

      html += '<div style="margin-bottom:var(--sp-sm);padding:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md);border-left:3px solid var(--down)">' +
        '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:var(--sp-sm)">' +
          '<span style="font-size:var(--fs-subtitle);font-weight:700">'+name+'</span>' +
          '<span style="font-size:var(--fs-label);color:var(--text-disabled);font-family:var(--font-mono)">'+code+'</span>' +
        '</div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-xs) var(--sp-md);font-size:var(--fs-body)">' +
          '<div style="display:flex;justify-content:space-between"><span style="color:var(--text-secondary)">现价</span><span style="font-family:var(--font-mono);font-weight:600;color:var(--'+chgCls+')">'+(curPrice||'—')+'</span></div>' +
          '<div style="display:flex;justify-content:space-between"><span style="color:var(--text-secondary)">涨幅</span><span style="font-family:var(--font-mono);font-weight:600;color:var(--'+chgCls+')">'+chg+'</span></div>' +
          '<div style="display:flex;justify-content:space-between"><span style="color:var(--text-secondary)">MA5</span><span style="font-family:var(--font-mono);font-weight:600">'+ma5+'</span></div>' +
          '<div style="display:flex;justify-content:space-between"><span style="color:var(--text-secondary)">MA20</span><span style="font-family:var(--font-mono);font-weight:600">'+ma20+'</span></div>' +
          '<div style="display:flex;justify-content:space-between"><span style="color:var(--text-secondary)">量比</span><span style="font-family:var(--font-mono);font-weight:600">'+volRatio+'</span></div>' +
          '<div style="display:flex;justify-content:space-between"><span style="color:var(--text-secondary)">换手</span><span style="font-family:var(--font-mono);font-weight:600">'+turnover+'</span></div>' +
        '</div>' +
        (buyPoint ? '<div style="margin-top:var(--sp-sm);font-size:var(--fs-body);color:var(--text-secondary)"><span style="color:var(--info)">买点：</span>'+buyPoint+'</div>' : '') +
        (ma5 !== '—' && curPrice > 0 ? '<div style="margin-top:2px;font-size:var(--fs-body);color:var(--text-secondary)"><span style="color:var(--warn)">距MA5：</span>'+((curPrice - parseFloat(ma5)) / parseFloat(ma5) * 100).toFixed(2)+'%</div>' : '') +
        '</div>';
    });

    if (!code1 && !code2) {
      html += '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled)">输入代码后点确认</div>';
    }

    body.innerHTML = html;

    // 绑定事件
    var self = this;
    var btn = body.querySelector('#w2_apply');
    if (btn) {
      btn.addEventListener('click', function() {
        var c1 = body.querySelector('#w2_code1').value.trim();
        var c2 = body.querySelector('#w2_code2').value.trim();
        DataStore.manualData.set('W2观察1', c1);
        DataStore.manualData.set('W2观察2', c2);
        self._renderBody();
      });
    }
    [body.querySelector('#w2_code1'), body.querySelector('#w2_code2')].forEach(function(el) {
      if (el) el.addEventListener('keydown', function(e) { if (e.key === 'Enter') btn.click(); });
    });

    this.updateTimestamp();
  }
}

WidgetRegistry.register('W09', W2CheckWidget);
