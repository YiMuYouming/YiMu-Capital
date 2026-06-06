// widgets/pnl-curve.js — W22 账户收益曲线
// Canvas 折线图: 账户TWR收益 vs 指数参考 + 仓位 + 自动回撤高亮
'use strict';

function hasW22Own(obj, key) {
  return Object.prototype.hasOwnProperty.call(obj || {}, key);
}


class PnLCurveWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    // 首次渲染建 DOM + 绑定事件，后续只更新数据
    var firstRender = !this._layoutBuilt;
    if (firstRender) {
      body.innerHTML = this._buildLayout();
      this._layoutBuilt = true;
    }

    var liveQ = (data && data.live_quotes) || {};
    // 和 W15 同源：账户 SSOT 优先，旧本地持仓仅为接口不可用时兜底。
    var manual = DataStore.manualData.getAll();
    var positions;
    var pnlCfg = (data && data.pnl) || {};
    var pnlLive = (data && data.pnl_live) || {};
    if (Array.isArray(pnlLive.positions)) {
      positions = pnlLive.positions;
    } else {
      try {
        positions = JSON.parse(manual['_positions'] || 'null');
        if (!positions || !positions.length) positions = (data && data.positions) || [];
      } catch(e) {
        positions = (data && data.positions) || [];
      }
    }
    var hasPnlLiveAsset = hasW22Own(pnlLive, 'total_asset');
    var hasPnlLiveDeposit = hasW22Own(pnlLive, 'total_deposit');
    var totalAsset = hasPnlLiveAsset
      ? (pnlLive.total_asset == null ? null : parseFloat(pnlLive.total_asset))
      : (pnlCfg['总资产'] != null ? parseFloat(pnlCfg['总资产']) : ((this._state && this._state.totalAsset != null) ? this._state.totalAsset : 0));
    var totalDeposit = hasPnlLiveDeposit
      ? pnlLive.total_deposit
      : (hasPnlLiveAsset ? null : (pnlCfg['累计入金'] != null ? pnlCfg['累计入金'] : ((this._state && this._state.totalDeposit != null) ? this._state.totalDeposit : 0)));

    this._state = {
      period: (this._state && this._state.period) || 'today',
      index: (this._state && this._state.index) || 'sh',
      drawerOpen: (this._state && this._state.drawerOpen) || false,
      liveQ: liveQ,
      positions: positions,
      totalAsset: totalAsset,
      totalDeposit: totalDeposit,
      pnlLive: pnlLive,
      _pnlSummary: this._state && this._state._pnlSummary,
    };

    // 统一预加载：一次 range=all 请求 → _allDailyData + drawer + summary
    if (location.protocol !== 'file:' && !this._allDataLoading && !this._allDataReady) {
      this._allDataLoading = true;
      var self = this;
      fetch('/api/pnl?range=all&index=' + self._state.index)
        .then(function(r) { return r.json(); })
        .then(function(d) {
          self._allDailyData = d;
          self._allDataReady = true;
          self._allDataLoading = false;
          self._updateDrawer(d);
          return fetch('/api/pnl/summary').then(function(r) { return r.json(); });
        })
        .then(function(s) {
          if (s) {
            self._state._pnlSummary = s;
            if (hasW22Own(s, 'total_asset')) self._state.totalAsset = s.total_asset;
            self._state.pnlLive = s;
            if (Array.isArray(s.positions)) self._state.positions = s.positions;
            if (hasW22Own(s, 'total_deposit')) self._state.totalDeposit = s.total_deposit;
            self._updateSummary();
            // 用真实总资产刷新 KPI
            self._fetchChartData(function(cd) {
              self._updateKPI(cd);
              self._drawChart(cd);
            });
          }
        })
        .catch(function() { self._allDataLoading = false; });
    }
    if (this._allDailyData) {
      this._updateDrawer(this._allDailyData);
      this._updateSummary();
    }

    var self = this;
    self._fetchChartData(function(chartData) {
      self._updateKPI(chartData);
      self._drawChart(chartData);
    });
    // 恢复抽屉状态
    if (this._state.drawerOpen) {
      var drawer = document.getElementById('pnl_drawer_' + this.id);
      var btn = document.getElementById('pnl_drawer_btn_' + this.id);
      if (drawer) drawer.classList.add('pnl-drawer-open');
      if (btn) { btn.classList.add('pnl-drawer-btn-open'); btn.innerHTML = '收起损益明细'; }
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
    if (firstRender) this._bindEvents();
    this.updateTimestamp();
  }

  // ===== Layout =====
  _buildLayout() {
    return '<div class="pnl-root" id="pnl_' + this.id + '">' +
      // KPI row 1: 累计（慢变）
      '<div class="pnl-kpi" id="pnl_kpi1_' + this.id + '">' +
        '<div class="pnl-kpi-card"><div class="pnl-kpi-lbl"><span class="evidence-inline-ref">E4</span>当前资产</div><div class="pnl-kpi-val" id="pnl_asset">—</div><div class="pnl-kpi-sub" id="pnl_asset_sub">—</div></div>' +
        '<div class="pnl-kpi-card"><div class="pnl-kpi-lbl">TWR累计</div><div class="pnl-kpi-val" id="pnl_twr">—</div><div class="pnl-kpi-sub" id="pnl_twr_sub">—</div></div>' +
        '<div class="pnl-kpi-card"><div class="pnl-kpi-lbl">指数参考</div><div class="pnl-kpi-val" id="pnl_bm_twr">—</div><div class="pnl-kpi-sub" id="pnl_bm_twr_sub">—</div></div>' +
        '<div class="pnl-kpi-card"><div class="pnl-kpi-lbl">相对指数</div><div class="pnl-kpi-val" id="pnl_alpha">—</div><div class="pnl-kpi-sub" id="pnl_alpha_sub">—</div></div>' +
        '<div class="pnl-kpi-card"><div class="pnl-kpi-lbl">历史最大回撤</div><div class="pnl-kpi-val" id="pnl_maxdd">—</div><div class="pnl-kpi-sub" id="pnl_maxdd_sub">—</div></div>' +
      '</div>' +
      // KPI row 2: 今日（实时变）
      '<div class="pnl-kpi" id="pnl_kpi2_' + this.id + '">' +
        '<div class="pnl-kpi-card pnl-kpi-dyn"><div class="pnl-kpi-lbl">今日盈亏</div><div class="pnl-kpi-val" id="pnl_pnl">—</div><div class="pnl-kpi-sub" id="pnl_pnl_sub">—</div></div>' +
        '<div class="pnl-kpi-card pnl-kpi-dyn"><div class="pnl-kpi-lbl">今日仓位</div><div class="pnl-kpi-val" id="pnl_pos">—</div><div class="pnl-kpi-sub" id="pnl_pos_sub">—</div></div>' +
        '<div class="pnl-kpi-card pnl-kpi-dyn"><div class="pnl-kpi-lbl" id="pnl_period_label">今日TWR</div><div class="pnl-kpi-val" id="pnl_period_val">—</div><div class="pnl-kpi-sub" id="pnl_period_sub">—</div></div>' +
        '<div class="pnl-kpi-card pnl-kpi-dyn"><div class="pnl-kpi-lbl">今日相对指数</div><div class="pnl-kpi-val" id="pnl_today_alpha">—</div><div class="pnl-kpi-sub" id="pnl_today_alpha_sub">—</div></div>' +
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
      '<div class="pnl-chart-wrap"><canvas class="pnl-chart" id="pnl_canvas_' + this.id + '"></canvas><div class="ui-empty pnl-chart-empty" id="pnl_empty_' + this.id + '"><div class="ui-empty-title">收益曲线暂无数据</div><div class="ui-empty-detail">等待盘中收益快照或历史曲线返回。</div></div></div>' +
      // Legend
      '<div class="pnl-legend">' +
        '<div class="pnl-leg-item"><div class="pnl-leg-line pnl-leg-portfolio"></div><span>账户收益(TWR)</span></div>' +
        '<div class="pnl-leg-item"><div class="pnl-leg-line pnl-leg-benchmark"></div><span id="pnl_idx_label_' + this.id + '">上证指数参考</span></div>' +
        '<div class="pnl-leg-item pnl-leg-ts" id="pnl_ts_' + this.id + '">—</div>' +
      '</div>' +
      // Drawer trigger
      '<div class="pnl-drawer-trigger"><button class="pnl-drawer-btn" id="pnl_drawer_btn_' + this.id + '">查看损益明细</button></div>' +
      // Drawer
      '<div class="pnl-drawer" id="pnl_drawer_' + this.id + '">' +
        '<table class="pnl-table"><thead><tr>' +
          '<th class="pnl-td-period">周期</th><th class="pnl-td-num">账户收益</th><th class="pnl-td-num">指数参考</th><th class="pnl-td-num">相对指数</th><th class="pnl-td-num">最大回撤</th>' +
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
    var key = period + '_' + idx;
    var url = '/api/pnl?range=' + period + '&index=' + idx;
    if (location.protocol === 'file:') { callback(null); return; }
    var self = this;
    if (!self._periodCache) self._periodCache = {};
    if (!self._periodFetchedAt) self._periodFetchedAt = {};
    if (!self._chartFetchLoading) self._chartFetchLoading = {};
    if (!self._chartFetchCallbacks) self._chartFetchCallbacks = {};

    var cached = self._periodCache[key];
    var fetchedAt = self._periodFetchedAt[key] || 0;
    if (cached && Date.now() - fetchedAt < 15000) {
      callback(cached);
      return;
    }

    if (self._chartFetchLoading[key]) {
      self._chartFetchCallbacks[key].push(callback);
      return;
    }

    self._chartFetchLoading[key] = true;
    self._chartFetchCallbacks[key] = [callback];

    function finish(data) {
      self._chartFetchLoading[key] = false;
      var callbacks = self._chartFetchCallbacks[key] || [];
      delete self._chartFetchCallbacks[key];
      callbacks.forEach(function(cb) { cb(data); });
    }

    fetch(url).then(function(r) { return r.json(); })
      .then(function(data) {
        if (data && data.labels && data.labels.length) {
          self._periodCache[key] = data;
          self._periodFetchedAt[key] = Date.now();
          finish(data);
        } else if (period === 'today') {
          // 非交易时间：保留上次今日缓存，图表停留在最后交易日
          finish(cached || null);
        } else {
          finish(null);
        }
      })
      .catch(function() { finish(cached || null); });
  }

  _calcDD(chartData) {
    if (!chartData || !chartData.portfolio || chartData.portfolio.length < 2) return null;
    var raw = chartData.portfolio;
    // 前值填充 null（被删脏数据/断连），供回撤计算用
    var p = [], last = null;
    for (var i = 0; i < raw.length; i++) {
      if (raw[i] != null) { last = raw[i]; p.push(raw[i]); }
      else { p.push(last); }
    }
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

    // Current asset — null=不可用, 0=合法零值
    var ta = s.totalAsset;
    var taNull = ta == null;
    var pnlLive = s.pnlLive || {};
    var anchorBlocked = pnlLive.anchor_blocked === true;
    var valuationBad = pnlLive.valuation_complete === false || anchorBlocked;
    var quoteStatus = pnlLive.quote_status || '';
    var isPostClose = quoteStatus === 'close_snapshot';
    var isQuoteUnavailable = valuationBad && !isPostClose;

    if (anchorBlocked) {
      asset.textContent = '—';
      document.getElementById('pnl_asset_sub').textContent = '锚点阻断 — 估值不可信';
    } else if (valuationBad && !isPostClose) {
      asset.textContent = taNull ? '—' : ta.toLocaleString();
      document.getElementById('pnl_asset_sub').textContent = taNull ? '行情缺失 — 估值不可信' : '行情缺失 · 非实时估值';
    } else if (isPostClose) {
      asset.textContent = taNull ? '—' : ta.toLocaleString();
      document.getElementById('pnl_asset_sub').textContent = '收盘快照 · 非实时';
    } else {
      asset.textContent = taNull ? '—' : ta.toLocaleString();
      var subText = taNull ? '—' : '累计入金 ' + _pnlFmtMoney(s.totalDeposit);
      // 回退历史标记
      if (chartData && chartData.is_fallback) {
        subText = (chartData.data_date || '?') + ' 回退 · 非今日实时';
      }
      document.getElementById('pnl_asset_sub').textContent = subText;
    }

    // Position P&L: 今日盈亏 = 现价 - 昨收（从涨幅反推），不是累计成本浮盈
    var mv = 0, todayChg = 0, missingQuotes = 0, missingBaseline = 0, missingRealized = 0;
    (s.positions || []).forEach(function(p) {
      var st = p['状态'] || '';
      if (st.indexOf('清') >= 0 || st.indexOf('删除') >= 0) {
        if (p['realized_today_pnl'] == null && p['today_pnl'] == null) {
          missingRealized++;
        }
        return;
      }
      var qty = parseFloat(String(p['数量']||'0').replace('股','')) || 0;
      var live = (s.liveQ || {})[p['代码']] || {};
      var cur = parseFloat(live['最新价']) || 0;
      if (!(cur > 0)) {
        missingQuotes++;
        return;
      }
      if (p['_day_start_price'] == null && p['today_pnl'] == null) {
        missingBaseline++;
        mv += qty * cur;
        return;
      }
      var chgPct = parseFloat(String(live['涨幅']||'0').replace('%','')) || 0;
      var yestClose = chgPct !== 0 ? Math.round(cur / (1 + chgPct / 100) * 100) / 100 : cur;
      mv += qty * cur;
      todayChg += qty * (cur - yestClose);
    });
    // SSOT mv — null=不可用, 0=合法空仓
    var ssotMv = (s.pnlLive || {}).mv;
    if (ssotMv != null) mv = parseFloat(ssotMv);
    var hasLivePnl = (s.pnlLive || {}).pnl_amount != null;
    var todayPnl = hasLivePnl ? parseFloat(s.pnlLive.pnl_amount) : todayChg;
    var todayPnlPct = (s.pnlLive || {}).pnl_pct != null ? parseFloat(s.pnlLive.pnl_pct) : (taNull ? null : (ta > 0 ? (todayChg / ta * 100) : 0));
    var ssotPosPct = (s.pnlLive || {}).pos_pct;
    var posPct = ssotPosPct != null ? parseFloat(ssotPosPct) : (taNull ? 0 : (ta > 0 ? (mv / ta * 100) : 0));
    var missingPnlBasis = !hasLivePnl && (missingQuotes > 0 || missingBaseline > 0 || missingRealized > 0);
    function _missingPnlBasisText(isClose) {
      var parts = [];
      if (missingQuotes > 0) parts.push(isClose ? '行情缺失' : '行情缺失 ' + missingQuotes + ' 只');
      if (missingBaseline > 0) parts.push('基线缺失 ' + missingBaseline + ' 只');
      if (missingRealized > 0) parts.push('今日收益基线缺失 ' + missingRealized + ' 只');
      return parts.join(' · ');
    }

    if (isQuoteUnavailable) {
      pnlEl.textContent = '—';
      pnlEl.style.color = 'var(--text-disabled)';
      document.getElementById('pnl_pnl_sub').textContent = '估值不可信';
      posEl.textContent = '—';
      posEl.style.color = 'var(--text-disabled)';
    } else if (isPostClose) {
      pnlEl.textContent = missingPnlBasis ? '—' : (todayPnl >= 0 ? '+' : '') + todayPnl.toLocaleString();
      pnlEl.style.color = missingPnlBasis ? 'var(--text-disabled)' : (todayPnl >= 0 ? 'var(--up)' : 'var(--down)');
      var closeSub = '';
      if (missingPnlBasis) { closeSub = _missingPnlBasisText(true); }
      else if (missingBaseline > 0) { closeSub = '基线缺失 ' + missingBaseline + ' 只'; }
      else if (missingRealized > 0) { closeSub = '今日收益基线缺失 ' + missingRealized + ' 只'; }
      else { closeSub = (todayPnlPct >= 0 ? '+' : '') + todayPnlPct.toFixed(2) + '% 收盘'; }
      document.getElementById('pnl_pnl_sub').textContent = closeSub;
      posEl.textContent = posPct.toFixed(0) + '%';
      posEl.style.color = posPct > 80 ? 'var(--danger)' : posPct > 50 ? 'var(--warn)' : 'var(--accent)';
    } else {
      pnlEl.textContent = missingPnlBasis ? '—' : (todayPnl >= 0 ? '+' : '') + todayPnl.toLocaleString();
      pnlEl.style.color = missingPnlBasis ? 'var(--text-disabled)' : (todayPnl >= 0 ? 'var(--up)' : 'var(--down)');
      var subLabel = '';
      if (missingPnlBasis) { subLabel = _missingPnlBasisText(false); }
      else if (missingBaseline > 0) { subLabel = '基线缺失 ' + missingBaseline + ' 只'; }
      else if (missingRealized > 0) { subLabel = '今日收益基线缺失 ' + missingRealized + ' 只'; }
      else { subLabel = (todayPnlPct >= 0 ? '+' : '') + todayPnlPct.toFixed(2) + '% 今日'; }
      document.getElementById('pnl_pnl_sub').textContent = subLabel;

      posEl.textContent = posPct.toFixed(0) + '%';
      posEl.style.color = posPct > 80 ? 'var(--danger)' : posPct > 50 ? 'var(--warn)' : 'var(--accent)';
    }
    document.getElementById('pnl_pos_sub').textContent = (s.positions||[]).filter(function(p){return (p['状态']||'').indexOf('清')<0&&(p['状态']||'').indexOf('删除')<0}).length + ' 只持仓';

    // Period KPI — 标签联动
    // Phase 5: 估值不可信时所有动态 KPI 同步置不可用
    if (isQuoteUnavailable) {
      var dynIds = ['pnl_period_val', 'pnl_dd_val', 'pnl_today_alpha'];
      dynIds.forEach(function(id) {
        var el = document.getElementById(id);
        if (el) { el.textContent = '—'; el.style.color = 'var(--text-disabled)'; }
      });
      ['pnl_period_sub', 'pnl_dd_sub', 'pnl_today_alpha_sub'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.textContent = '估值不可信';
      });
    }
    var isFallback = chartData && chartData.is_fallback;
    var fbDate = isFallback ? (chartData.data_date || '?') : '';
    var periodLabel = { today:'今日', week:'近一周', month:'近一月', quarter:'近三月', year:'近一年' };
    var perStr = periodLabel[s.period] || s.period;
    if (isFallback && s.period === 'today') {
      perStr = fbDate + ' 回退';
    }
    var pnlLabelEl = document.getElementById('pnl_period_label');
    if (pnlLabelEl) pnlLabelEl.textContent = perStr + ' TWR';
    var ddLabelEl = document.getElementById('pnl_dd_label');
    if (ddLabelEl) ddLabelEl.textContent = perStr + ' 回撤';
    // 相对指数标签联动
    var alphaEl = document.getElementById('pnl_today_alpha');
    if (alphaEl) {
      var alphaLbl = alphaEl.parentElement.querySelector('.pnl-kpi-lbl');
      if (alphaLbl) alphaLbl.textContent = perStr + ' 相对指数';
    }

    // 今日：用实时持仓浮动盈亏 + 日内的回撤/相对指数
    if (s.period === 'today') {
      if (isQuoteUnavailable) {
        document.getElementById('pnl_period_val').textContent = '—';
        document.getElementById('pnl_period_val').style.color = 'var(--text-disabled)';
        document.getElementById('pnl_period_sub').textContent = '估值不可信';
        document.getElementById('pnl_dd_val').textContent = '—';
        document.getElementById('pnl_dd_val').style.color = 'var(--text-disabled)';
        var todayAlphaEl2 = document.getElementById('pnl_today_alpha');
        if (todayAlphaEl2) {
          todayAlphaEl2.textContent = '—';
          todayAlphaEl2.style.color = 'var(--text-disabled)';
        }
      } else if (chartData && chartData.portfolio && chartData.portfolio.length) {
        var _n = chartData.portfolio.length, _lastI = _n - 1;
        while (_lastI >= 0 && chartData.portfolio[_lastI] == null) _lastI--;
        var lastPnl = _lastI >= 0 ? chartData.portfolio[_lastI] : null;
        var liveTodayPnl = (s.pnlLive || {}).pnl_pct != null ? parseFloat(s.pnlLive.pnl_pct) : lastPnl;
        document.getElementById('pnl_period_val').textContent = liveTodayPnl != null ? ((liveTodayPnl >= 0 ? '+' : '') + liveTodayPnl.toFixed(2) + '%') : '—';
        document.getElementById('pnl_period_val').style.color = liveTodayPnl != null ? (liveTodayPnl >= 0 ? 'var(--up)' : 'var(--down)') : 'var(--text-disabled)';
        var fallbackLabel = chartData.is_fallback ? (chartData.data_date || '?') + ' 回退' : '实时收益';
        document.getElementById('pnl_period_sub').textContent = chartData.is_fallback ? fallbackLabel : '实时收益';
        var ddI = this._calcDD(chartData);
        document.getElementById('pnl_dd_val').textContent = (ddI ? ddI.dd : 0).toFixed(2) + '%';
        var lastB = chartData.benchmark && _lastI >= 0 ? chartData.benchmark[_lastI] : null;
        var todayAlphaEl = document.getElementById('pnl_today_alpha');
        if (todayAlphaEl && lastB != null) {
          var ta = liveTodayPnl - lastB;
          todayAlphaEl.textContent = (ta >= 0 ? '+' : '') + ta.toFixed(2) + '%';
          todayAlphaEl.style.color = ta >= 0 ? 'var(--up)' : 'var(--down)';
        }
        if (chartData.is_fallback) {
          var alphaSubEl = document.getElementById('pnl_today_alpha_sub');
          if (alphaSubEl) alphaSubEl.textContent = fallbackLabel + ' TWR−指数参考';
        }
      }
    } else {
      if (isQuoteUnavailable) return;
      var cache = this._allDailyData;
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
      document.getElementById('pnl_period_sub').textContent = '相对指数 ' + (((cP-1)*100-(cB-1)*100) >= 0 ? '+' : '') + ((cP-1)*100-(cB-1)*100).toFixed(2) + '%';
      document.getElementById('pnl_dd_val').textContent = md.toFixed(2) + '%';
    } else if (chartData && chartData.portfolio && chartData.portfolio.length) {
      var cp = chartData.portfolio, cb = chartData.benchmark;
      var ddI = this._calcDD(chartData);
      var lastP = cp[cp.length-1];
      document.getElementById('pnl_period_val').textContent = (lastP >= 0 ? '+' : '') + lastP.toFixed(2) + '%';
      document.getElementById('pnl_period_val').style.color = lastP >= 0 ? 'var(--up)' : 'var(--down)';
      document.getElementById('pnl_period_sub').textContent = '相对指数 ' + (lastP-(cb[cb.length-1]) >= 0 ? '+' : '') + (lastP-cb[cb.length-1]).toFixed(2) + '%';
      document.getElementById('pnl_dd_val').textContent = (ddI ? ddI.dd : 0).toFixed(2) + '%';
    }
    document.getElementById('pnl_dd_val').style.color = 'var(--down)';

    // 今日相对指数
    var todayAlphaEl = document.getElementById('pnl_today_alpha');
    if (todayAlphaEl && chartData && chartData.portfolio && chartData.benchmark) {
      var lastValid = chartData.portfolio.length - 1;
      while (lastValid >= 0 && chartData.portfolio[lastValid] == null) lastValid--;
      var lastP = lastValid >= 0 ? chartData.portfolio[lastValid] : null;
      var lastB = lastValid >= 0 ? chartData.benchmark[lastValid] : null;
      if (lastP != null && lastB != null) {
        var ta = lastP - lastB;
        todayAlphaEl.textContent = (ta >= 0 ? '+' : '') + ta.toFixed(2) + '%';
        todayAlphaEl.style.color = ta >= 0 ? 'var(--up)' : 'var(--down)';
      }
    }
    var taSub = document.getElementById('pnl_today_alpha_sub');
    if (taSub) taSub.textContent = 'TWR−指数参考';

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
    // 周=最近5个交易日, 月=最近22个交易日
    var dates = ad.dates || [];
    var weekStart = dates.length >= 5 ? dates[dates.length - 5] : (dates[0] || '2020-01-01');
    var monthStart = dates.length >= 22 ? dates[dates.length - 22] : (dates[0] || '2020-01-01');
    var fromDates = {
      today:     now.toISOString().slice(0, 10),
      week:      weekStart,
      month:     monthStart,
      quarter:   new Date(now.getFullYear(), now.getMonth() - 3, 1).toISOString().slice(0, 10),
      year:      now.getFullYear() + '-01-01',
    };
    var periods = ['today', 'week', 'month', 'quarter', 'year'];
    var labels  = ['日', '近一周', '近一月', '近三月', '近一年'];

    var html = '';
    var self = this;
    periods.forEach(function(p, i) {
      var result;
      if (p === 'today') {
        var ic = (self._periodCache || {})['today_' + self._state.index];
        if (ic && ic.portfolio && ic.portfolio.length >= 2) {
          // intraday portfolio 是累计值（非单期收益率），取末值作为今日收益
          var lastI = ic.portfolio.length - 1;
          while (lastI >= 0 && ic.portfolio[lastI] == null) lastI--;
          if (lastI >= 0 && ic.portfolio[lastI] != null) {
            var todayPnl = ic.portfolio[lastI];
            var todayBm  = ic.benchmark[lastI] != null ? ic.benchmark[lastI] : 0;
            // 最大回撤：从累计序列中找峰谷差
            var pk = -Infinity, dd = 0;
            for (var j = 0; j <= lastI; j++) {
              if (ic.portfolio[j] == null) continue;
              if (ic.portfolio[j] > pk) pk = ic.portfolio[j];
              if (ic.portfolio[j] - pk < dd) dd = ic.portfolio[j] - pk;
            }
            result = { pnl: todayPnl, bm: todayBm, dd: dd };
          }
        }
      }
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
    var totalAsset = s.totalAsset != null ? s.totalAsset : null;

    // 从 _allDailyData 实时算 TWR + 指数参考 + 回撤（和抽屉同源）
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
    if (aSub) aSub.textContent = 'TWR−指数参考';

    var ddEl = document.getElementById('pnl_maxdd');
    if (ddEl) { ddEl.textContent = histMaxDD.toFixed(2) + '%'; ddEl.style.color = 'var(--down)'; }
    var ddSub = document.getElementById('pnl_maxdd_sub');
    if (ddSub) ddSub.textContent = '历史最大';

    // 抽屉底部汇总已移至 KPI 行，此处清空
    var el = document.getElementById('pnl_summary_' + this.id);
    if (el) { el.innerHTML = ''; }
  }

  // ===== Chart =====
  _setChartEmpty(show, detail) {
    var empty = document.getElementById('pnl_empty_' + this.id);
    if (!empty) return;
    empty.classList.toggle('is-visible', !!show);
    var detailEl = empty.querySelector ? empty.querySelector('.ui-empty-detail') : null;
    if (detailEl && detail) detailEl.textContent = detail;
  }

  _drawChart(chartData) {
    var canvas = document.getElementById('pnl_canvas_' + this.id);
    if (!canvas) return;
    if (!chartData) {
      this._setChartEmpty(true, '等待 /api/pnl 返回有效收益曲线。');
      return;
    }
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
      this._setChartEmpty(true, '请确认收益快照服务已返回至少两个采样点。');
      return;
    }
    this._setChartEmpty(false);

    var p = chartData.portfolio;
    var b = chartData.benchmark;
    var pos = chartData.position;
    var n = p.length;

    // 前值填充：中间 null（被删的脏数据/短暂断连）用上一个有效值填，首尾 null（未开盘/未到时间）保留
    function _forwardFill(arr) {
      var out = [], lastVal = null, seenValid = false;
      for (var i = 0; i < arr.length; i++) {
        if (arr[i] != null) { seenValid = true; lastVal = arr[i]; out.push(arr[i]); }
        else if (seenValid) { out.push(lastVal); }  // 数据中段null → 前值填充
        else { out.push(null); }  // 开盘前null → 保留
      }
      // 尾部 null → 恢复为 null（未来时间不填充）
      for (var j = out.length - 1; j >= 0 && out[j] === lastVal && arr[j] == null; j--) {
        out[j] = null;
      }
      return out;
    }

    var pFilled = _forwardFill(p);
    var bFilled = _forwardFill(b);
    var posFilled = _forwardFill(pos);

    // Scale — 跳过 null (未到时间的空槽)
    var validP = pFilled.filter(function(v){return v != null;});
    var validB = bFilled.filter(function(v){return v != null;});
    var allVals = validP.concat(validB);
    if (!allVals.length) { allVals = [0, 0]; }
    var absMax = Math.max(Math.abs(Math.min.apply(null, allVals)), Math.abs(Math.max.apply(null, allVals)));
    if (absMax === 0) absMax = 1;  // 全零序列避免 maxY=minY=0 导致 NaN
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
      ctx.textBaseline = 'bottom';
      var label = '最大回撤 ' + ddInfo.dd.toFixed(2) + '%';
      var labelW = ctx.measureText(label).width;
      var lx = troughX + 6;
      if (lx + labelW > PAD.l + cw) { ctx.textAlign = 'right'; lx = troughX - 6; }
      else { ctx.textAlign = 'left'; }
      ctx.fillText(label, lx, Math.max(PAD.t + 14, peakY - 4));
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

    // Y left labels (g=0→top, g=4→bottom, val maps max→min)
    ctx.fillStyle = '#5C5652';
    ctx.font = '11px -apple-system,sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (var g = 0; g <= 4; g++) {
      var val = maxY - (g/4) * (maxY - minY);
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
    _drawSegments(bFilled, '#2563EB', 2, [6, 3]);

    // Area fill
    var grad = ctx.createLinearGradient(0, PAD.t, 0, PAD.t + ch);
    grad.addColorStop(0, 'rgba(220,38,38,0.12)');
    grad.addColorStop(1, 'rgba(220,38,38,0.01)');
    _fillArea(pFilled, grad);

    // Portfolio line
    _drawSegments(pFilled, '#DC2626', 2.5);

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
        if (label) label.textContent = this.textContent + '指数参考';
        // 重新拉 all 数据更新抽屉
        self._allDataReady = false;
        self._allDataLoading = false;
        fetch('/api/pnl?range=all&index=' + self._state.index)
          .then(function(r) { return r.json(); })
          .then(function(d) {
            self._allDailyData = d;
            self._allDataReady = true;
            self._updateDrawer(d);
            self._updateSummary();
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
          ? '收起损益明细'
          : '查看损益明细';
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
      crossEl.className = 'pnl-cross';
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
          tip.className = 'pnl-tooltip';
          document.body.appendChild(tip);
        }
        var isDaily = cd.type === 'daily';
        var lbl = cd.labels[idx];
        if (!isDaily && lbl.length > 5) lbl = lbl.split(' ')[0];
        var pVal = cd.portfolio[idx];
        var bVal = cd.benchmark[idx];
        var hasP = pVal != null && !isNaN(pVal);
        var hasB = bVal != null && !isNaN(bVal);
        tip.innerHTML =
          '<b>' + (isDaily ? '' : '') + lbl + '</b>' +
          '<br>收益 <span style=\"color:' + (hasP ? (pVal >= 0 ? '#DC2626' : '#059669') : '#999') + '\">' +
          (hasP ? ((pVal >= 0 ? '+' : '') + pVal.toFixed(2) + '%') : '—') + '</span>' +
          '<br>指数 <span style=\"color:' + (hasB ? (bVal >= 0 ? '#DC2626' : '#059669') : '#999') + '\">' +
          (hasB ? ((bVal >= 0 ? '+' : '') + bVal.toFixed(2) + '%') : '—') + '</span>' +
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
