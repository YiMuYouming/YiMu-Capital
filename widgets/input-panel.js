// widgets/input-panel.js — W16 报数面板 (v2.0: DOM→DataStore.manualData)
'use strict';

class InputPanelWidget extends YiMuWidget {
  constructor(config) {
    super(config);
    this._panelOpen = true;
    this._delegatedBound = false;
    try { this._panelOpen = localStorage.getItem(STORAGE_KEYS.panelOpen) !== '0'; } catch(e) {}
  }

  unmount() {
    this._delegatedBound = false;
    super.unmount();
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

    var pnlLive = (data && data.pnl_live) || {};
    var totalAsset = parseFloat(pnlLive.total_asset) || 0;
    var deposit = parseFloat(pnlLive.total_deposit) || 0;
    var totalReturn = deposit > 0 ? ((totalAsset - deposit) / deposit * 100) : 0;
    var retColor = totalReturn >= 0 ? 'var(--up)' : 'var(--down)';
    html += '<div style="margin-top:var(--sp-xs);padding:6px 10px;background:var(--bg-base);border-radius:var(--radius-sm);display:flex;justify-content:space-between;font-size:var(--fs-body);gap:var(--sp-md)">' +
      '<span><span style="color:var(--text-secondary)">总资产</span> <span style="font-family:var(--font-mono);font-weight:700;font-size:var(--fs-subtitle)">' + totalAsset.toLocaleString() + '</span></span>' +
      '<span><span style="color:var(--text-secondary)">累计入金</span> <span style="font-family:var(--font-mono);font-weight:700;font-size:var(--fs-subtitle)">' + deposit.toLocaleString() + '</span></span>' +
      '<span><span style="color:var(--text-secondary)">累计收益</span> <span style="font-family:var(--font-mono);font-weight:700;font-size:var(--fs-subtitle);color:'+retColor+'">'+(totalReturn>=0?'+':'')+totalReturn.toFixed(2)+'%</span></span></div>';

    html += '<div style="margin-top:var(--sp-sm);display:flex;align-items:center;gap:var(--sp-md)">' +
      '<button class="input-refresh" id="btnRefresh">刷新数据</button>' +
      '<span style="font-size:var(--fs-label);color:var(--text-secondary)" id="lastUpdate">—</span>' +
      '</div>';

    body.innerHTML = html;

    // 事件代理：仅首次 render 绑定，防重复 render 叠加 handler
    if (!this._delegatedBound) {
      this._delegatedBound = true;
      var self = this;
      this._on(body, 'click', function(e) {
        if (e.target && e.target.id === 'btnRefresh') {
          self._saveAndRefresh();
        }
      });

      this._on(body, 'change', function(e) {
        var el = e.target;
        var id = el && el.id;
        if (!id || id.indexOf('in_') !== 0) return;
        if (id === 'in_情绪值_手动覆盖') {
          DataStore.manualData.set('_情绪值_手动覆盖', el.checked ? 'true' : 'false');
          return;
        }
        var fieldKey = id.replace('in_', '');
        DataStore.manualData.set(fieldKey, el.value);
      });

      this._on(body, 'input', function(e) {
        var el = e.target;
        var id = el && el.id;
        if (!id || id.indexOf('in_') !== 0 || id === 'in_情绪值_手动覆盖') return;
        var fieldKey = id.replace('in_', '');
        DataStore.manualData.set(fieldKey, el.value);
      });
    }

    this.updateTimestamp();
  }

  _saveAndRefresh() {
    var fields = ['情绪值','上涨','下跌','涨停收益','连板收益','炸板收益','风险值','晋级率','封板率','涨停家数','跌停家数','赚钱效应','最高板','次高板','梯队'];
    fields.forEach(function(f) {
      var el = document.getElementById('in_'+f);
      if (el) DataStore.manualData.set(f, el.value);
    });
    var overrideCb = document.getElementById('in_情绪值_手动覆盖');
    if (overrideCb) DataStore.manualData.set('_情绪值_手动覆盖', overrideCb.checked ? 'true' : 'false');

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
