// widgets/today-ops.js — W17 今日操作（自助录入+自动计算+同步持仓）
'use strict';

function _syncPosition(entry) {
  // 从 manualData 或 DataStore 读取现有持仓
  var manual = DataStore.manualData.getAll();
  var posJson = manual['_positions'] || '[]';
  var positions = [];
  try { positions = JSON.parse(posJson); } catch(e) { positions = []; }
  // 如果 manualData 没有，从 DataStore.merged 初始化
  if (!positions.length) {
    var merged = DataStore.merged || {};
    (merged.positions || []).forEach(function(p) {
      var s = p['状态'] || '';
      if (s.indexOf('清仓') < 0 && s.indexOf('卖出') < 0) {
        positions.push({
          '标的': p['标的'], '代码': p['代码']||'', '方向': p['方向']||'',
          '成本': p['成本'], '现价': p['现价'], '数量': p['数量']||0,
          '止损': p['止损']||'—', '状态': '持有'
        });
      }
    });
  }

  var act = entry['动作'] || '';
  var stock = entry['标的'] || '';
  var price = parseFloat(entry['价格']) || 0;
  var qty = parseInt(entry['数量']) || 0;

  if (act.indexOf('清仓') >= 0 || act.indexOf('卖出') >= 0) {
    // 卖出/清仓：标记持仓
    var found = positions.find(function(p) { return p['标的'] === stock; });
    if (found) {
      found['状态'] = '已清仓';
      found['卖出价'] = price;
      found['清仓原因'] = entry['原因'] || '';
    }
  } else {
    // 买入/追涨：新增或合并持仓
    var exist = positions.find(function(p) { return p['标的'] === stock; });
    if (exist) {
      // 合并：加权平均成本
      var oldQty = parseInt(exist['数量']) || 0;
      var oldCost = parseFloat(exist['成本']) || 0;
      var newQty = oldQty + qty;
      var newCost = oldQty > 0 ? ((oldCost * oldQty) + (price * qty)) / newQty : price;
      exist['数量'] = newQty;
      exist['成本'] = Math.round(newCost * 100) / 100;
      exist['现价'] = price;
    } else {
      positions.push({
        '标的': stock, '代码': '', '方向': '',
        '成本': price, '现价': price, '数量': qty,
        '止损': '—', '状态': '持有'
      });
    }
  }

  DataStore.manualData.set('_positions', JSON.stringify(positions));
}

class TodayOpsWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;

    // 从 manualData 读取操作记录，同时合并附录数据
    var manual = DataStore.manualData.getAll();
    var opsJson = manual['_今日操作'] || '[]';
    var ops = [];
    try { ops = JSON.parse(opsJson); } catch(e) { ops = []; }

    // 也读附录解析的数据（首次加载时显示）
    var appendix = (data && data.decision && data.decision['今日操作']) || [];

    // 如果 manualData 无记录，从附录初始化
    if (!ops.length && appendix.length) {
      appendix.forEach(function(o) {
        var qty = parseFloat(o['数量']) || 100;
        var price = parseFloat(o['价格']) || 0;
        o['数量'] = qty;
        o['市值'] = Math.round(price * qty);
        o['盈亏pct'] = parseFloat(o['盈亏']) || 0;
      });
      ops = appendix;
    }

    var html = '';

    // 添加按钮
    html += '<div style="margin-bottom:var(--sp-sm)">' +
      '<button id="w17_add" style="background:var(--info);color:var(--text-inverse);border:none;padding:var(--sp-xs) var(--sp-md);border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body);font-family:var(--font-sans)">+ 添加操作</button>' +
      '</div>';

    if (!ops.length) {
      html += '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled);font-size:var(--fs-body)">今日无操作</div>';
      body.innerHTML = html;
      this._bindEvents(body, ops);
      this.updateTimestamp();
      return;
    }

    // 表格
    html += '<table class="data-table"><thead><tr>' +
      '<th>时间</th><th>动作</th><th>标的</th><th>价格</th><th>数量</th><th>市值</th><th>盈亏</th><th>盈亏%</th><th>原因</th><th></th>' +
      '</tr></thead><tbody>';

    ops.forEach(function(o, idx) {
      var price = parseFloat(o['价格']) || 0;
      var qty = parseFloat(o['数量']) || 0;
      var mv = Math.round(price * qty);
      var pl = parseFloat(o['盈亏']) || 0;
      var plPct = parseFloat(o['盈亏pct']) || (price > 0 ? (pl / (price * qty) * 100) : 0);
      var plCls = pl > 0 ? 'up' : pl < 0 ? 'down' : '';
      var pctCls = plPct > 0 ? 'up' : plPct < 0 ? 'down' : '';
      var act = o['动作'] || '—';

      html += '<tr>' +
        '<td style="font-size:var(--fs-body)">'+(o['时间']||'—')+'</td>' +
        '<td><span class="tag" style="background:var(--'+(act.indexOf('追')>=0?'up-bg':'danger-bg')+');color:var(--'+(act.indexOf('追')>=0?'up':'danger')+');font-size:var(--fs-body)">'+act+'</span></td>' +
        '<td style="font-size:var(--fs-body);font-weight:600">'+(o['标的']||'—')+'</td>' +
        '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+(price||'—')+'</td>' +
        '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+(qty||'—')+'</td>' +
        '<td style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">'+mv.toLocaleString()+'</td>' +
        '<td class="'+plCls+'" style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">'+(pl>=0?'+':'')+pl.toFixed(0)+'</td>' +
        '<td class="'+pctCls+'" style="font-size:var(--fs-body);font-family:var(--font-mono);font-weight:600">'+(plPct>=0?'+':'')+plPct.toFixed(2)+'%</td>' +
        '<td style="font-size:var(--fs-body);color:var(--text-secondary);max-width:120px;white-space:normal">'+(o['原因']||'')+'</td>' +
        '<td><button class="w17_del" data-idx="'+idx+'" style="background:none;border:none;color:var(--danger);cursor:pointer;font-size:var(--fs-body)">×</button></td>' +
        '</tr>';
    });

    html += '</tbody></table>';
    body.innerHTML = html;
    this._bindEvents(body, ops);
    this.updateTimestamp();
  }

  _bindEvents(body, ops) {
    var self = this;

    // 添加按钮
    var addBtn = body.querySelector('#w17_add');
    if (addBtn) addBtn.addEventListener('click', function() { self._showAddForm(ops); });

    // 删除按钮
    body.querySelectorAll('.w17_del').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var idx = parseInt(this.dataset.idx);
        ops.splice(idx, 1);
        DataStore.manualData.set('_今日操作', JSON.stringify(ops));
        self._renderBody();
      });
    });
  }

  _showAddForm(ops) {
    var self = this;
    var html = '<div id="w17_form" style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);z-index:3000;display:flex;align-items:center;justify-content:center">' +
      '<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:var(--sp-lg);width:90%;max-width:420px">' +
      '<div style="font-size:var(--fs-subtitle);font-weight:700;margin-bottom:var(--sp-md)">添加操作</div>' +
      '<div class="input-grid" style="grid-template-columns:1fr 1fr">' +
        '<div class="input-group"><label>时间</label><input id="w17_time" placeholder="9:35" style="width:100%"></div>' +
        '<div class="input-group"><label>动作</label><select id="w17_act" style="width:100%"><option>W1追涨</option><option>W2买入</option><option>卖出</option><option>清仓</option></select></div>' +
        '<div class="input-group"><label>标的</label><input id="w17_stock" placeholder="大业股份" style="width:100%"></div>' +
        '<div class="input-group"><label>价格</label><input id="w17_price" type="number" step="0.01" style="width:100%"></div>' +
        '<div class="input-group"><label>数量(股)</label><input id="w17_qty" type="number" value="100" style="width:100%"></div>' +
        '<div class="input-group"><label>盈亏</label><input id="w17_pnl" type="number" step="0.01" style="width:100%"></div>' +
      '</div>' +
      '<div class="input-group" style="margin-top:var(--sp-sm)"><label>原因</label><input id="w17_reason" style="width:100%"></div>' +
      '<div style="display:flex;gap:var(--sp-sm);margin-top:var(--sp-md)">' +
        '<button id="w17_save" style="flex:1;background:var(--info);color:var(--text-inverse);border:none;padding:var(--sp-sm);border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body)">确认</button>' +
        '<button id="w17_cancel" style="flex:1;background:var(--bg-base);color:var(--text-primary);border:1px solid var(--border);padding:var(--sp-sm);border-radius:var(--radius-sm);cursor:pointer;font-size:var(--fs-body)">取消</button>' +
      '</div></div></div>';

    var overlay = document.createElement('div');
    overlay.innerHTML = html;
    document.body.appendChild(overlay);

    overlay.querySelector('#w17_cancel').onclick = function() { overlay.remove(); };
    overlay.querySelector('#w17_save').onclick = function() {
      var price = parseFloat(overlay.querySelector('#w17_price').value) || 0;
      var qty = parseInt(overlay.querySelector('#w17_qty').value) || 0;
      var pnl = parseFloat(overlay.querySelector('#w17_pnl').value) || 0;
      var entry = {
        '时间': overlay.querySelector('#w17_time').value,
        '动作': overlay.querySelector('#w17_act').value,
        '标的': overlay.querySelector('#w17_stock').value,
        '价格': price,
        '数量': qty,
        '市值': Math.round(price * qty),
        '盈亏': pnl,
        '盈亏pct': price > 0 && qty > 0 ? (pnl / (price * qty) * 100) : 0,
        '原因': overlay.querySelector('#w17_reason').value
      };
      ops.push(entry);
      DataStore.manualData.set('_今日操作', JSON.stringify(ops));
      // 同步更新 W15 持仓
      _syncPosition(entry);
      overlay.remove();
      self._renderBody();
    };
    overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });
  }
}

WidgetRegistry.register('W17', TodayOpsWidget);
