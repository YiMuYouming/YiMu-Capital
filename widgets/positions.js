// widgets/positions.js — W15 持仓+记流水+清仓 v3.0
'use strict';

class PositionsWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var manual = DataStore.manualData.getAll();
    var liveQ = (data && data.live_quotes) || {};

    // === 持仓（manualData 优先，附录兜底）===
    var basePos = JSON.parse(JSON.stringify((data && data.positions) || []));
    basePos.forEach(function(p) { if (!p['数量']) p['数量'] = 0; });

    var P = basePos;
    try {
      var mp = JSON.parse(manual['_positions'] || 'null');
      if (mp && mp.length) {
        var merged = false;
        mp.forEach(function(m) {
          var idx = P.findIndex(function(p) { return p['标的'] === m['标的']; });
          if (idx >= 0) { P[idx] = m; merged = true; }
          else { P.push(m); merged = true; }
        });
        if (!merged) P = basePos;
      }
    } catch(e) {}

    // 注入实时现价
    P.forEach(function(p) {
      var q = liveQ[p['代码']] || {};
      var livePrice = parseFloat(q['最新价']) || 0;
      if (livePrice > 0) p['现价'] = livePrice;
    });

    var ops = [];
    try { ops = JSON.parse(manual['_今日操作'] || '[]'); } catch(e) {}

    var active = [], cleared = [];
    P.forEach(function(p) {
      if ((p['状态']||'').indexOf('删除')>=0) return;  // 跳过已删除
      if ((p['状态']||'').indexOf('清')>=0) cleared.push(p); else active.push(p);
    });

    active.forEach(function(p) {
      var qty = parseFloat(String(p['数量']||'0').replace('股',''))||0;
      var pr = parseFloat(p['现价'])||0, c = parseFloat(p['成本'])||0;
      p['_qty'] = qty;
      p['_mv'] = Math.round(pr*qty); p['_pnl'] = Math.round((pr-c)*qty);
      p['_pct'] = c>0?((pr-c)/c*100):0;
    });

    var html = '';

    // 汇总卡片
    var ta = parseFloat(manual['总资产'])||0;
    var pv=0, pc=0; active.forEach(function(p){pv+=p['_mv']||0;pc+=Math.round((parseFloat(p['成本'])||0)*(p['_qty']||0));});
    var tp = pv - pc;
    var af = (manual['可用资金']!=null) ? parseFloat(manual['可用资金']) : ta-pv;
    if (!ta || ta <= 0) ta = pv + af;
    var tc=tp>0?'up':tp<0?'down':'', pp=pc>0?(tp/pc*100):0, pr=ta>0?Math.round(pv/ta*100):0;

    html += '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:var(--sp-xs) var(--sp-sm);margin-bottom:var(--sp-md);padding:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md);font-size:var(--fs-body)">'+
      '<div style="text-align:center"><div class="kpi-label">总资产</div><div style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700">'+ta.toLocaleString()+'</div></div>'+
      '<div style="text-align:center"><div class="kpi-label">持仓市值</div><div style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700">'+pv.toLocaleString()+'</div></div>'+
      '<div style="text-align:center"><div class="kpi-label">总盈亏</div><div style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700;color:var(--'+tc+')">'+(tp>=0?'+':'')+tp.toFixed(2)+'</div></div>'+
      '<div style="text-align:center"><div class="kpi-label">总盈亏%</div><div style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700;color:var(--'+tc+')">'+(pp>=0?'+':'')+pp.toFixed(2)+'%</div></div>'+
      '<div style="text-align:center"><div class="kpi-label">可用资金</div><div style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700">'+af.toLocaleString()+'</div></div>'+
      '<div style="text-align:center"><div class="kpi-label">仓位</div><div style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700;color:'+(pr>80?'var(--danger)':pr>50?'var(--warn)':'var(--info)')+'">'+pr+'%</div></div>'+
      '</div>';

    // ===== 持仓 =====
    html += '<div style="font-size:var(--fs-body);font-weight:600;margin-bottom:var(--sp-xs)">持仓 <span style="font-weight:400;color:var(--text-disabled)">（点✎编辑 / 删除）</span></div>';
    if (active.length) {
      html += '<table class="data-table"><thead><tr><th>标的</th><th>市值</th><th>数量</th><th>现价</th><th>成本</th><th>盈亏</th><th>盈亏%</th><th>止损</th><th></th></tr></thead><tbody>';
      active.forEach(function(p, pi) {
        var pc=(p['_pnl']||0)>0?'up':(p['_pnl']||0)<0?'down':'', pt=(p['_pct']||0)>0?'up':(p['_pct']||0)<0?'down':'';
        html += '<tr><td style="font-size:var(--fs-body);font-weight:600">'+(p['标的']||'—')+' <span style="font-size:var(--fs-label);color:var(--text-disabled)">'+(p['代码']||'')+'</span></td>'+
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">'+(p['_mv']||0).toLocaleString()+'</td>'+
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+(p['_qty']||0).toLocaleString()+'</td>'+
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+(p['现价']||'—')+'</td>'+
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono);color:var(--text-secondary)">'+(p['成本']||'—')+'</td>'+
          '<td class="'+pc+'" style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">'+(p['_pnl']>=0?'+':'')+(p['_pnl']||0).toLocaleString()+'</td>'+
          '<td class="'+pt+'" style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">'+(p['_pct']>=0?'+':'')+(p['_pct']||0).toFixed(2)+'%</td>'+
          '<td style="font-size:var(--fs-body)">'+(p['止损']||'—')+'</td>'+
          '<td><button class="w15_pos_edit" data-pidx="'+pi+'" style="background:none;border:none;color:var(--info);cursor:pointer;font-size:var(--fs-body)" title="编辑">✎</button></td></tr>';
      });
      html += '</tbody></table>';
    } else { html += '<div style="padding:var(--sp-sm);text-align:center;color:var(--text-disabled);font-size:var(--fs-body)">空仓</div>'; }

    // ===== 今日记录 =====
    html += '<div style="display:flex;align-items:center;gap:var(--sp-sm);margin-top:var(--sp-md);margin-bottom:var(--sp-xs)">'+
      '<span style="font-size:var(--fs-body);font-weight:600">今日记录</span>'+
      '<button id="w15_add" style="background:var(--info);color:var(--text-inverse);border:none;padding:2px 10px;border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body);font-family:var(--font-sans)">记流水</button></div>';

    if (ops.length) {
      html += '<table class="data-table"><thead><tr><th>时间</th><th>动作</th><th>标的</th><th>代码</th><th>价格</th><th>数量</th><th>窗口</th><th>原因</th><th></th></tr></thead><tbody>';
      ops.forEach(function(o, i) {
        var act=o['动作']||'—', isBuy=act.indexOf('买入')>=0||act.indexOf('追')>=0;
        html += '<tr><td style="font-size:var(--fs-body)">'+(o['时间']||'—')+'</td>'+
          '<td><span class="tag" style="font-size:var(--fs-body);background:var(--'+(isBuy?'up-bg':'down-bg')+');color:var(--'+(isBuy?'up':'down')+')">'+act+'</span></td>'+
          '<td style="font-size:var(--fs-body);font-weight:600">'+(o['标的']||'—')+'</td>'+
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono);color:var(--text-secondary)">'+(o['代码']||'—')+'</td>'+
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+(o['价格']||'—')+'</td>'+
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+(o['数量']||'—')+'</td>'+
          '<td style="font-size:var(--fs-body)">'+(o['窗口']||'—')+'</td>'+
          '<td style="font-size:var(--fs-body);color:var(--text-secondary);max-width:100px;white-space:normal">'+(o['原因']||'')+'</td>'+
          '<td><button class="w15_edit" data-idx="'+i+'" style="background:none;border:none;color:var(--info);cursor:pointer;font-size:var(--fs-body)" title="编辑">✎</button>'+
          '<button class="w15_del" data-idx="'+i+'" style="background:none;border:none;color:var(--danger);cursor:pointer;font-size:var(--fs-body)" title="删除">×</button></td></tr>';
      });
      html += '</tbody></table>';
    } else {
      html += '<div style="padding:var(--sp-sm);text-align:center;color:var(--text-disabled);font-size:var(--fs-body)">今日无操作</div>';
    }

    // ===== 清仓跟踪 =====
    if (cleared.length) {
      var now=new Date();
      var tracked=cleared.filter(function(p){var d=p['清仓日期'];if(!d)return true;try{return(now-new Date(d))/(86400000)<=7}catch(e){return true}});
      if (tracked.length) {
        html += '<div style="margin-top:var(--sp-md)"><span style="font-size:var(--fs-body);font-weight:600">清仓跟踪（7日内）</span></div>';
        html += '<table class="data-table"><thead><tr><th>标的</th><th>成本</th><th>卖出价</th><th>盈亏%</th><th>现价</th><th>卖出后涨跌</th><th>原因</th></tr></thead><tbody>';
        tracked.forEach(function(p) {
          var sp=parseFloat(p['卖出价']||p['现价'])||0, cp=parseFloat(p['成本'])||0;
          var lq=liveQ[(p['代码']||'')]||{};
          var liveOk = lq['最新价'] != null && parseFloat(lq['最新价']) > 0;
          var cur = liveOk ? parseFloat(lq['最新价']) : 0;
          var pl=cp>0?((sp-cp)/cp*100):0, pcls=pl>0?'up':'down';
          var ap=liveOk&&sp>0?((cur-sp)/sp*100):0, acls=ap>0?'up':ap<0?'down':'';
          html += '<tr><td style="font-size:var(--fs-body);font-weight:600">'+(p['标的']||'—')+'</td>'+
            '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+(cp||'—')+'</td>'+
            '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+(sp||'—')+'</td>'+
            '<td class="'+pcls+'" style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">'+(pl>=0?'+':'')+pl.toFixed(2)+'%</td>'+
            '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+(liveOk?cur:'—')+'</td>'+
            '<td class="'+acls+'" style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">'+(liveOk&&sp>0?(ap>=0?'+':'')+ap.toFixed(2)+'%':'—')+'</td>'+
            '<td style="font-size:var(--fs-body);color:var(--text-secondary);max-width:100px;white-space:normal">'+(p['清仓原因']||'')+'</td></tr>';
        });
        html += '</tbody></table>';
      }
    }

    body.innerHTML = html;
    this._bindEvents(active);

    // 自动更新 总资产 = pv + af
    DataStore.manualData.set('总资产', pv + af);
    this.updateTimestamp();

    if (!PositionsWidget._synced && location.protocol !== 'file:') {
      PositionsWidget._synced = true;
      var mp2 = DataStore.manualData.getAll();
      if (mp2['_positions'] || mp2['_今日操作']) {
        var pos2 = []; try { pos2 = JSON.parse(mp2['_positions'] || 'null'); } catch(e) {}
        var ops2 = []; try { ops2 = JSON.parse(mp2['_今日操作'] || '[]'); } catch(e) {}
        if (pos2 || ops2.length) _bridgeSync(pos2, ops2);
      }
    }
  }

  _bindEvents(active) {
    var self = this;
    var body = this.getBody();

    var addBtn = body.querySelector('#w15_add');
    if (addBtn) addBtn.onclick = function() { self._showForm(active); };

    // 编辑流水
    body.querySelectorAll('.w15_edit').forEach(function(b) {
      b.onclick = function() {
        var ops = []; try{ops=JSON.parse(DataStore.manualData.getAll()['_今日操作']||'[]')}catch(e){}
        var idx = parseInt(this.dataset.idx);
        if (ops[idx]) self._showForm(active, idx, ops[idx]);
      };
    });

    // 删除流水
    body.querySelectorAll('.w15_del').forEach(function(b) {
      b.onclick = function() {
        var ops = []; try{ops=JSON.parse(DataStore.manualData.getAll()['_今日操作']||'[]')}catch(e){}
        ops.splice(parseInt(this.dataset.idx), 1);
        DataStore.manualData.set('_今日操作', JSON.stringify(ops));
        self._renderBody();
      };
    });

    // 编辑持仓
    body.querySelectorAll('.w15_pos_edit').forEach(function(b) {
      b.onclick = function() {
        var idx = parseInt(this.dataset.pidx);
        if (active[idx]) self._showPosEdit(active[idx]);
      };
    });
  }

  _showPosEdit(p) {
    var self = this;
    var o = document.createElement('div');
    o.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);z-index:3000;display:flex;align-items:center;justify-content:center';
    o.innerHTML = '<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:var(--sp-lg);width:90%;max-width:360px">'+
      '<div style="font-size:var(--fs-subtitle);font-weight:700;margin-bottom:var(--sp-md)">编辑持仓</div>'+
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-sm)">'+
        '<div class="input-group" style="grid-column:1/-1"><label>标的名称</label><input id="pe_stock" value="'+(p['标的']||'')+'" style="width:100%"></div>'+
        '<div class="input-group"><label>代码</label><input id="pe_code" value="'+(p['代码']||'')+'" style="width:100%"></div>'+
        '<div class="input-group"><label>方向</label><select id="pe_dir" style="width:100%"><option>连板</option><option>趋势</option></select></div>'+
        '<div class="input-group"><label>成本</label><input id="pe_cost" type="number" step="0.01" value="'+(p['成本']||'')+'" style="width:100%"></div>'+
        '<div class="input-group"><label>数量(股)</label><input id="pe_qty" type="number" value="'+(p['数量']||0)+'" style="width:100%"></div>'+
        '<div class="input-group"><label>止损</label><input id="pe_stop" value="'+(p['止损']||'—')+'" style="width:100%"></div>'+
      '</div>'+
      '<div style="display:flex;gap:var(--sp-sm);margin-top:var(--sp-md)">'+
        '<button id="pe_save" style="flex:1;background:var(--info);color:var(--text-inverse);border:none;padding:var(--sp-sm);border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body)">保存</button>'+
        '<button id="pe_del" style="flex:0;background:var(--danger);color:var(--text-inverse);border:none;padding:var(--sp-sm) 16px;border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body)">删除</button>'+
        '<button id="pe_cancel" style="flex:1;background:var(--bg-base);color:var(--text-primary);border:1px solid var(--border);padding:var(--sp-sm);border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body)">取消</button>'+
      '</div></div>';
    document.body.appendChild(o);

    // 预设方向
    if (p['方向']) {
      var ds = o.querySelector('#pe_dir');
      for (var di = 0; di < ds.options.length; di++) {
        if (ds.options[di].value === p['方向']) { ds.selectedIndex = di; break; }
      }
    }

    o.querySelector('#pe_cancel').onclick = function(){ o.remove(); };
    o.querySelector('#pe_del').onclick = function(){
      if (!confirm('确定删除 '+(p['标的']||'此持仓')+'？')) return;
      // 从 localStorage _positions 中删除
      var pos = []; try{pos=JSON.parse(DataStore.manualData.getAll()['_positions']||'[]')}catch(e){}
      if (!pos.length) pos = JSON.parse(JSON.stringify((DataStore.merged&&DataStore.merged.positions)||[]));
      // 标的名匹配删除
      var found = -1;
      for (var i = pos.length-1; i >= 0; i--) {
        if (pos[i]['标的'] === p['标的']) { found = i; break; }
      }
      if (found >= 0) pos.splice(found, 1);
      // 如果是从 baseline 来的（不在 _positions 里），标记为已删除
      if (found < 0) {
        p['状态'] = '已删除';
        pos.push(p);
      }
      DataStore.manualData.set('_positions', JSON.stringify(pos));
      o.remove(); self._renderBody();
    };
    o.querySelector('#pe_save').onclick = function(){
      var g = function(id){return (o.querySelector('#'+id)||{}).value||'';};
      var pos = []; try{pos=JSON.parse(DataStore.manualData.getAll()['_positions']||'[]')}catch(e){}
      if (!pos.length) pos = JSON.parse(JSON.stringify((DataStore.merged&&DataStore.merged.positions)||[]));
      var found = pos.findIndex(function(x){return x['标的']===p['标的']&&x['代码']===p['代码'];});
      var entry = {
        '标的': g('pe_stock'), '代码': g('pe_code'), '方向': g('pe_dir'),
        '成本': parseFloat(g('pe_cost'))||0, '数量': parseInt(g('pe_qty'))||0,
        '止损': g('pe_stop')||'—', '状态': '持有', '现价': p['现价']||parseFloat(g('pe_cost'))||0
      };
      if (found >= 0) pos[found] = entry; else pos.push(entry);
      DataStore.manualData.set('_positions', JSON.stringify(pos));
      o.remove(); self._renderBody();
    };
    o.addEventListener('click', function(e){if(e.target===o)o.remove();});
  }

  _showForm(active, editIdx, prefill) {
    var self = this;
    var isEdit = editIdx != null;
    var pf = prefill || {};

    var o = document.createElement('div');
    o.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);z-index:3000;display:flex;align-items:center;justify-content:center';

    var sellOpts = active.map(function(p){return '<option value="'+p['标的']+'" data-code="'+(p['代码']||'')+'" data-price="'+(p['现价']||'')+'" data-qty="'+(p['数量']||0)+'">'+p['标的']+' ('+(p['代码']||'')+')</option>';}).join('');

    o.innerHTML = '<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:var(--sp-lg);width:90%;max-width:400px">'+
      '<div style="font-size:var(--fs-subtitle);font-weight:700;margin-bottom:var(--sp-md)">'+(isEdit?'编辑流水':'记流水')+'</div>'+
      '<div style="display:flex;gap:var(--sp-sm);margin-bottom:var(--sp-md)">'+
        '<button id="f_buy" style="flex:1;padding:var(--sp-sm);border:none;border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body);font-weight:600;background:var(--up-bg);color:var(--up)">买入</button>'+
        '<button id="f_sell" style="flex:1;padding:var(--sp-sm);border:none;border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body);font-weight:600;background:var(--down-bg);color:var(--down);opacity:0.4">卖出</button>'+
      '</div>'+
      '<div id="f_sell_select" style="display:none;margin-bottom:var(--sp-sm)"><div class="input-group"><label>选择持仓</label><select id="f_sel_stock" style="width:100%"><option value="">— 选择 —</option>'+sellOpts+'</select></div></div>'+
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-sm)">'+
        '<div class="input-group"><label>股票代码</label><input id="f_code" value="'+(pf['代码']||'')+'" style="width:100%"></div>'+
        '<div class="input-group"><label>时间</label><input id="f_time" value="'+(pf['时间']||_nowTime())+'" style="width:100%"></div>'+
        '<div class="input-group" style="grid-column:1/-1"><label>标的名称</label><input id="f_stock" value="'+(pf['标的']||'')+'" style="width:100%"></div>'+
        '<div class="input-group"><label>价格</label><input id="f_price" type="number" step="0.01" value="'+(pf['价格']||'')+'" style="width:100%"></div>'+
        '<div class="input-group" id="f_qty_row"><label>数量(股)</label><input id="f_qty" type="number" value="'+(pf['数量']||'100')+'" style="width:100%"></div>'+
        '<div class="input-group" id="f_win_row"><label>窗口</label><select id="f_win" style="width:100%"><option>W1</option><option>W2</option></select></div>'+
        '<div class="input-group" style="grid-column:1/-1"><label>交易理由</label><input id="f_reason" value="'+(pf['原因']||'')+'" style="width:100%"></div>'+
      '</div>'+
      '<div style="display:flex;gap:var(--sp-sm);margin-top:var(--sp-md)">'+
        '<button id="f_save" style="flex:1;background:var(--info);color:var(--text-inverse);border:none;padding:var(--sp-sm);border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body)">确认</button>'+
        '<button id="f_cancel" style="flex:1;background:var(--bg-base);color:var(--text-primary);border:1px solid var(--border);padding:var(--sp-sm);border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body)">取消</button>'+
      '</div></div>';
    document.body.appendChild(o);

    // 编辑模式：预设动作
    if (isEdit && pf['动作']) {
      var act = pf['动作'];
      var isBuyDefault = act.indexOf('买入')>=0 || act.indexOf('追')>=0;
      var buyBtn = o.querySelector('#f_buy'), sellBtn = o.querySelector('#f_sell');
      var sellSelect = o.querySelector('#f_sell_select');
      buyBtn.style.opacity = isBuyDefault ? '1' : '0.4';
      sellBtn.style.opacity = isBuyDefault ? '0.4' : '1';
      sellSelect.style.display = isBuyDefault ? 'none' : '';
      if (!isBuyDefault) {
        o.querySelector('#f_qty_row').querySelector('label').textContent = '卖出数量';
      }
      var winSel = o.querySelector('#f_win');
      for (var wi = 0; wi < winSel.options.length; wi++) {
        if (winSel.options[wi].value === pf['窗口']) { winSel.selectedIndex = wi; break; }
      }
    }

    // 买入/卖出切换
    var buyBtn2 = o.querySelector('#f_buy'), sellBtn2 = o.querySelector('#f_sell');
    var sellSelect2 = o.querySelector('#f_sell_select'), qtyRow2 = o.querySelector('#f_qty_row'), winRow2 = o.querySelector('#f_win_row');
    var qtyLabel2 = qtyRow2.querySelector('label');

    function toggle(buy) {
      buyBtn2.style.opacity = buy ? '1' : '0.4';
      sellBtn2.style.opacity = buy ? '0.4' : '1';
      sellSelect2.style.display = buy ? 'none' : '';
      qtyLabel2.textContent = buy ? '数量(股)' : '卖出数量';
      winRow2.style.display = buy ? '' : 'none';
    }
    buyBtn2.onclick = function(){toggle(true)};
    sellBtn2.onclick = function(){toggle(false)};

    o.querySelector('#f_sel_stock').onchange = function() {
      var opt = this.selectedOptions[0];
      if (!opt || !opt.value) return;
      o.querySelector('#f_stock').value = opt.value;
      o.querySelector('#f_code').value = opt.dataset.code || '';
      o.querySelector('#f_price').value = opt.dataset.price || '';
      o.querySelector('#f_qty').value = opt.dataset.qty || '';
    };

    o.querySelector('#f_cancel').onclick = function() { o.remove(); };
    o.querySelector('#f_save').onclick = function() {
      var g = function(id) { return (o.querySelector('#'+id)||{}).value || ''; };
      var buy = buyBtn2.style.opacity !== '0.4';
      var price = parseFloat(g('f_price'))||0, qty = parseInt(g('f_qty'))||0;
      var stock = g('f_stock'), code = g('f_code'), reason = g('f_reason');
      var act = buy ? (g('f_win')==='W1'?'W1追涨':'W2买入') : '卖出';

      // 更新/新增流水
      var ops = []; try{ops=JSON.parse(DataStore.manualData.getAll()['_今日操作']||'[]')}catch(e){}
      var entry = {'时间':g('f_time'),'动作':act,'标的':stock,'代码':code,'价格':price,'数量':qty,'窗口':buy?g('f_win'):'—','原因':reason};
      if (isEdit) ops[editIdx] = entry; else ops.push(entry);
      DataStore.manualData.set('_今日操作', JSON.stringify(ops));

      // 买入 → 扣可用资金 / 卖出 → 加可用资金
      var af = parseFloat(DataStore.manualData.getAll()['可用资金']) || 0;
      var tradeAmt = price * qty;
      if (buy) af = Math.max(0, af - tradeAmt);
      else af = af + tradeAmt;
      DataStore.manualData.set('可用资金', af);

      // 更新持仓
      var pos = []; try{pos=JSON.parse(DataStore.manualData.getAll()['_positions']||'null')}catch(e){}
      if (!pos||!pos.length) pos=JSON.parse(JSON.stringify((DataStore.merged&&DataStore.merged.positions)||[]));

      if (!buy) {
        var f = pos.find(function(p){return p['标的']===stock;});
        if (f) {
          var oldQty = parseInt(f['数量'])||0;
          var sellQty = qty;
          if (sellQty >= oldQty) {
            f['状态']='已清仓'; f['卖出价']=price; f['清仓原因']=reason; f['清仓日期']=new Date().toISOString().slice(0,10);
          } else {
            f['数量'] = oldQty - sellQty;
          }
        }
      } else {
        var e = pos.find(function(p){return p['标的']===stock;});
        if (e) {
          var oq=parseInt(e['数量'])||0, oc=parseFloat(e['成本'])||0, nq=oq+qty;
          e['数量']=nq; e['成本']=oq>0?Math.round(((oc*oq)+(price*qty))/nq*100)/100:price; e['现价']=price; e['代码']=code||e['代码'];
        } else {
          pos.push({'标的':stock,'代码':code,'成本':price,'现价':price,'数量':qty,'止损':'—','状态':'持有'});
        }
      }
      DataStore.manualData.set('_positions', JSON.stringify(pos));
      _bridgeSync(pos, ops);
      o.remove(); self._renderBody();
    };
    o.addEventListener('click', function(e){if(e.target===o)o.remove();});
  }
}

function _nowTime() { var d=new Date(); return d.getHours()+':'+String(d.getMinutes()).padStart(2,'0'); }

function _bridgeSync(positions, ops) {
  if (location.protocol === 'file:') return;
  try {
    fetch('/api/sync', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ positions: positions, '今日操作': ops })
    }).catch(function(){});
  } catch(e) {}
}

WidgetRegistry.register('W15', PositionsWidget);
