// widgets/input-panel.js — W16 报数面板 (v2.0: DOM→DataStore.manualData)
'use strict';

class InputPanelWidget extends YiMuWidget {
  constructor(config) {
    super(config);
    this._panelOpen = true;
    try { this._panelOpen = localStorage.getItem(STORAGE_KEYS.panelOpen) !== '0'; } catch(e) {}
  }

  mount(container) {
    super.mount(container);
    // 恢复折叠状态
    var body = this.getBody();
    if (body && !this._panelOpen) body.style.display = 'none';
  }

  render(data) {
    var body = this.getBody();
    if (!body) return;

    var fields = [
      {id:'可用资金',type:'number',label:'可用资金(元)'},
      {id:'累计入金',type:'number',label:'累计入金(元)'},
      {id:'情绪值',type:'number',label:'情绪值(%)'},
      {id:'上涨',type:'number',label:'上涨家数'},
      {id:'下跌',type:'number',label:'下跌家数'},
      {id:'涨停收益',type:'text',label:'涨停收益(%)'},
      {id:'连板收益',type:'text',label:'连板收益(%)'},
      {id:'炸板收益',type:'text',label:'炸板收益(%)'},
      {id:'风险值',type:'text',label:'连板风险值'},
      {id:'晋级率',type:'text',label:'晋级率(%)'},
      {id:'封板率',type:'text',label:'封板率(%)'},
      {id:'涨停家数',type:'number',label:'涨停家数'},
      {id:'跌停家数',type:'number',label:'跌停家数'},
      {id:'赚钱效应',type:'select',label:'赚钱效应',opts:['','好','一般','差']},
      {id:'最高板',type:'text',label:'最高板'},
      {id:'次高板',type:'text',label:'次高板'},
      {id:'梯队',type:'text',label:'连板梯队'},
    ];

    var manual = DataStore.manualData.getAll();

    var html = '<div class="input-grid">';
    fields.forEach(function(f) {
      html += '<div class="input-group"><label for="in_'+f.id+'">'+f.label+'</label>';
      if (f.type === 'select') {
        html += '<select id="in_'+f.id+'">';
        (f.opts||[]).forEach(function(o) {
          html += '<option value="'+o+'"'+(String(manual[f.id]||'')===o?' selected':'')+'>'+o+'</option>';
        });
        html += '</select>';
      } else {
        html += '<input type="'+f.type+'" id="in_'+f.id+'" value="'+(manual[f.id]||'')+'">';
      }
      // 情绪值手动覆盖开关
      if (f.id === '情绪值') {
        var checked = manual['_情绪值_手动覆盖'] === 'true' ? ' checked' : '';
        html += '<label class="manual-override-label"><input type="checkbox" id="in_情绪值_手动覆盖"'+checked+'> 手动覆盖自动计算</label>';
      }
      html += '</div>';
    });
    html += '</div>';

    // 自动计算的 总资产 = 持仓市值 + 可用资金
    var afAuto = parseFloat(manual['可用资金']) || 0;
    var mv = 0;
    try {
      var pos = JSON.parse(manual['_positions'] || 'null');
      if (!pos || !pos.length) {
        var merged = DataStore.merged || {};
        pos = merged.positions || [];
      }
      (pos || []).forEach(function(p) {
        if ((p['状态']||'').indexOf('清')>=0 || (p['状态']||'').indexOf('删除')>=0) return;
        var qty = parseFloat(String(p['数量']||'0').replace('股','')) || 0;
        var pr = parseFloat(p['现价']) || parseFloat(p['成本']) || 0;
        mv += Math.round(qty * pr);
      });
    } catch(e) {}
    var totalAsset = afAuto + mv;
    var totalPnL = parseFloat(manual['总盈亏']) || 0;
    var pnlColor = totalPnL >= 0 ? 'var(--up)' : 'var(--down)';
    html += '<div style="margin-top:var(--sp-xs);padding:6px 10px;background:var(--bg-base);border-radius:var(--radius-sm);display:flex;justify-content:space-between;font-size:var(--fs-body);gap:var(--sp-md)">' +
      '<span><span style="color:var(--text-secondary)">总资产</span> <span style="font-family:var(--font-mono);font-weight:700;font-size:var(--fs-subtitle)">' + totalAsset.toLocaleString() + '</span></span>' +
      '<span><span style="color:var(--text-secondary)">总盈亏</span> <span style="font-family:var(--font-mono);font-weight:700;font-size:var(--fs-subtitle);color:'+pnlColor+'">'+(totalPnL>=0?'+':'')+totalPnL.toLocaleString()+'</span></span></div>';

    html += '<div style="margin-top:var(--sp-sm);display:flex;align-items:center;gap:var(--sp-md)">' +
      '<button class="input-refresh" id="btnRefresh">刷新数据</button>' +
      '<span style="font-size:var(--fs-label);color:var(--text-secondary)" id="lastUpdate">—</span>' +
      '</div>';

    body.innerHTML = html;

    // Bind events
    var self = this;
    var refreshBtn = body.querySelector('#btnRefresh');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', function() { self._saveAndRefresh(); });
    }

    fields.forEach(function(f) {
      var el = body.querySelector('#in_'+f.id);
      if (el) {
        el.addEventListener('change', function() {
          DataStore.manualData.set(f.id, el.value);
        });
        el.addEventListener('input', function() {
          DataStore.manualData.set(f.id, el.value);
        });
      }
    });

    // 情绪值手动覆盖 checkbox
    var overrideCb = body.querySelector('#in_情绪值_手动覆盖');
    if (overrideCb) {
      overrideCb.addEventListener('change', function() {
        DataStore.manualData.set('_情绪值_手动覆盖', overrideCb.checked ? 'true' : 'false');
      });
    }

    this.updateTimestamp();
  }

  _saveAndRefresh() {
    var fields = ['可用资金','情绪值','上涨','下跌','涨停收益','连板收益','炸板收益','风险值','晋级率','封板率','涨停家数','跌停家数','赚钱效应','最高板','次高板','梯队','累计入金'];
    fields.forEach(function(f) {
      var el = document.getElementById('in_'+f);
      if (el) DataStore.manualData.set(f, el.value);
    });
    var overrideCb = document.getElementById('in_情绪值_手动覆盖');
    if (overrideCb) DataStore.manualData.set('_情绪值_手动覆盖', overrideCb.checked ? 'true' : 'false');

    // 总资产 = 持仓市值 + 可用资金（自动计算）
    var afAuto = parseFloat(document.getElementById('in_可用资金')?.value) || 0;
    var mv = 0;
    try {
      var pos = JSON.parse(DataStore.manualData.getAll()['_positions'] || 'null');
      if (!pos || !pos.length) { var m = DataStore.merged || {}; pos = (m && m.positions) || []; }
      (pos || []).forEach(function(p) {
        if ((p['状态']||'').indexOf('清')>=0 || (p['状态']||'').indexOf('删除')>=0) return;
        var qty = parseFloat(String(p['数量']||'0').replace('股','')) || 0;
        var pr = parseFloat(p['现价']) || parseFloat(p['成本']) || 0;
        mv += Math.round(qty * pr);
      });
    } catch(e) {}
    var totalAsset = afAuto + mv;
    DataStore.manualData.set('总资产', totalAsset);

    _bridgeSyncPnl(totalAsset,
      parseFloat(document.getElementById('in_累计入金')?.value) || 0
    );

    DataStore.merge();
    DataStore.notifyAll();

    var ts = document.getElementById('lastUpdate');
    if (ts) ts.textContent = '✓ 已更新 ' + new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
  }

  _togglePanel() {
    var body = this.getBody();
    if (!body) return;
    this._panelOpen = !this._panelOpen;
    body.style.display = this._panelOpen ? '' : 'none';
    try { localStorage.setItem(STORAGE_KEYS.panelOpen, this._panelOpen?'1':'0'); } catch(e) {}
  }
}

WidgetRegistry.register('W16', InputPanelWidget);

function _bridgeSyncPnl(asset, deposit) {
  if (location.protocol === 'file:') return;
  try {
    fetch('/api/sync', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ pnl: { 总资产: asset, 累计入金: deposit } })
    }).catch(function(){});
  } catch(e) {}
}
