// widgets/pnl-curve.js — W22 账户收益曲线
// Canvas 折线图: 账户TWR收益 vs 基准指数 + 仓位 + 自动回撤高亮
'use strict';

// 注入一次 CSS
(function() {
  if (document.getElementById('pnl-curve-style')) return;
  var style = document.createElement('style');
  style.id = 'pnl-curve-style';
  style.textContent =
    '.pnl-root{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}' +
    // KPI
    '.pnl-kpi{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--border);margin-bottom:2px}' +
    '.pnl-kpi-card{background:var(--bg-card);padding:12px 16px;min-height:70px}' +
    '.pnl-kpi-lbl{font-size:10px;text-transform:uppercase;letter-spacing:.3px;color:var(--text-secondary);margin-bottom:3px;font-weight:500}' +
    '.pnl-kpi-val{font-size:24px;font-weight:700;font-family:var(--font-mono);line-height:1.2}' +
    '.pnl-kpi-sub{font-size:10px;color:var(--text-disabled);margin-top:2px}' +
    '.pnl-kpi-dyn{border-left:2px solid var(--accent)}' +
    // Controls
    '.pnl-ctrl{display:flex;align-items:center;gap:6px;padding:8px 14px;border-bottom:1px solid var(--border-light);background:var(--bg-base);flex-wrap:wrap}' +
    '.pnl-ctrl-label{font-size:10px;color:var(--text-disabled);letter-spacing:.3px;text-transform:uppercase;margin-right:4px}' +
    '.pnl-index,.pnl-periods{display:flex;gap:3px}' +
    '.pnl-idx-btn,.pnl-period{padding:3px 10px;border-radius:4px;font-size:11px;cursor:pointer;color:var(--text-secondary);background:transparent;border:none;font-family:inherit;font-weight:500;transition:all .12s}' +
    '.pnl-idx-btn:hover,.pnl-period:hover{background:var(--bg-hover);color:var(--text)}' +
    '.pnl-idx-btn.active{background:var(--info-bg);color:var(--info);font-weight:600}' +
    '.pnl-period.active{background:var(--info-bg);color:var(--info);font-weight:600}' +
    '.pnl-period-custom{border:1px dashed var(--border);color:var(--text-disabled);margin-left:auto}' +
    // Chart
    '.pnl-chart-wrap{position:relative;padding:8px 14px 4px}' +
    '.pnl-chart-wrap canvas{width:100%;height:280px;display:block;border-radius:6px}' +
    // Legend
    '.pnl-legend{display:flex;gap:20px;padding:0 14px 8px;align-items:center;flex-wrap:wrap}' +
    '.pnl-leg-item{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text-secondary)}' +
    '.pnl-leg-line{width:20px;height:3px;border-radius:2px;flex-shrink:0}' +
    // Drawer
    // 辅助功能
    '.pnl-aux-row{padding:0 14px 6px;display:flex;gap:12px}' +
    '.pnl-aux-label{font-size:11px;color:var(--text-secondary);cursor:pointer;display:flex;align-items:center;gap:4px}' +
    '.pnl-pos-chart{margin:0 14px 4px}' +
    '.pnl-pos-chart canvas{width:100%;height:90px;display:block}' +
    // Drawer
    '.pnl-drawer-trigger{padding:0 14px 10px}' +
    '.pnl-drawer-btn{width:100%;padding:9px 14px;border-radius:6px;font-size:13px;cursor:pointer;background:var(--bg-base);border:1px solid var(--border);color:var(--text);font-family:inherit;font-weight:600;transition:all .12s;display:flex;align-items:center;justify-content:center;gap:6px}' +
    '.pnl-drawer-btn:hover{background:var(--accent-bg);border-color:var(--accent);color:var(--accent)}' +
    '.pnl-drawer-btn.pnl-drawer-btn-open{background:var(--accent-bg);border-color:var(--accent);color:var(--accent)}' +
    '.pnl-drawer-btn::after{content:"▼";font-size:9px;color:var(--text-disabled);transition:transform .2s}' +
    '.pnl-drawer-btn.pnl-drawer-btn-open::after{transform:rotate(180deg)}' +
    '.pnl-drawer{display:none;margin:0 14px 14px;border-radius:8px;border:1px solid var(--border-light);overflow:hidden}' +
    '.pnl-drawer.pnl-drawer-open{display:block}' +
    // Table
    '.pnl-table{width:100%;border-collapse:collapse;font-size:12px}' +
    '.pnl-table th{background:var(--bg-base);padding:8px 12px;font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:var(--text-secondary);font-weight:600;border-bottom:1px solid var(--border-light);white-space:nowrap}' +
    '.pnl-table td{padding:8px 12px;border-bottom:1px solid var(--border-light);font-variant-numeric:tabular-nums}' +
    '.pnl-table tbody tr:hover td{background:var(--bg-hover)}' +
    '.pnl-table tbody tr:last-child td{border-bottom:none}' +
    '.pnl-td-period{font-weight:600;white-space:nowrap;width:72px}' +
    '.pnl-td-num{font-family:var(--font-mono);text-align:right;white-space:nowrap}' +
    '.pnl-td-bold{font-weight:600}' +
    '.pnl-table th.pnl-td-period{text-align:left}' +
    '.pnl-table th.pnl-td-num{text-align:right}' +
    '.pnl-cum-row{background:var(--bg-base)}' +
    '.pnl-cum-row td{font-weight:600;border-top:2px solid var(--border);padding:10px 12px}' +
    // Summary
    '.pnl-summary{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--border);border-top:1px solid var(--border)}' +
    '.pnl-sum-cell{background:var(--bg-card);padding:10px 14px;text-align:right}' +
    '.pnl-sum-lbl{font-size:9px;text-transform:uppercase;letter-spacing:.3px;color:var(--text-disabled);margin-bottom:2px}' +
    '.pnl-sum-val{font-size:14px;font-weight:600;font-family:var(--font-mono)}';
  document.head.appendChild(style);
})();


class PnLCurveWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    body.innerHTML = this._buildLayout();

    var liveQ = (data && data.live_quotes) || {};
    var positions = (data && data.positions) || [];
    var pnlCfg = (data && data.pnl) || {};
    var totalAsset = pnlCfg['总资产'] || (this._state && this._state.totalAsset) || 0;
    var totalDeposit = pnlCfg['累计入金'] || (this._state && this._state.totalDeposit) || 0;

    this._state = {
      period: (this._state && this._state.period) || 'today',
      index: (this._state && this._state.index) || 'sh',
      drawerOpen: (this._state && this._state.drawerOpen) || false,
      liveQ: liveQ,
      positions: positions,
      totalAsset: totalAsset,
      totalDeposit: totalDeposit,
      _pnlSummary: this._state && this._state._pnlSummary,
    };

    // 统一预加载：一次 range=all 请求 → _posCache + _allDailyData + drawer + summary
    if (location.protocol !== 'file:' && !this._allDataLoading && !this._allDataReady) {
      this._allDataLoading = true;
      var self = this;
      fetch('/api/pnl?range=all&index=' + self._state.index)
        .then(function(r) { return r.json(); })
        .then(function(d) {
          self._posCache = d;
          self._allDailyData = d;
          self._allDataReady = true;
          self._allDataLoading = false;
          self._updateDrawer(d);
          // 同时拉 summary（独立端点）
          return fetch('/api/pnl/summary').then(function(r) { return r.json(); });
        })
        .then(function(s) {
          if (s) { self._state._pnlSummary = s; self._updateSummary(); }
          // 如果仓位图已勾选且有缓存，自动绘制
          var tog = document.getElementById('pnl_pos_toggle_' + self.id);
          if (tog && tog.checked) {
            var ch = document.getElementById('pnl_pos_chart_' + self.id);
            if (ch) ch.style.display = '';
            self._drawPosChart();
          }
        })
        .catch(function() { self._allDataLoading = false; });
    }
    // 缓存已就绪时直接更新（后续 render 触发时）
    if (this._allDailyData) {
      this._updateDrawer(this._allDailyData);
      this._updateSummary();
    }

    var self = this;
    self._fetchChartData(function(chartData) {
      self._updateKPI(chartData);
      self._drawChart(chartData);
      self._drawPosChart();
    });
    // 恢复抽屉状态
    if (this._state.drawerOpen) {
      var drawer = document.getElementById('pnl_drawer_' + this.id);
      var btn = document.getElementById('pnl_drawer_btn_' + this.id);
      if (drawer) drawer.classList.add('pnl-drawer-open');
      if (btn) { btn.classList.add('pnl-drawer-btn-open'); btn.innerHTML = '📊 收起损益明细'; }
    }
    // 恢复 tab 激活态
    var root = document.getElementById('pnl_' + this.id);
    if (root) {
      root.querySelectorAll('.pnl-period').forEach(function(el) {
        el.classList.toggle('active', el.dataset.p === this._state.period);
      }, this);
      root.querySelectorAll('.pnl-idx-btn').forEach(function(el) {
        el.classList.toggle('active', el.dataset.idx === this._state.index);
      }, this);
    }
    this._bindEvents();
    this.updateTimestamp();
  }

  // ===== Layout =====
  _buildLayout() {
    return '<div class="pnl-root" id="pnl_' + this.id + '">' +
      // KPI row 1: 累计（慢变）
      '<div class="pnl-kpi" id="pnl_kpi1_' + this.id + '">' +
        '<div class="pnl-kpi-card"><div class="pnl-kpi-lbl">当前资产</div><div class="pnl-kpi-val" id="pnl_asset">—</div><div class="pnl-kpi-sub" id="pnl_asset_sub">—</div></div>' +
        '<div class="pnl-kpi-card"><div class="pnl-kpi-lbl">TWR累计</div><div class="pnl-kpi-val" id="pnl_twr">—</div><div class="pnl-kpi-sub" id="pnl_twr_sub">—</div></div>' +
        '<div class="pnl-kpi-card"><div class="pnl-kpi-lbl">基准累计</div><div class="pnl-kpi-val" id="pnl_bm_twr">—</div><div class="pnl-kpi-sub" id="pnl_bm_twr_sub">—</div></div>' +
        '<div class="pnl-kpi-card"><div class="pnl-kpi-lbl">累计超额 α</div><div class="pnl-kpi-val" id="pnl_alpha">—</div><div class="pnl-kpi-sub" id="pnl_alpha_sub">—</div></div>' +
        '<div class="pnl-kpi-card"><div class="pnl-kpi-lbl">历史最大回撤</div><div class="pnl-kpi-val" id="pnl_maxdd">—</div><div class="pnl-kpi-sub" id="pnl_maxdd_sub">—</div></div>' +
      '</div>' +
      // KPI row 2: 今日（实时变）
      '<div class="pnl-kpi" id="pnl_kpi2_' + this.id + '">' +
        '<div class="pnl-kpi-card pnl-kpi-dyn"><div class="pnl-kpi-lbl">今日浮动盈亏</div><div class="pnl-kpi-val" id="pnl_pnl">—</div><div class="pnl-kpi-sub" id="pnl_pnl_sub">—</div></div>' +
        '<div class="pnl-kpi-card pnl-kpi-dyn"><div class="pnl-kpi-lbl">今日仓位</div><div class="pnl-kpi-val" id="pnl_pos">—</div><div class="pnl-kpi-sub" id="pnl_pos_sub">—</div></div>' +
        '<div class="pnl-kpi-card pnl-kpi-dyn"><div class="pnl-kpi-lbl" id="pnl_period_label">今日TWR</div><div class="pnl-kpi-val" id="pnl_period_val">—</div><div class="pnl-kpi-sub" id="pnl_period_sub">—</div></div>' +
        '<div class="pnl-kpi-card pnl-kpi-dyn"><div class="pnl-kpi-lbl">今日超额 α</div><div class="pnl-kpi-val" id="pnl_today_alpha">—</div><div class="pnl-kpi-sub" id="pnl_today_alpha_sub">—</div></div>' +
        '<div class="pnl-kpi-card pnl-kpi-dyn"><div class="pnl-kpi-lbl" id="pnl_dd_label">今日回撤</div><div class="pnl-kpi-val" id="pnl_dd_val">—</div><div class="pnl-kpi-sub" id="pnl_dd_sub">—</div></div>' +
      '</div>' +
      // Controls
      '<div class="pnl-ctrl">' +
        '<span class="pnl-ctrl-label">对比</span>' +
        '<div class="pnl-index">' +
          '<button class="pnl-idx-btn active" data-idx="sh">上证</button>' +
          '<button class="pnl-idx-btn" data-idx="sz">深证</button>' +
          '<button class="pnl-idx-btn" data-idx="cy">创业板</button>' +
        '</div>' +
        '<div class="pnl-periods">' +
          '<button class="pnl-period active" data-p="today">日</button>' +
          '<button class="pnl-period" data-p="week">周</button>' +
          '<button class="pnl-period" data-p="month">月</button>' +
          '<button class="pnl-period" data-p="quarter">近三月</button>' +
          '<button class="pnl-period" data-p="year">近一年</button>' +
          '' +
        '</div>' +
      '</div>' +
      // Chart
      '<div class="pnl-chart-wrap"><canvas id="pnl_canvas_' + this.id + '"></canvas></div>' +
      // Legend
      '<div class="pnl-legend">' +
        '<div class="pnl-leg-item"><div class="pnl-leg-line" style="background:#DC2626"></div><span>账户收益(TWR)</span></div>' +
        '<div class="pnl-leg-item"><div class="pnl-leg-line" style="background:#2563EB"></div><span id="pnl_idx_label_' + this.id + '">上证指数</span></div>' +
        '<div class="pnl-leg-item" style="margin-left:auto;font-size:10px;color:var(--text-disabled)" id="pnl_ts_' + this.id + '">—</div>' +
      '</div>' +
      // 辅助功能行：仓位复选框
      '<div class="pnl-aux-row">' +
        '<label class="pnl-aux-label"><input type="checkbox" id="pnl_pos_toggle_' + this.id + '"> 显示仓位</label>' +
      '</div>' +
      // 仓位子图
      '<div class="pnl-pos-chart" id="pnl_pos_chart_' + this.id + '" style="display:none">' +
        '<canvas id="pnl_pos_canvas_' + this.id + '"></canvas>' +
      '</div>' +
      // Drawer trigger
      '<div class="pnl-drawer-trigger"><button class="pnl-drawer-btn" id="pnl_drawer_btn_' + this.id + '">📊 查看损益明细</button></div>' +
      // Drawer
      '<div class="pnl-drawer" id="pnl_drawer_' + this.id + '">' +
        '<table class="pnl-table"><thead><tr>' +
          '<th class="pnl-td-period">周期</th><th class="pnl-td-num">账户收益</th><th class="pnl-td-num">基准收益</th><th class="pnl-td-num">超额α</th><th class="pnl-td-num">最大回撤</th>' +
        '</tr></thead><tbody id="pnl_tbody_' + this.id + '"></tbody></table>' +
        '<div class="pnl-summary" id="pnl_summary_' + this.id + '"></div>' +
      '</div>' +
    '</div>';
  }

  // ===== Data helpers =====
  // 周期过滤（共用）
  _filterByPeriod(daily, period) {
    var now = new Date();
    var day = now.getDay() || 7;
    switch(period) {
      case 'week': { var dow = now.getDay(); var diff = dow === 0 ? -6 : 1 - dow; var mon = new Date(now); mon.setDate(now.getDate() + diff); mon.setHours(0,0,0,0); return daily.filter(function(d){return new Date(d.date)>=mon;}); }
      case 'month': return daily.filter(function(d){var dt=new Date(d.date); return dt.getMonth()===now.getMonth()&&dt.getFullYear()===now.getFullYear();});
      case 'quarter': { var q = new Date(now); q.setMonth(now.getMonth()-3); return daily.filter(function(d){return new Date(d.date)>=q;}); }
      case 'year': return daily.filter(function(d){return new Date(d.date).getFullYear()===now.getFullYear();});
      default: return daily.slice();
    }
  }
  _getIndexKey() { return this._state.index; }

  _fetchChartData(callback) {
    var period = this._state.period;
    var idx = this._state.index;
    var url = '/api/pnl?range=' + period + '&index=' + idx;
    if (location.protocol === 'file:') { callback(null); return; }
    var self = this;
    fetch(url).then(function(r) { return r.json(); })
      .then(function(data) {
        if (data && data.labels && data.labels.length) {
          if (!self._periodCache) self._periodCache = {};
          self._periodCache[period + '_' + idx] = data;
          callback(data);
        } else if (period === 'today') {
          // 非交易时间：保留上次今日缓存，图表停留在最后交易日
          var cached = (self._periodCache || {})['today_' + idx];
          callback(cached || null);
        } else {
          callback(null);
        }
      })
      .catch(function() { callback(null); });
  }

  _calcDD(chartData) {
    if (!chartData || !chartData.portfolio || chartData.portfolio.length < 2) return null;
    var p = chartData.portfolio;
    // 找最高点，然后往前（时间后）找最低点，计算最大回撤
    var bestPeak = { idx: 0, val: p[0] };
    var worstDD = { dd: 0, peak: null, trough: null };

    for (var i = 0; i < p.length; i++) {
      if (p[i] > bestPeak.val) {
        bestPeak = { idx: i, val: p[i] };
      }
      // 从当前最高点到当前位置的回撤
      var dd = p[i] - bestPeak.val;
      if (dd < worstDD.dd) {
        worstDD = {
          dd: Math.round(dd * 100) / 100,
          peak: { idx: bestPeak.idx, val: bestPeak.val },
          trough: { idx: i, val: p[i] }
        };
      }
    }
    return worstDD.dd < 0 ? worstDD : null;
  }

  // ===== KPI update =====
  _updateKPI(chartData) {
    var s = this._state;
    var asset = document.getElementById('pnl_asset');
    if (!asset) return;
    var pnlEl = document.getElementById('pnl_pnl');
    var posEl = document.getElementById('pnl_pos');

    // Current asset
    var ta = s.totalAsset;
    var hasAsset = ta && ta > 0;
    asset.textContent = hasAsset ? _pnlFmtMoney(ta) : '—';
    document.getElementById('pnl_asset_sub').textContent = ta ? '累计入金 ' + _pnlFmtMoney(s.totalDeposit) : '—';

    // Position P&L
    var mv = 0, cost = 0;
    (s.positions || []).forEach(function(p) {
      if ((p['状态']||'').indexOf('清') >= 0) return;
      var qty = parseFloat(String(p['数量']||'0').replace('股','')) || 0;
      var cp = parseFloat(p['成本']) || 0;
      var live = (s.liveQ || {})[p['代码']] || {};
      var cur = parseFloat(live['最新价']) || cp;
      mv += qty * cur;
      cost += qty * cp;
    });
    var pnlAmount = mv - cost;
    var pnlPct = ta > 0 ? (pnlAmount / ta * 100) : 0;
    var posPct = ta > 0 ? (mv / ta * 100) : 0;

    pnlEl.textContent = _pnlFmtMoney(pnlAmount);
    pnlEl.style.color = pnlAmount >= 0 ? 'var(--up)' : 'var(--down)';
    document.getElementById('pnl_pnl_sub').textContent = (pnlPct >= 0 ? '+' : '') + pnlPct.toFixed(2) + '% 浮动';

    posEl.textContent = posPct.toFixed(0) + '%';
    posEl.style.color = posPct > 80 ? 'var(--danger)' : posPct > 50 ? 'var(--warn)' : 'var(--accent)';
    // 时段平均仓位
    var posSub = (s.positions||[]).filter(function(p){return (p['状态']||'').indexOf('清')<0}).length + ' 只持仓';
    if (chartData && chartData.position && chartData.position.length) {
      var sumPos = 0;
      for (var pi = 0; pi < chartData.position.length; pi++) sumPos += chartData.position[pi];
      var avgPos = (sumPos / chartData.position.length).toFixed(1);
      posSub = '时段均值 ' + avgPos + '%';
    }
    document.getElementById('pnl_pos_sub').textContent = posSub;

    // Period KPI
    var periodLabel = { today:'今日', week:'本周', month:'本月', quarter:'近三月', year:'近一年' };
    var perStr = periodLabel[s.period] || s.period;
    document.getElementById('pnl_period_label').textContent = perStr + '净值变化';
    document.getElementById('pnl_dd_label').textContent = perStr + '回撤';

    // 今日：用实时持仓浮动盈亏；周/月/季/年：用 all-data 缓存算 TWR
    if (s.period === 'today') {
      document.getElementById('pnl_period_val').textContent = (pnlPct >= 0 ? '+' : '') + pnlPct.toFixed(2) + '%';
      document.getElementById('pnl_period_val').style.color = pnlPct >= 0 ? 'var(--up)' : 'var(--down)';
      document.getElementById('pnl_period_sub').textContent = '浮动盈亏/总资产';
    } else {
      var cache = this._posCache || this._allDailyData;
      if (cache && cache.dates && cache.dates.length) {
      var now = new Date();
      var dmap = {
        week: new Date(now.getFullYear(), now.getMonth(), now.getDate() - ((now.getDay()||7)-1)).toISOString().slice(0,10),
        month: now.toISOString().slice(0,7) + '-01',
        quarter: new Date(now.getFullYear(), now.getMonth()-3, 1).toISOString().slice(0,10),
        year: now.getFullYear() + '-01-01'
      };
      var fd = dmap[s.period] || cache.dates[0];
      var cP = 1.0, cB = 1.0, pk = -Infinity, md = 0, rp = 0;
      for (var i = 0; i < cache.dates.length; i++) {
        if (cache.dates[i] < fd) continue;
        cP *= (1 + cache.portfolio[i] / 100);
        cB *= (1 + cache.benchmark[i] / 100);
        rp = (cP - 1) * 100;
        if (rp > pk) pk = rp;
        if (rp - pk < md) md = rp - pk;
      }
      document.getElementById('pnl_period_val').textContent = ((cP-1)*100 >= 0 ? '+' : '') + ((cP-1)*100).toFixed(2) + '%';
      document.getElementById('pnl_period_val').style.color = (cP-1)*100 >= 0 ? 'var(--up)' : 'var(--down)';
      document.getElementById('pnl_period_sub').textContent = '超额 ' + (((cP-1)*100-(cB-1)*100) >= 0 ? '+' : '') + ((cP-1)*100-(cB-1)*100).toFixed(2) + '%';
      document.getElementById('pnl_dd_val').textContent = md.toFixed(2) + '%';
    } else if (chartData && chartData.portfolio && chartData.portfolio.length) {
      var cp = chartData.portfolio, cb = chartData.benchmark;
      var ddI = this._calcDD(chartData);
      var lastP = cp[cp.length-1];
      document.getElementById('pnl_period_val').textContent = (lastP >= 0 ? '+' : '') + lastP.toFixed(2) + '%';
      document.getElementById('pnl_period_val').style.color = lastP >= 0 ? 'var(--up)' : 'var(--down)';
      document.getElementById('pnl_period_sub').textContent = '超额 ' + (lastP-(cb[cb.length-1]) >= 0 ? '+' : '') + (lastP-cb[cb.length-1]).toFixed(2) + '%';
      document.getElementById('pnl_dd_val').textContent = (ddI ? ddI.dd : 0).toFixed(2) + '%';
    }
    document.getElementById('pnl_dd_val').style.color = 'var(--down)';

    // 今日超额 α α
    var todayAlphaEl = document.getElementById('pnl_today_alpha');
    if (todayAlphaEl && chartData && chartData.portfolio && chartData.benchmark) {
      var lastP = chartData.portfolio[chartData.portfolio.length - 1];
      var lastB = chartData.benchmark[chartData.benchmark.length - 1];
      if (lastP != null && lastB != null) {
        var ta = lastP - lastB;
        todayAlphaEl.textContent = (ta >= 0 ? '+' : '') + ta.toFixed(2) + '%';
        todayAlphaEl.style.color = ta >= 0 ? 'var(--up)' : 'var(--down)';
      }
    }
    var taSub = document.getElementById('pnl_today_alpha_sub');
    if (taSub) taSub.textContent = 'TWR−基准';

    // Row 1 标签联动
    var idxName2 = {sh:'上证', sz:'深证', cy:'创业'}[s.index] || '上证';
    var bmSub2 = document.getElementById('pnl_bm_twr_sub');
    if (bmSub2) bmSub2.textContent = idxName2 + '指数同期';

  }

  }

  _updateDrawer(allData) {
    var tbody = document.getElementById('pnl_tbody_' + this.id);
    if (!tbody) return;

    function pctStr(v) { return (isNaN(v) ? '—' : (v >= 0 ? '+' : '') + v.toFixed(2) + '%'); }

    var ad = this._allDailyData;
    if (!ad || !ad.dates || !ad.dates.length) return;

    // 从 _allDailyData 按日期过滤 + TWR 连乘（秒开，无需等 _periodCache）
    function computePeriod(fromDateStr) {
      var tP = 1.0, tB = 1.0, tPk = -Infinity, tDD = 0, tRP = 0;
      var hasData = false;
      for (var i = 0; i < ad.dates.length; i++) {
        if (ad.dates[i] < fromDateStr) continue;
        hasData = true;
        tP *= (1 + ad.portfolio[i] / 100);
        tB *= (1 + ad.benchmark[i] / 100);
        tRP = (tP - 1) * 100;
        if (tRP > tPk) tPk = tRP;
        if (tRP - tPk < tDD) tDD = tRP - tPk;
      }
      if (!hasData) return null;
      return { pnl: (tP - 1) * 100, bm: (tB - 1) * 100, dd: tDD };
    }

    // 周无数据 → 回退到最近有数据的周一
    function fallbackWeek(fd) {
      var result = computePeriod(fd);
      if (result) return result;
      // 找最近有数据的周一
      var dates = ad.dates || [];
      if (!dates.length) return null;
      var lastDate = dates[dates.length - 1];
      var lastD = new Date(lastDate);
      var dow = lastD.getDay() || 7;
      var fallbackMon = new Date(lastD);
      fallbackMon.setDate(lastD.getDate() - dow + 1);
      var fbStr = fallbackMon.toISOString().slice(0, 10);
      if (fbStr === fd) return null; // 避免死循环
      return computePeriod(fbStr);
    }

    var now = new Date();
    var dow = now.getDay();
    var weekStart = new Date(now); weekStart.setDate(now.getDate() + (dow === 0 ? -6 : 1 - dow));
    var fromDates = {
      today:     now.toISOString().slice(0, 10),
      week:      weekStart.toISOString().slice(0, 10),
      month:     new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10),
      quarter:   new Date(now.getFullYear(), now.getMonth() - 3, 1).toISOString().slice(0, 10),
      year:      now.getFullYear() + '-01-01',
    };
    var periods = ['today', 'week', 'month', 'quarter', 'year'];
    var labels  = ['日', '周', '月', '近三月', '近一年'];

    var html = '';
    var self = this;
    periods.forEach(function(p, i) {
      var result;
      if (p === 'today') {
        var ic = (self._periodCache || {})['today_' + self._state.index];
        if (ic && ic.portfolio && ic.portfolio.length >= 2) {
          var tP = 1.0, tB = 1.0, tPk = -Infinity, tDD = 0, tRP = 0;
          for (var j = 0; j < ic.portfolio.length; j++) {
            tP *= (1 + ic.portfolio[j] / 100);
            tB *= (1 + ic.benchmark[j] / 100);
            tRP = (tP - 1) * 100;
            if (tRP > tPk) tPk = tRP;
            if (tRP - tPk < tDD) tDD = tRP - tPk;
          }
          result = { pnl: (tP - 1) * 100, bm: (tB - 1) * 100, dd: tDD };
        }
      }
      if (!result && p === 'week') result = fallbackWeek(fromDates[p]);
      if (!result) result = computePeriod(fromDates[p]);

      if (!result) {
        html += '<tr><td class="pnl-td-period">' + labels[i] + '</td><td class="pnl-td-num" colspan="4">—</td></tr>';
      } else {
        html += '<tr>' +
          '<td class="pnl-td-period">' + labels[i] + '</td>' +
          '<td class="pnl-td-num" style="color:' + (result.pnl >= 0 ? 'var(--up)' : 'var(--down)') + '">' + pctStr(result.pnl) + '</td>' +
          '<td class="pnl-td-num" style="color:' + (result.bm >= 0 ? 'var(--up)' : 'var(--down)') + '">' + pctStr(result.bm) + '</td>' +
          '<td class="pnl-td-num" style="color:' + ((result.pnl - result.bm) >= 0 ? 'var(--up)' : 'var(--down)') + ';font-size:11px">' + pctStr(result.pnl - result.bm) + '</td>' +
          '<td class="pnl-td-num" style="color:var(--down)">' + pctStr(result.dd) + '</td>' +
        '</tr>';
      }
    });

    // 累计行：全量 _allDailyData TWR
    var cumResult = computePeriod('2020-01-01');
    if (cumResult) {
      html += '<tr class="pnl-cum-row">' +
        '<td class="pnl-td-period pnl-td-bold">累计</td>' +
        '<td class="pnl-td-num" style="color:' + (cumResult.pnl >= 0 ? 'var(--up)' : 'var(--down)') + '">' + pctStr(cumResult.pnl) + '</td>' +
        '<td class="pnl-td-num" style="color:' + (cumResult.bm >= 0 ? 'var(--up)' : 'var(--down)') + '">' + pctStr(cumResult.bm) + '</td>' +
        '<td class="pnl-td-num" style="color:' + ((cumResult.pnl - cumResult.bm) >= 0 ? 'var(--up)' : 'var(--down)') + ';font-size:11px">' + pctStr(cumResult.pnl - cumResult.bm) + '</td>' +
        '<td class="pnl-td-num" style="color:var(--down)">' + pctStr(cumResult.dd) + '</td>' +
      '</tr>';
    }
    tbody.innerHTML = html;
  }

  _updateSummary() {
    var s = this._state;
    var totalAsset = s.totalAsset || 0;

    // 从 _allDailyData 实时算 TWR + 基准 + 回撤（和抽屉同源）
    var cumReturn = 0, bmTWR = 0, histMaxDD = 0;
    if (this._allDailyData && this._allDailyData.portfolio && this._allDailyData.portfolio.length) {
      var ad = this._allDailyData;
      var cumB = 1.0, cumP = 1.0, pk = -Infinity, rp = 0;
      for (var i = 0; i < ad.portfolio.length; i++) {
        cumP *= (1 + ad.portfolio[i] / 100);
        cumB *= (1 + ad.benchmark[i] / 100);
        rp = (cumP - 1) * 100;
        if (rp > pk) pk = rp;
        if (rp - pk < histMaxDD) histMaxDD = rp - pk;
      }
      cumReturn = (cumP - 1) * 100;
      bmTWR = (cumB - 1) * 100;
    } else {
      // fallback: summary API
      var lastNav = (s._pnlSummary && s._pnlSummary.last_nav) || 1.0;
      cumReturn = (lastNav - 1) * 100;
    }
    var alpha = cumReturn - bmTWR;

    // Row 1: 累计 KPI
    var twrEl = document.getElementById('pnl_twr');
    if (twrEl) { twrEl.textContent = (cumReturn >= 0 ? '+' : '') + cumReturn.toFixed(2) + '%'; twrEl.style.color = cumReturn >= 0 ? 'var(--up)' : 'var(--down)'; }
    var twrSub = document.getElementById('pnl_twr_sub');
    if (twrSub) twrSub.textContent = '数据 ' + (this._allDailyData && this._allDailyData.dates && this._allDailyData.dates.length ? this._allDailyData.dates[0] : '2026-03-30') + ' 起';

    var bmEl = document.getElementById('pnl_bm_twr');
    if (bmEl) { bmEl.textContent = (bmTWR >= 0 ? '+' : '') + bmTWR.toFixed(2) + '%'; bmEl.style.color = bmTWR >= 0 ? 'var(--up)' : 'var(--down)'; }
    var bmSub = document.getElementById('pnl_bm_twr_sub');
    var idxName = {sh:'上证', sz:'深证', cy:'创业'}[this._state.index] || '上证';
    if (bmSub) bmSub.textContent = idxName + '指数同期';

    var aEl = document.getElementById('pnl_alpha');
    if (aEl) { aEl.textContent = (alpha >= 0 ? '+' : '') + alpha.toFixed(2) + '%'; aEl.style.color = alpha >= 0 ? 'var(--up)' : 'var(--down)'; }
    var aSub = document.getElementById('pnl_alpha_sub');
    if (aSub) aSub.textContent = 'TWR−基准';

    var ddEl = document.getElementById('pnl_maxdd');
    if (ddEl) { ddEl.textContent = histMaxDD.toFixed(2) + '%'; ddEl.style.color = 'var(--down)'; }
    var ddSub = document.getElementById('pnl_maxdd_sub');
    if (ddSub) ddSub.textContent = '历史最大';

    // 也更新抽屉底部汇总（保留兼容）
    var el = document.getElementById('pnl_summary_' + this.id);
    if (el) {
      el.innerHTML =
        '<div class="pnl-sum-cell"><div class="pnl-sum-lbl">数据起点</div><div class="pnl-sum-val">2026-03-30</div></div>';
    }
  }

  // 仓位子图
  _drawPosChart() {
    if (location.protocol === 'file:') return;
    var self = this;
    var canvas = document.getElementById('pnl_pos_canvas_' + this.id);
    if (!canvas) return;
    if (!self._posCache) return;   // 缓存未就绪，等统一预加载完成
    // 用缓存数据绘制
    var d = self._posCache;
    if (!d.labels || !d.labels.length) return;
        var now = new Date();
        var fromDate;
        switch(self._state.period) {
          case 'today': fromDate = new Date(now); fromDate.setDate(now.getDate()-1); break;
          case 'week': fromDate = new Date(now); fromDate.setDate(now.getDate() - (now.getDay()||7) + 1); break;
          case 'month': fromDate = new Date(now.getFullYear(), now.getMonth(), 1); break;
          case 'quarter': fromDate = new Date(now); fromDate.setMonth(now.getMonth()-3); break;
          case 'year': fromDate = new Date(now.getFullYear(), 0, 1); break;
          default: fromDate = new Date(2020,0,1);
        }
        var dates = [], posVals = [];
        var fullDates = d.dates || [];
        for (var i = 0; i < fullDates.length; i++) {
          var dd = new Date(fullDates[i]);  // full dates "2026-03-30"
          if (dd >= fromDate) {
            dates.push(d.labels[i]);  // short labels "03-30"
            posVals.push(d.position[i]);
          }
        }
        if (dates.length < 2) return;

        var rect2 = canvas.getBoundingClientRect();
        var W = rect2.width, H = rect2.height || 90;
        var DPR2 = window.devicePixelRatio || 1;
        canvas.width = W * DPR2;
        canvas.height = H * DPR2;
        canvas.style.width = W + 'px';
        canvas.style.height = H + 'px';
        var ctx = canvas.getContext('2d');
        ctx.scale(DPR2, DPR2);

        var PAD = { t: 8, r: 12, b: 16, l: 30 };
        var cw = W - PAD.l - PAD.r;
        var ch = H - PAD.t - PAD.b;

        ctx.clearRect(0, 0, W, H);
        ctx.fillStyle = '#FAFAF9';
        ctx.fillRect(0, 0, W, H);

        var n = dates.length;
        function xVal(i) { return PAD.l + (i / (n - 1)) * cw; }

        // Y auto-scale
        var posMin = Math.min.apply(null, posVals);
        var posMax = Math.max.apply(null, posVals);
        posMin = Math.floor(posMin / 10) * 10;
        posMax = Math.ceil(posMax / 10) * 10;
        if (posMax - posMin < 20) { posMax = posMin + 20; }
        if (posMin < 0) posMin = 0;

        function posY(v) { return PAD.t + ch - ((v - posMin) / (posMax - posMin)) * ch; }

        // 面积填充
        ctx.beginPath();
        ctx.moveTo(xVal(0), posY(posMin));
        for (var i = 0; i < n; i++) {
          ctx.lineTo(xVal(i), posY(posVals[i]));
        }
        ctx.lineTo(xVal(n-1), posY(posMin));
        ctx.closePath();
        ctx.fillStyle = 'rgba(217,119,6,0.15)';
        ctx.fill();

        // 线
        ctx.beginPath();
        for (var i = 0; i < n; i++) {
          var px = xVal(i), py = posY(posVals[i]);
          if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
        }
        ctx.strokeStyle = '#D97706';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Y labels — 3档
        ctx.fillStyle = '#8A8480';
        ctx.font = '8px -apple-system,sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillText(posMin + '%', PAD.l - 4, posY(posMin));
        ctx.fillText(Math.round((posMin+posMax)/2) + '%', PAD.l - 4, posY((posMin+posMax)/2));
        ctx.fillText(posMax + '%', PAD.l - 4, posY(posMax));

        // X labels — 只标日期
        if (n > 0) {
          ctx.textAlign = 'center';
          ctx.textBaseline = 'top';
          var labelStep = Math.max(1, Math.floor(n / 6));
          for (var i = 0; i < n; i += labelStep) {
            ctx.fillText(dates[i], xVal(i), PAD.t + ch + 2);
          }
        }
  }

  // ===== Chart =====
  _drawChart(chartData) {
    if (!chartData) return;
    var canvas = document.getElementById('pnl_canvas_' + this.id);
    if (!canvas) return;
    var rect = canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;

    var W = rect.width, H = rect.height;
    var DPR = window.devicePixelRatio || 1;
    canvas.width = W * DPR;
    canvas.height = H * DPR;
    var ctx = canvas.getContext('2d');
    ctx.scale(DPR, DPR);

    var ddInfo = this._calcDD(chartData);

    var PAD = { t: 24, r: 70, b: 30, l: 62 };
    var cw = W - PAD.l - PAD.r;
    var ch = H - PAD.t - PAD.b;
    if (cw < 50 || ch < 20) return;

    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#FFFFFF';
    ctx.fillRect(0, 0, W, H);

    if (!chartData || !chartData.portfolio || chartData.portfolio.length < 2) {
      ctx.fillStyle = '#8A8480';
      ctx.font = '13px -apple-system,sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('暂无数据，请确保 poll_live.py 运行中', W/2, H/2);
      return;
    }

    var p = chartData.portfolio;
    var b = chartData.benchmark;
    var pos = chartData.position;
    var n = p.length;

    // Scale — 跳过 null (未到时间的空槽)
    var validP = p.filter(function(v){return v != null;});
    var validB = b.filter(function(v){return v != null;});
    var allVals = validP.concat(validB);
    if (!allVals.length) { allVals = [0, 0]; }
    var absMax = Math.max(Math.abs(Math.min.apply(null, allVals)), Math.abs(Math.max.apply(null, allVals)));
    var step = absMax < 2 ? 0.5 : absMax < 5 ? 1 : 2;
    var maxY = Math.ceil(absMax / step) * step;
    var minY = -maxY;

    function yVal(v) { return v == null ? null : PAD.t + ch - ((v - minY) / (maxY - minY)) * ch; }
    function xVal(i) { return PAD.l + (i / (n - 1)) * cw; }

    // 画线段（null 处断开）
    function _drawSegments(vals, color, width, dash) {
      ctx.beginPath(); var started = false;
      if (dash) ctx.setLineDash(dash);
      for (var segI = 0; segI < n; segI++) {
        var sv = vals[segI], spy = yVal(sv);
        if (sv == null || spy == null) { started = false; continue; }
        if (!started) { ctx.moveTo(xVal(segI), spy); started = true; }
        else { ctx.lineTo(xVal(segI), spy); }
      }
      ctx.strokeStyle = color; ctx.lineWidth = width || 2; ctx.stroke(); ctx.setLineDash([]);
    }
    // 面积填充（null 处断开）
    function _fillArea(vals, grad) {
      var zy = yVal(0);
      for (var segI = 0; segI < n; segI++) {
        var sv = vals[segI], spy = yVal(sv);
        if (sv == null || spy == null) continue;
        ctx.beginPath(); ctx.moveTo(xVal(segI), zy); ctx.lineTo(xVal(segI), spy);
        var segEnd = segI;
        while (segEnd + 1 < n && vals[segEnd + 1] != null && yVal(vals[segEnd + 1]) != null) segEnd++;
        for (var j = segI + 1; j <= segEnd; j++) ctx.lineTo(xVal(j), yVal(vals[j]));
        ctx.lineTo(xVal(segEnd), zy); ctx.closePath();
        ctx.fillStyle = grad; ctx.fill();
        segI = segEnd;
      }
    }

    // 最大回撤：高点→低点 L形标注
    if (ddInfo && ddInfo.peak && ddInfo.trough) {
      var peakX = xVal(ddInfo.peak.idx), peakY = yVal(ddInfo.peak.val);
      var troughX = xVal(ddInfo.trough.idx), troughY = yVal(ddInfo.trough.val);

      // 峰谷圆点
      ctx.beginPath(); ctx.arc(peakX, peakY, 5, 0, Math.PI*2);
      ctx.fillStyle = '#D97706'; ctx.fill();
      ctx.strokeStyle = '#FFFFFF'; ctx.lineWidth = 2; ctx.stroke();

      ctx.beginPath(); ctx.arc(troughX, troughY, 5, 0, Math.PI*2);
      ctx.fillStyle = '#D97706'; ctx.fill();
      ctx.strokeStyle = '#FFFFFF'; ctx.lineWidth = 2; ctx.stroke();

      // L形虚线：先横后竖
      ctx.strokeStyle = 'rgba(217,119,6,0.5)';
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(peakX, peakY);     // 从峰开始
      ctx.lineTo(troughX, peakY);   // 横线到谷的X位置
      ctx.lineTo(troughX, troughY); // 竖线到谷
      ctx.stroke();
      ctx.setLineDash([]);

      // 标注
      ctx.fillStyle = '#D97706';
      ctx.font = 'bold 11px -apple-system,sans-serif';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'bottom';
      ctx.fillText('最大回撤 ' + ddInfo.dd.toFixed(2) + '%', troughX + 6, peakY - 4);
    }

    // Grid
    ctx.strokeStyle = '#F0EEEC';
    ctx.lineWidth = 1;
    for (var g = 0; g <= 4; g++) {
      ctx.beginPath();
      ctx.moveTo(PAD.l, PAD.t + (g/4) * ch);
      ctx.lineTo(PAD.l + cw, PAD.t + (g/4) * ch);
      ctx.stroke();
    }

    // Zero line — 加粗
    var zeroY = yVal(0);
    ctx.strokeStyle = '#D1CFC5';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(PAD.l, zeroY);
    ctx.lineTo(PAD.l + cw, zeroY);
    ctx.stroke();

    // Y left labels
    ctx.fillStyle = '#5C5652';
    ctx.font = '11px -apple-system,sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (var g = 0; g <= 4; g++) {
      var val = minY + (g/4) * (maxY - minY);
      ctx.fillText((val >= 0 ? '+' : '') + val.toFixed(2) + '%', PAD.l - 8, PAD.t + (g/4) * ch);
    }


    // X labels
    ctx.fillStyle = '#5C5652';
    ctx.font = '10px -apple-system,sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    var isToday = this._state.period === 'today';
    var isDaily = chartData.type === 'daily';
    var labelStep;
    if (isDaily) {
      labelStep = Math.max(1, Math.floor(n / 10));
    } else if (isToday) {
      labelStep = 6;  // today: 每30分钟（6×5min=66 slots）
    } else {
      labelStep = 48;  // week/month: 每天首条
      if (n <= 48) labelStep = Math.max(1, Math.floor(n / 8));
    }
    for (var xi = 0; xi < n; xi += labelStep) {
      var lbl = chartData.labels[xi];
      // week/month intraday标签: 只显示日期部分
      if (!isToday && !isDaily && lbl.length > 5) lbl = lbl.split(' ')[0] || lbl.slice(0, 5);
      ctx.fillText(lbl, xVal(xi), PAD.t + ch + 6);
    }
    // 始终显示最后一个标签
    if ((n - 1) % labelStep !== 0) {
      var lastLbl = chartData.labels[n-1];
      if (!isToday && !isDaily && lastLbl.length > 5) lastLbl = lastLbl.split(' ')[0] || lastLbl.slice(0, 5);
      ctx.fillText(lastLbl, xVal(n-1), PAD.t + ch + 6);
    }

    // Benchmark line
    _drawSegments(b, '#2563EB', 2, [6, 3]);

    // Area fill
    var grad = ctx.createLinearGradient(0, PAD.t, 0, PAD.t + ch);
    grad.addColorStop(0, 'rgba(220,38,38,0.12)');
    grad.addColorStop(1, 'rgba(220,38,38,0.01)');
    _fillArea(p, grad);

    // Portfolio line
    _drawSegments(p, '#DC2626', 2.5);

    // End labels — 用最后一个有效值
    var lastValidI = n - 1;
    while (lastValidI >= 0 && p[lastValidI] == null) lastValidI--;
    if (lastValidI < 0) lastValidI = n - 1;
    var lastPX = xVal(lastValidI);
    var lastP = p[lastValidI];
    var lastB = b[lastValidI];
    var idxName = {sh:'上证', sz:'深证', cy:'创业'}[this._getIndexKey()] || '上证';

    // 账户收益率 — 放在曲线末端右侧
    ctx.font = 'bold 11px -apple-system,sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#DC2626';
    ctx.fillText((lastP >= 0 ? '+' : '') + lastP.toFixed(2) + '%', lastPX + 4, yVal(lastP));

    // 指数 — 放在收益率下方
    ctx.fillStyle = '#2563EB';
    ctx.font = '10px -apple-system,sans-serif';
    ctx.fillText(idxName + ' ' + (lastB >= 0 ? '+' : '') + lastB.toFixed(2) + '%', lastPX + 4, yVal(lastB) + 15);

    // 保存数据供 hover 使用
    this._lastChartData = chartData;
    this._lastXVal = xVal;
    this._lastYVal = yVal;
  }

  // ===== Events =====
  _bindEvents() {
    var self = this;

    // 仓位子图切换
    var posToggle = document.getElementById('pnl_pos_toggle_' + this.id);
    if (posToggle) {
      posToggle.addEventListener('change', function() {
        var chart = document.getElementById('pnl_pos_chart_' + self.id);
        if (this.checked) {
          if (chart) chart.style.display = '';
          // 有缓存直接画，没缓存等预加载回调
          if (self._posCache) self._drawPosChart();
        } else {
          if (chart) chart.style.display = 'none';
        }
      });
    }
    var root = document.getElementById('pnl_' + this.id);
    if (!root) return;

    // Period tabs
    root.querySelectorAll('.pnl-period:not(.pnl-period-custom)').forEach(function(el) {
      el.addEventListener('click', function() {
        root.querySelectorAll('.pnl-period').forEach(function(b){b.classList.remove('active')});
        this.classList.add('active');
        self._state.period = this.dataset.p;
        self._fetchChartData(function(chartData) {
          self._updateKPI(chartData);
          self._drawChart(chartData);
          self._drawPosChart();
        });
      });
    });

    // Index selector
    root.querySelectorAll('.pnl-idx-btn').forEach(function(el) {
      el.addEventListener('click', function() {
        root.querySelectorAll('.pnl-idx-btn').forEach(function(b){b.classList.remove('active')});
        this.classList.add('active');
        self._state.index = this.dataset.idx;
        var label = document.getElementById('pnl_idx_label_' + self.id);
        if (label) label.textContent = this.textContent + '指数';
        // 重新拉 all 数据更新抽屉
        self._allDataReady = false;
        self._allDataLoading = false;
        fetch('/api/pnl?range=all&index=' + self._state.index)
          .then(function(r) { return r.json(); })
          .then(function(d) {
            self._allDailyData = d;
            self._posCache = d;
            self._allDataReady = true;
            self._updateDrawer(d);
            self._updateSummary();
            self._drawPosChart();
          });
        self._fetchChartData(function(chartData) {
          self._updateKPI(chartData);
          self._drawChart(chartData);
        });
      });
    });

    // Drawer toggle
    var btn = document.getElementById('pnl_drawer_btn_' + this.id);
    if (btn) {
      btn.addEventListener('click', function() {
        self._state.drawerOpen = !self._state.drawerOpen;
        var drawer = document.getElementById('pnl_drawer_' + self.id);
        if (drawer) drawer.classList.toggle('pnl-drawer-open', self._state.drawerOpen);
        this.classList.toggle('pnl-drawer-btn-open', self._state.drawerOpen);
        this.innerHTML = self._state.drawerOpen
          ? '📊 收起损益明细'
          : '📊 查看损益明细';
      });
    }

    // 清理旧十字线
    var oldCross = document.getElementById('pnl_cross_' + this.id);
    if (oldCross) oldCross.remove();

    // Hover: 竖线标记 + tooltip
    var mainCanvas = document.getElementById('pnl_canvas_' + this.id);
    if (mainCanvas) {
      mainCanvas.style.cursor = 'crosshair';

      // 创建十字线 div
      var crossEl = document.createElement('div');
      crossEl.id = 'pnl_cross_' + this.id;
      crossEl.style.cssText = 'position:absolute;top:0;width:1px;background:#D97706;pointer-events:none;z-index:10;display:none;border-left:1px dashed #D97706';
      mainCanvas.parentElement.appendChild(crossEl);

      mainCanvas.addEventListener('mousemove', function(e) {
        var rect = mainCanvas.getBoundingClientRect();
        var mx = e.clientX - rect.left;
        var cd = self._lastChartData;
        if (!cd || !cd.labels || !cd.labels.length) return;
        var PAD = { t: 24, r: 70, b: 30, l: 62 };
        var cw = rect.width - PAD.l - PAD.r;
        var n = cd.labels.length;
        var idx = Math.round(((mx - PAD.l) / cw) * (n - 1));
        if (idx < 0 || idx >= n) { crossEl.style.display = 'none'; return; }

        // 十字线位置
        crossEl.style.display = 'block';
        crossEl.style.left = (PAD.l + (idx / (n - 1)) * cw) + 'px';
        crossEl.style.height = (rect.height - PAD.t - PAD.b) + 'px';
        crossEl.style.top = PAD.t + 'px';

        // tooltip
        var tip = document.getElementById('pnl_tooltip_' + self.id);
        if (!tip) {
          tip = document.createElement('div');
          tip.id = 'pnl_tooltip_' + self.id;
          tip.style.cssText = 'position:fixed;background:var(--bg-card,#FFFFFF);color:var(--text-primary,#2D2926);padding:6px 10px;border-radius:4px;border:1px solid var(--border,#E5E2DE);font-size:11px;pointer-events:none;z-index:9999;line-height:1.6;font-family:var(--font-mono);box-shadow:0 2px 8px rgba(0,0,0,0.1)';
          document.body.appendChild(tip);
        }
        var isDaily = cd.type === 'daily';
        var lbl = cd.labels[idx];
        if (!isDaily && lbl.length > 5) lbl = lbl.split(' ')[0];
        tip.innerHTML =
          '<b>' + (isDaily ? '' : '') + lbl + '</b>' +
          '<br>收益 <span style=\"color:' + (cd.portfolio[idx] >= 0 ? '#DC2626' : '#059669') + '\">' +
          (cd.portfolio[idx] >= 0 ? '+' : '') + cd.portfolio[idx].toFixed(2) + '%</span>' +
          '<br>指数 <span style=\"color:' + (cd.benchmark[idx] >= 0 ? '#DC2626' : '#059669') + '\">' +
          (cd.benchmark[idx] >= 0 ? '+' : '') + cd.benchmark[idx].toFixed(2) + '%</span>' +
          (cd.position[idx] != null ? '<br>仓位 ' + cd.position[idx].toFixed(1) + '%' : '');
        tip.style.left = (e.clientX + 14) + 'px';
        tip.style.top = (e.clientY - 10) + 'px';
        tip.style.display = 'block';
      });
      mainCanvas.addEventListener('mouseleave', function() {
        var tip = document.getElementById('pnl_tooltip_' + self.id);
        if (tip) tip.style.display = 'none';
        crossEl.style.display = 'none';
      });
    }

  }

  onResize(w, h) {
    if (this._lastChartData) this._drawChart(this._lastChartData);
    if (this._posCache) this._drawPosChart();
  }
}

// ===== Utilities =====
WidgetRegistry.register('W22', PnLCurveWidget);

// 工具函数
var _pnlFmtMoney = function(v) {
  v = parseFloat(v) || 0;
  if (Math.abs(v) >= 1e8) return (v/1e8).toFixed(2) + '亿';
  if (Math.abs(v) >= 1e4) return (v/1e4).toFixed(1) + '万';
  return v.toFixed(0);
};
