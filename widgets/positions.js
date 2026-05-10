// widgets/positions.js — W15 持仓明细+今日操作+清仓跟踪（合并 W17）
'use strict';

class PositionsWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var manual = DataStore.manualData.getAll();
    var liveQ = (data && data.live_quotes) || {};

    // 持仓数据：优先 manualData._positions，fallback 附录
    var posJson = manual['_positions'] || '';
    var P = [];
    try { P = JSON.parse(posJson); } catch(e) {}
    if (!P || !P.length) { P = JSON.parse(JSON.stringify((data && data.positions) || [])); }

    // 今日操作
    var opsJson = manual['_今日操作'] || '[]';
    var ops = [];
    try { ops = JSON.parse(opsJson); } catch(e) {}
    if (!ops.length) {
      var appendixOps = (data && data.decision && data.decision['今日操作']) || [];
      if (appendixOps.length) {
        appendixOps.forEach(function(o) {
          o['数量'] = parseFloat(o['数量']) || 100;
          o['市值'] = Math.round((parseFloat(o['价格'])||0) * o['数量']);
          o['盈亏pct'] = parseFloat(o['盈亏']) || 0;
        });
        ops = appendixOps;
      }
    }

    // 分类持仓
    var active = [], cleared = [];
    P.forEach(function(p) {
      var s = p['状态'] || '';
      if (s.indexOf('清仓')>=0 || s.indexOf('卖出')>=0) cleared.push(p);
      else active.push(p);
    });

    // 自动计算活跃持仓
    active.forEach(function(p) {
      var qty = parseFloat(p['数量']) || 0;
      var price = parseFloat(p['现价']) || 0;
      var cost = parseFloat(p['成本']) || 0;
      p['_市值'] = Math.round(price * qty);
      p['_盈亏'] = Math.round((price - cost) * qty);
      p['_盈亏pct'] = cost > 0 ? ((price - cost) / cost * 100) : 0;
    });

    var html = '';

    // ===== 汇总卡片 =====
    var totalAssetWan = parseFloat(manual['总资产']) || 0;
    var totalAsset = totalAssetWan * 10000;
    var posValue = 0, posCost = 0;
    active.forEach(function(p) { posValue += p['_市值']||0; posCost += Math.round((parseFloat(p['成本'])||0)*(parseFloat(p['数量'])||0)); });
    var totalPnl = posValue - posCost;
    var pnlCls = totalPnl > 0 ? 'up' : totalPnl < 0 ? 'down' : '';
    var pnlPct = posCost > 0 ? (totalPnl / posCost * 100) : 0;
    var availFund = totalAsset - posValue;
    var positionRatio = totalAsset > 0 ? Math.round(posValue / totalAsset * 100) : 0;

    if (totalAsset > 0) {
      html += '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:var(--sp-xs) var(--sp-sm);margin-bottom:var(--sp-md);padding:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md);font-size:var(--fs-body)">' +
        '<div style="text-align:center"><div class="kpi-label">总资产</div><div style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700">'+totalAsset.toLocaleString()+'</div></div>' +
        '<div style="text-align:center"><div class="kpi-label">持仓市值</div><div style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700">'+posValue.toLocaleString()+'</div></div>' +
        '<div style="text-align:center"><div class="kpi-label">总盈亏</div><div style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700;color:var(--'+pnlCls+')">'+(totalPnl>=0?'+':'')+totalPnl.toLocaleString()+'</div></div>' +
        '<div style="text-align:center"><div class="kpi-label">总盈亏%</div><div style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700;color:var(--'+pnlCls+')">'+(pnlPct>=0?'+':'')+pnlPct.toFixed(2)+'%</div></div>' +
        '<div style="text-align:center"><div class="kpi-label">可用资金</div><div style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700">'+availFund.toLocaleString()+'</div></div>' +
        '<div style="text-align:center"><div class="kpi-label">仓位</div><div style="font-family:var(--font-mono);font-size:var(--fs-subtitle);font-weight:700;color:'+(positionRatio>80?'var(--danger)':positionRatio>50?'var(--warn)':'var(--info)')+'">'+positionRatio+'%</div></div>' +
        '</div>';
    }

    // ===== 活跃持仓表格 =====
    if (active.length) {
      html += '<div style="font-size:var(--fs-body);font-weight:600;color:var(--text-primary);margin-bottom:var(--sp-xs)">持仓</div>';
      html += '<table class="data-table"><thead><tr>' +
        '<th>标的</th><th>市值</th><th>数量</th><th>现价</th><th>成本</th><th>盈亏</th><th>盈亏%</th><th>止损</th>' +
        '</tr></thead><tbody>';
      active.forEach(function(p) {
        var pnlC = (p['_盈亏']||0)>0?'up':(p['_盈亏']||0)<0?'down':'';
        var pctC = (p['_盈亏pct']||0)>0?'up':(p['_盈亏pct']||0)<0?'down':'';
        html += '<tr>' +
          '<td style="font-size:var(--fs-body);font-weight:600">'+(p['标的']||'—')+'</td>' +
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">'+(p['_市值']||0).toLocaleString()+'</td>' +
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+(p['数量']||0).toLocaleString()+'</td>' +
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+(p['现价']||'—')+'</td>' +
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono);color:var(--text-secondary)">'+(p['成本']||'—')+'</td>' +
          '<td class="'+pnlC+'" style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">'+(p['_盈亏']>=0?'+':'')+(p['_盈亏']||0).toLocaleString()+'</td>' +
          '<td class="'+pctC+'" style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">'+(p['_盈亏pct']>=0?'+':'')+(p['_盈亏pct']||0).toFixed(2)+'%</td>' +
          '<td style="font-size:var(--fs-body)">'+(p['止损']||'—')+'</td>' +
          '</tr>';
      });
      html += '</tbody></table>';
    }

    // ===== 今日操作 =====
    html += '<div style="display:flex;align-items:center;gap:var(--sp-sm);margin-top:var(--sp-md);margin-bottom:var(--sp-xs)">' +
      '<span style="font-size:var(--fs-body);font-weight:600;color:var(--text-primary)">今日操作</span>' +
      '<button id="w15_add" style="background:var(--info);color:#fff;border:none;padding:2px 10px;border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body);font-family:var(--font-sans)">+ 添加</button>' +
      '</div>';

    if (ops.length) {
      html += '<table class="data-table"><thead><tr>' +
        '<th>时间</th><th>动作</th><th>标的</th><th>价格</th><th>数量</th><th>市值</th><th>盈亏%</th><th>原因</th><th></th>' +
        '</tr></thead><tbody>';
      ops.forEach(function(o, idx) {
        var price = parseFloat(o['价格'])||0;
        var qty = parseFloat(o['数量'])||0;
        var mv = Math.round(price*qty);
        var pct = parseFloat(o['盈亏pct'])||0;
        var pctCls = pct>0?'up':pct<0?'down':'';
        var act = o['动作']||'—';
        html += '<tr>' +
          '<td style="font-size:var(--fs-body)">'+(o['时间']||'—')+'</td>' +
          '<td><span class="tag" style="font-size:var(--fs-body);background:var(--'+(act.indexOf('追')>=0?'up-bg':'danger-bg')+');color:var(--'+(act.indexOf('追')>=0?'up':'danger')+')">'+act+'</span></td>' +
          '<td style="font-size:var(--fs-body);font-weight:600">'+(o['标的']||'—')+'</td>' +
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+(price||'—')+'</td>' +
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+(qty||'—')+'</td>' +
          '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+mv.toLocaleString()+'</td>' +
          '<td class="'+pctCls+'" style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">'+(pct>=0?'+':'')+pct.toFixed(2)+'%</td>' +
          '<td style="font-size:var(--fs-body);color:var(--text-secondary);max-width:100px;white-space:normal">'+(o['原因']||'')+'</td>' +
          '<td><button class="w15_del" data-idx="'+idx+'" style="background:none;border:none;color:var(--danger);cursor:pointer;font-size:var(--fs-body)">×</button></td>' +
          '</tr>';
      });
      html += '</tbody></table>';
    }

    // ===== 清仓跟踪（7日内） =====
    if (cleared.length) {
      var now = new Date();
      var tracked = cleared.filter(function(p) {
        var d = p['清仓日期'];
        if (!d) return true;
        try { return (now - new Date(d))/(1000*60*60*24) <= 7; } catch(e) { return true; }
      });

      if (tracked.length) {
        html += '<div style="margin-top:var(--sp-md)"><span style="font-size:var(--fs-body);font-weight:600;color:var(--text-primary)">清仓跟踪（7日内）</span></div>';
        html += '<table class="data-table"><thead><tr>' +
          '<th>标的</th><th>成本</th><th>卖出价</th><th>盈亏%</th><th>现价</th><th>卖出后涨跌</th><th>原因</th>' +
          '</tr></thead><tbody>';
        tracked.forEach(function(p) {
          var sellPrice = parseFloat(p['卖出价']||p['现价'])||0;
          var costPrice = parseFloat(p['成本'])||0;
          var curPrice = parseFloat(liveQ[p['代码']]&&liveQ[p['代码']]['最新价']) || parseFloat(p['最新价']||p['现价']) || 0;
          var plPct = costPrice>0 ? ((sellPrice-costPrice)/costPrice*100) : 0;
          var plCls = plPct>0?'up':'down';
          var afterPct = sellPrice>0 ? ((curPrice-sellPrice)/sellPrice*100) : 0;
          var afterCls = afterPct>0?'up':'down';
          html += '<tr>' +
            '<td style="font-size:var(--fs-body);font-weight:600">'+(p['标的']||'—')+'</td>' +
            '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+(costPrice||'—')+'</td>' +
            '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+(sellPrice||'—')+'</td>' +
            '<td class="'+plCls+'" style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">'+(plPct>=0?'+':'')+plPct.toFixed(2)+'%</td>' +
            '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+(curPrice>0?curPrice:'—')+'</td>' +
            '<td class="'+afterCls+'" style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">'+(afterPct>=0?'+':'')+afterPct.toFixed(2)+'%</td>' +
            '<td style="font-size:var(--fs-body);color:var(--text-secondary);max-width:100px;white-space:normal">'+(p['清仓原因']||'')+'</td>' +
            '</tr>';
        });
        html += '</tbody></table>';
      }
    }

    body.innerHTML = html;
    this._bindEvents(body, active, cleared, ops);
    this.updateTimestamp();
  }

  _bindEvents(body, active, cleared, ops) {
    var self = this;

    var addBtn = body.querySelector('#w15_add');
    if (addBtn) addBtn.addEventListener('click', function() { self._showAddForm(active, cleared, ops); });

    body.querySelectorAll('.w15_del').forEach(function(btn) {
      btn.addEventListener('click', function() {
        ops.splice(parseInt(this.dataset.idx), 1);
        DataStore.manualData.set('_今日操作', JSON.stringify(ops));
        self._renderBody();
      });
    });
  }

  _showAddForm(active, cleared, ops) {
    var self = this;
    var overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);z-index:3000;display:flex;align-items:center;justify-content:center';
    overlay.innerHTML = '<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:var(--sp-lg);width:90%;max-width:420px">' +
      '<div style="font-size:var(--fs-subtitle);font-weight:700;margin-bottom:var(--sp-md)">添加操作</div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-sm)">' +
        '<div class="input-group"><label>时间</label><input id="a_time" value="'+_nowTime()+'" style="width:100%"></div>' +
        '<div class="input-group"><label>动作</label><select id="a_act" style="width:100%"><option>W1追涨</option><option>W2买入</option><option>卖出</option><option>清仓</option></select></div>' +
        '<div class="input-group"><label>标的</label><input id="a_stock" style="width:100%"></div>' +
        '<div class="input-group"><label>代码</label><input id="a_code" style="width:100%"></div>' +
        '<div class="input-group"><label>价格</label><input id="a_price" type="number" step="0.01" style="width:100%"></div>' +
        '<div class="input-group"><label>数量(股)</label><input id="a_qty" type="number" value="100" style="width:100%"></div>' +
        '<div class="input-group"><label>方向</label><input id="a_dir" style="width:100%"></div>' +
        '<div class="input-group"><label>止损</label><input id="a_stop" placeholder="—" style="width:100%"></div>' +
      '</div>' +
      '<div class="input-group" style="margin-top:var(--sp-sm)"><label>原因</label><input id="a_reason" style="width:100%"></div>' +
      '<div style="display:flex;gap:var(--sp-sm);margin-top:var(--sp-md)">' +
        '<button id="a_save" style="flex:1;background:var(--info);color:#fff;border:none;padding:var(--sp-sm);border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body)">确认</button>' +
        '<button id="a_cancel" style="flex:1;background:var(--bg-base);color:var(--text-primary);border:1px solid var(--border);padding:var(--sp-sm);border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body)">取消</button>' +
      '</div></div>';

    document.body.appendChild(overlay);

    overlay.querySelector('#a_cancel').onclick = function() { overlay.remove(); };
    overlay.querySelector('#a_save').onclick = function() {
      var price = parseFloat(overlay.querySelector('#a_price').value)||0;
      var qty = parseInt(overlay.querySelector('#a_qty').value)||0;
      var stock = overlay.querySelector('#a_stock').value;
      var code = overlay.querySelector('#a_code').value;
      var act = overlay.querySelector('#a_act').value;
      var mv = Math.round(price*qty);

      // 添加到操作记录
      ops.push({
        '时间': overlay.querySelector('#a_time').value,
        '动作': act, '标的': stock, '价格': price, '数量': qty,
        '市值': mv, '盈亏pct': 0, '原因': overlay.querySelector('#a_reason').value
      });
      DataStore.manualData.set('_今日操作', JSON.stringify(ops));

      // 同步持仓
      if (act.indexOf('清仓')>=0 || act.indexOf('卖出')>=0) {
        var found = active.find(function(p){return p['标的']===stock;});
        if (found) {
          found['状态'] = '已清仓';
          found['卖出价'] = price;
          found['清仓原因'] = overlay.querySelector('#a_reason').value;
          found['清仓日期'] = new Date().toISOString().slice(0,10);
          active.splice(active.indexOf(found), 1);
          cleared.push(found);
        }
      } else {
        var exist = active.find(function(p){return p['标的']===stock;});
        if (exist) {
          var oldQty = parseInt(exist['数量'])||0;
          var oldCost = parseFloat(exist['成本'])||0;
          var newQty = oldQty + qty;
          exist['数量'] = newQty;
          exist['成本'] = oldQty>0 ? Math.round(((oldCost*oldQty)+(price*qty))/newQty*100)/100 : price;
          exist['现价'] = price;
        } else {
          active.push({
            '标的': stock, '代码': code, '方向': overlay.querySelector('#a_dir').value,
            '成本': price, '现价': price, '数量': qty,
            '止损': overlay.querySelector('#a_stop').value||'—', '状态': '持有'
          });
        }
      }
      DataStore.manualData.set('_positions', JSON.stringify(active.concat(cleared)));
      DataStore.notifyAll();
      overlay.remove();
      self._renderBody();
    };
    overlay.addEventListener('click', function(e) { if (e.target===overlay) overlay.remove(); });
  }
}

function _nowTime() {
  var d = new Date();
  return d.getHours()+':'+String(d.getMinutes()).padStart(2,'0');
}

WidgetRegistry.register('W15', PositionsWidget);
