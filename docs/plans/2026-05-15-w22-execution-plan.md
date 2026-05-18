# W22 收益曲线组件 — 分步实施计划

**目标：** 修复 W22 组件 P0/P1/P2 共 12 项问题，每步独立验证、独立提交

**架构：** 后端先行（db.py → poll_live.py），前端随后（pnl-curve.js），每步改一个逻辑单元

**技术栈：** Python 3（sqlite3 + PyTDX）+ 纯 JavaScript（Canvas + GridStack）

**审计来源：** 洋米初审 + 稳米深度审计 + 黑米独立审计

---

## 执行顺序依赖图

```
Step 1 (db.py query_pnl)     ← 无依赖，先做
    ↓
Step 2 (poll_live.py rollup) ← 依赖 Step1 的 query_pnl 返回格式一致
    ↓
Step 3 (NaN 防御)             ← 无依赖
Step 4 (合并重复 fetch)        ← 无依赖，但影响 Step7
Step 5 (_periodCache key)     ← 无依赖
Step 6 (onResize)             ← 无依赖
    ↓
Step 7 (抽屉累计行+DD)         ← 依赖 Step4 的 _allDailyData 统一
Step 8 (KPI 标签改名)          ← 无依赖
Step 9 (死按钮+数字对齐)       ← 无依赖
Step 10 (week 边界修复)        ← 无依赖
```

---

### 任务 1: `query_pnl()` week/month 改走 daily_summary

**文件：** `scripts/db.py:125-213`

**问题：** week/month 走 intraday_snapshots，前端取末点当"本周收益"，实际是最后一天单日值。

**改动：** 统一路由逻辑——只有 today 走 intraday，其余全部走 daily_summary。

**步骤：**

1. 备份
```bash
cp scripts/db.py scripts/db.py.bak_$(date +%Y%m%d_%H%M)
```

2. 修改 `query_pnl()` 函数，将 week/month 从 intraday 分支移到 daily_summary 分支。当前代码约 L143-213，改为：

```python
def query_pnl(range='today', index='sh'):
    idx_map = {'sh': 'sh_pct', 'sz': 'sz_pct', 'cy': 'cy_pct'}
    idx_field = idx_map.get(index, 'sh_pct')
    today = datetime.now().strftime('%Y-%m-%d')

    # today: 走 intraday_snapshots（5分钟粒度）
    if range == 'today':
        rows = _exec(
            f"SELECT ts, pnl_pct, {idx_field} AS bm_pct, pos_pct, nav FROM intraday_snapshots WHERE date = ? ORDER BY ts",
            (today,))
        return {
            'type': 'intraday',
            'labels': [r['ts'][-8:-3] if 'T' in r['ts'] else r['ts'] for r in rows],
            'portfolio': [r['pnl_pct'] for r in rows],
            'benchmark': [r['bm_pct'] for r in rows],
            'position': [r['pos_pct'] for r in rows],
            'nav': [r['nav'] for r in rows],
        }

    # 计算 from_date
    now = datetime.now()
    day_of_week = now.weekday()
    if range == 'week':
        d = now.day - day_of_week
        from_date = now.replace(day=max(d, 1)).strftime('%Y-%m-%d')
    elif range == 'month':
        from_date = now.strftime('%Y-%m-01')
    elif range == 'quarter':
        m = ((now.month - 1) // 3) * 3 + 1
        from_date = f"{now.year}-{m:02d}-01"
    elif range == 'year':
        from_date = f"{now.year}-01-01"
    else:  # 'all' 或无匹配
        from_date = '2020-01-01'

    # week/month/quarter/year/all — 全部走 daily_summary
    rows = _exec(f"""
        SELECT date, pnl_pct, {idx_field} AS bm_pct, pos_pct, nav
        FROM daily_summary WHERE date >= ? ORDER BY date
    """, (from_date,))
    rows_list = [dict(r) for r in rows]
    return {
        'type': 'daily',
        'labels': [r['date'][-5:] for r in rows_list],
        'portfolio': [r['pnl_pct'] for r in rows_list],
        'benchmark': [r['bm_pct'] for r in rows_list],
        'position': [r['pos_pct'] for r in rows_list],
        'nav': [r['nav'] for r in rows_list],
        'dates': [r['date'] for r in rows_list],
    }
```

3. 验证：
```bash
cd /Users/YouMing/Documents/YM_Capital/live-dashboard && python3 -c "
from scripts.db import query_pnl
import json

# 测试各 range
for r in ['today', 'week', 'month', 'quarter', 'year', 'all']:
    d = query_pnl(r, 'sh')
    print(f'{r}: type={d[\"type\"]}, points={len(d[\"portfolio\"])}, labels={d[\"labels\"][:3]}...')

# 确认 week/month 不再是 'intraday'
d_week = query_pnl('week')
assert d_week['type'] == 'daily', 'WEEK SHOULD BE DAILY'
d_month = query_pnl('month')
assert d_month['type'] == 'daily', 'MONTH SHOULD BE DAILY'
d_today = query_pnl('today')
assert d_today['type'] == 'intraday', 'TODAY SHOULD BE INTRADAY'
print('ALL ASSERTIONS PASSED')
"
```

4. 提交：
```bash
git add scripts/db.py
git commit -m "fix(db): query_pnl week/month route to daily_summary instead of intraday_snapshots

Previously week/month fetched 5-min intraday snapshots whose pnl_pct is
single-day cumulative, not period cumulative. Frontend took the last point
as period return, showing wrong numbers (e.g. Wednesday's intraday value
displayed as 'this week's return').

Now week/month/quarter/year/all uniformly use daily_summary. Only 'today'
uses intraday_snapshots.

Root cause found by 稳米 audit."
```

---

### 任务 2: 盘中 NAV 维护 + `rollup_daily()` NAV 链 + sz/cy 补全 + 回撤修正

**文件：** `scripts/poll_live.py`

**问题（三源合并）：**
- `log_pnl_snapshot()` 写 `nav=1.0` 硬编码（洋米+稳米）
- `rollup_daily()` 用最后一个快照的浮动盈亏%当 TWR（黑米 P0-4）
- 回撤算法 `peak = portfolio[0]` 非标准（黑米 P2-5）
- `sz_pct=0, cy_pct=0` 硬编码（洋米+黑米 P0-5）

**改动分两处：**

**2a. 修改 `log_pnl_snapshot()`——盘中维护真正 NAV**

当前 L1258-1269，`nav=1.0` 改为从上一快照或前日收盘 NAV 连乘：

```python
def log_pnl_snapshot(pnl, live_index):
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    ts_iso = now.strftime('%Y-%m-%dT%H:%M:%S')

    # 盘中 NAV：从上一快照或前日收盘 NAV 连乘
    # 当日第一个快照：nav = prev_close_nav × (1 + pnl_pct/100)
    # 后续快照：nav = 上一快照的 nav（pnl_pct 已是当日累计值，不需要再乘）
    prev_snap = _exec(
        "SELECT nav FROM intraday_snapshots WHERE date = ? ORDER BY ts DESC LIMIT 1",
        (today,))
    if prev_snap:
        # 不是当日第一个快照：用上一快照的 NAV × (1 + delta)
        prev_nav = prev_snap[0]['nav']
        prev_pnl = _exec(
            "SELECT pnl_pct FROM intraday_snapshots WHERE date = ? ORDER BY ts DESC LIMIT 1",
            (today,))
        prev_pnl_pct = prev_pnl[0]['pnl_pct'] if prev_pnl else 0
        delta = pnl['pnl_pct'] - prev_pnl_pct
        nav = round(prev_nav * (1 + delta / 100), 6)
    else:
        # 当日第一个快照：从前日 daily_summary NAV 继承
        prev_day = _exec(
            "SELECT nav FROM daily_summary WHERE date < ? ORDER BY date DESC LIMIT 1",
            (today,))
        prev_close_nav = prev_day[0]['nav'] if prev_day else 1.0
        nav = round(prev_close_nav * (1 + pnl['pnl_pct'] / 100), 6)

    # ... safe_float 等不变 ...

    try:
        insert_snapshot({
            'ts': ts_iso,
            'date': today,
            'pnl_pct': pnl['pnl_pct'],
            'nav': nav,  # ← 改为真正的 TWR NAV
            ...
        })
```

**2b. 修改 `rollup_daily()`——标准回撤算法 + NAV/sz/cy**

```python
def rollup_daily():
    global _last_rollup_date
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    if _last_rollup_date == today:
        return
    try:
        from scripts.db import query_pnl as db_query_pnl
        data = db_query_pnl('today', 'sh')
        if not data or not data['portfolio']:
            return
        n = len(data['portfolio'])
        if n < 2: return

        # 日 TWR：用盘中的 nav 字段计算
        # _exec 需要从当前模块导入
        nav_rows = _exec(
            "SELECT nav FROM intraday_snapshots WHERE date = ? ORDER BY ts",
            (today,))
        if nav_rows and len(nav_rows) >= 2:
            nav_open = nav_rows[0]['nav']
            nav_close = nav_rows[-1]['nav']
            if nav_open > 0:
                daily_twr = round((nav_close - nav_open) / nav_open * 100, 4)
            else:
                daily_twr = 0.0
            new_nav = nav_close
        else:
            # fallback: 用 pnl_pct 末点 + 前日 NAV 连乘
            prev = _exec("SELECT nav FROM daily_summary WHERE date < ? ORDER BY date DESC LIMIT 1", (today,))
            prev_nav = prev[0]['nav'] if prev else 1.0
            daily_twr = round(data['portfolio'][-1], 4)
            new_nav = round(prev_nav * (1 + daily_twr / 100), 6)

        # 标准最大回撤算法（黑米修正）
        peak = -float('inf')
        peak_idx = 0
        for i, v in enumerate(data['portfolio']):
            if v > peak:
                peak = v
                peak_idx = i
        max_dd = 0.0
        dd_start = dd_end = None
        for i, v in enumerate(data['portfolio']):
            if i <= peak_idx:
                continue
            dd = v - peak
            if dd < max_dd:
                max_dd = dd
                dd_end = data['labels'][i] if data['labels'] else None
        dd_start = data['labels'][peak_idx] if data['labels'] and peak_idx < len(data['labels']) else None

        # 补全 sz/cy 指数日收益
        sz_pct = 0.0
        cy_pct = 0.0
        try:
            sz_data = db_query_pnl('today', 'sz')
            if sz_data and sz_data['benchmark']:
                sz_pct = round(sz_data['benchmark'][-1], 4)
        except Exception:
            pass
        try:
            cy_data = db_query_pnl('today', 'cy')
            if cy_data and cy_data['benchmark']:
                cy_pct = round(cy_data['benchmark'][-1], 4)
        except Exception:
            pass

        insert_daily_summary({
            'date': today,
            'nav': new_nav,
            'pnl_pct': daily_twr,  # ← 用日 TWR，不是快照末点
            'sh_pct': round(data['benchmark'][-1], 4) if data['benchmark'] else 0,
            'sz_pct': sz_pct,
            'cy_pct': cy_pct,
            'pos_pct': round(data['position'][-1], 2) if data['position'] else 0,
            'deposit': 0,
            'max_dd': round(max_dd, 4),
            'max_dd_start': dd_start,
            'max_dd_end': dd_end,
        })
        _last_rollup_date = today
        log(f"Daily rollup: nav={new_nav:.6f} twr={daily_twr:.2f}% sh={data['benchmark'][-1]:.2f}% sz={sz_pct:.2f}% cy={cy_pct:.2f}% dd={max_dd:.2f}%")
    except Exception as e:
        log(f"Rollup error: {e}")
```

3. 验证：
```bash
cd /Users/YouMing/Documents/YM_Capital/live-dashboard && python3 -c "
from scripts.db import init_db, query_pnl
init_db()

# 手动调用 rollup
from scripts.poll_live import rollup_daily
rollup_daily()

import sqlite3
conn = sqlite3.connect('data/pnl.db')
conn.row_factory = sqlite3.Row
row = conn.execute('SELECT * FROM daily_summary ORDER BY date DESC LIMIT 1').fetchone()
r = dict(row)
print(f'date={r[\"date\"]} nav={r[\"nav\"]:.6f} twr={r[\"pnl_pct\"]:.4f}%')
print(f'sh={r[\"sh_pct\"]:.4f}% sz={r[\"sz_pct\"]:.4f}% cy={r[\"cy_pct\"]:.4f}%')

# 验证 NAV 链
prev = conn.execute('SELECT nav FROM daily_summary WHERE date < ? ORDER BY date DESC LIMIT 1', (r['date'],)).fetchone()
if prev:
    expected = round(prev['nav'] * (1 + r['pnl_pct']/100), 6)
    match = abs(expected - r['nav']) < 0.001
    print(f'NAV chain: prev={prev[\"nav\"]:.6f} expected={expected:.6f} actual={r[\"nav\"]:.6f} {\"✓\" if match else \"✗\"}')

# 黑米追加：确认 SZ/CY benchmark 非全零
d_sz = query_pnl('week', 'sz')
assert any(v != 0 for v in d_sz['benchmark']), 'SZ benchmark still all zeros!'
print(f'SZ benchmark OK: {d_sz[\"benchmark\"][:5]}')
d_cy = query_pnl('week', 'cy')
assert any(v != 0 for v in d_cy['benchmark']), 'CY benchmark still all zeros!'
print(f'CY benchmark OK: {d_cy[\"benchmark\"][:5]}')

# 验证 intraday_snapshots 的 nav 不再是 1.0
snap = conn.execute('SELECT ts, nav FROM intraday_snapshots ORDER BY ts DESC LIMIT 5').fetchall()
for s in snap:
    print(f'intraday nav: {s[\"ts\"]} → {s[\"nav\"]:.6f}')
conn.close()
print('ALL CHECKS PASSED')
"
```
prev = conn.execute('SELECT nav FROM daily_summary WHERE date < ? ORDER BY date DESC LIMIT 1', (r['date'],)).fetchone()
if prev:
    expected = round(prev['nav'] * (1 + r['pnl_pct']/100), 6)
    match = abs(expected - r['nav']) < 0.001
    print(f'NAV chain: prev={prev[\"nav\"]:.6f} expected={expected:.6f} actual={r[\"nav\"]:.6f} {\"✓\" if match else \"✗\"} ')
conn.close()
"
```

4. 提交：
```bash
git add scripts/poll_live.py
git commit -m "fix(poll): maintain intraday NAV chain, fix rollup daily TWR/sz/cy/DD

Changes:
- log_pnl_snapshot(): compute real intraday NAV (chain from prev snapshot
  or previous day's close NAV), not hardcoded 1.0
- rollup_daily(): use nav[-1]/nav[0] to compute daily TWR instead of
  last snapshot's floating P&L%; fill sz_pct/cy_pct from intraday data;
  fix max drawdown algorithm (standard peak-then-trough, not peak-from-[0])

Fixes: P0-4 (黑米), P0-5 (黑米), P2-5 (黑米), NAV chain (洋米+稳米)"
```

---

### 任务 3: totalAsset=0 时 NaN 防御

**文件：** `widgets/pnl-curve.js:282-315`

**问题：** W16 未同步时 totalAsset=0，`pnlAmount/0 → Infinity`，KPI 全部 NaN。

**步骤：**

1. 备份
```bash
cp widgets/pnl-curve.js widgets/pnl-curve.js.bak_$(date +%Y%m%d_%H%M)
```

2. 在 `_updateKPI()` 开头（L282 附近 var s = this._state 之后），在 asset 赋值之前加入：

```javascript
_updateKPI(chartData) {
  var s = this._state;
  var asset = document.getElementById('pnl_asset');
  if (!asset) return;

  // P0-2: totalAsset=0 防御
  var ta = s.totalAsset;
  if (!ta || ta <= 0) {
    // 尝试从持仓市值反推
    var mvGuess = 0;
    (s.positions || []).forEach(function(p) {
      if ((p['状态']||'').indexOf('清') >= 0) return;
      var qty = parseFloat(String(p['数量']||'0').replace('股','')) || 0;
      var live = (s.liveQ || {})[p['代码']] || {};
      var cur = parseFloat(live['最新价']) || parseFloat(p['成本']) || 0;
      mvGuess += qty * cur;
    });
    // 如果持仓市值 > 0，用仓位%反推总资产
    if (mvGuess > 0) {
      var posPctGuess = 0;
      if (chartData && chartData.position && chartData.position.length) {
        posPctGuess = chartData.position[chartData.position.length - 1];
      }
      if (posPctGuess > 0) {
        ta = mvGuess / (posPctGuess / 100);
      } else {
        ta = mvGuess; // fallback: 假设满仓
      }
    }
    // 还是推不出来 → 显示"—"
    if (!ta || ta <= 0) {
      asset.textContent = '—';
      document.getElementById('pnl_asset_sub').textContent = '请先同步报数面板';
      return;
    }
    // 更新到 state（后续计算用）
    s.totalAsset = ta;
  }
  // ... 后面继续原有逻辑
```

3. 验证：在浏览器 DevTools 中模拟 `totalAsset=0`：
```javascript
// 在浏览器 console 中执行
DataStore.merged.pnl['总资产'] = 0;
// 触发 W22 重渲染，检查 KPI 显示"—"而非 NaN
```

4. 提交：
```bash
git add widgets/pnl-curve.js
git commit -m "fix(w22): guard against totalAsset=0 causing NaN in KPI cards

When W16 sync hasn't run, totalAsset defaults to 0, causing
pnlAmount/0 = Infinity and all KPI cards show NaN.

Added defense: try to derive totalAsset from position MV + position%,
or show '—' with instructions to sync the input panel.

Found by 稳米 audit."
```

---

### 任务 4: 合并重复的 `/api/pnl?range=all` 请求

**文件：** `widgets/pnl-curve.js:95-137`

**问题：** `render()` 中 `_posCache` 和 `_allDailyData` 发了两条相同请求，`_drawPosChart()` 还会再发。

**步骤：**

1. 在 `render()` 中，将第 96-137 行的三路 fetch 合并为一：

```javascript
// 替换原来的 L96-137：
// 统一预加载：一次 range=all 请求，喂给仓位缓存 + 抽屉 + summary
if (location.protocol !== 'file:' && !this._allDataLoading && !this._allDataReady) {
  this._allDataLoading = true;
  var self = this;
  fetch('/api/pnl?range=all&index=sh')
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
    })
    .catch(function() {
      self._allDataLoading = false;
    });
}
// 如果数据已就绪，直接用缓存更新
if (this._allDailyData) {
  this._updateDrawer(this._allDailyData);
  this._updateSummary();
}
```

2. 修改 `_drawPosChart()`（L445-555），删除其中的独立 fetch 逻辑（L451-457），只读缓存：

```javascript
_drawPosChart() {
  if (location.protocol === 'file:') return;
  var canvas = document.getElementById('pnl_pos_canvas_' + this.id);
  if (!canvas) return;
  // 去掉原来的独立 fetch（L451-457），改为只读缓存：
  if (!this._posCache) return;  // 缓存未就绪，等预加载完成后重试
  // ... 后面的绘制逻辑不变
```

3. 在 `_bindEvents()` 的仓位 toggle 逻辑中（L762-772），勾选时如果缓存还没就绪，提示而非静默失败：

```javascript
if (self._posCache) {
  self._drawPosChart();
} else {
  // 缓存还在加载中，稍后自动绘制
  var checkInterval = setInterval(function() {
    if (self._posCache) {
      clearInterval(checkInterval);
      self._drawPosChart();
    }
  }, 200);
  // 5 秒超时
  setTimeout(function() { clearInterval(checkInterval); }, 5000);
}
```

4. 验证：
```bash
# 打开看板 → DevTools Network 标签 → 强刷页面
# 确认 /api/pnl?range=all 只出现 1 次
# 确认 /api/pnl/summary 只出现 1 次
# 勾选"显示仓位" → 仓位子图正常出现
```

5. 提交：
```bash
git add widgets/pnl-curve.js
git commit -m "fix(w22): merge duplicate /api/pnl?range=all requests into single fetch

Previously render() launched 3 separate fetch calls to the same endpoint
(_posCache preload, _allDailyData preload, _drawPosChart retry).
Now uses a single Promise shared across all consumers.

Also removed stale fetch logic from _drawPosChart() — reads cache only."
```

---

### 任务 5: `_periodCache` 按 index 隔离 key

**文件：** `widgets/pnl-curve.js:247-248`

**问题**（黑米发现）：`_periodCache[period]` 不区分 index，切换到深证后再切回上证，缓存里是深证数据。

**步骤：**

1. 修改 `_fetchChartData()` 中的缓存 key（L247-248）：

```javascript
// 改前: self._periodCache[period] = data;
// 改后:
var cacheKey = period + '_' + idx;
if (!self._periodCache) self._periodCache = {};
self._periodCache[cacheKey] = data;
```

2. 修改 `_updateDrawer()` 中读取 `_periodCache` 的地方（L384）：

```javascript
// 改前: var d = cache[p];
// 改后: var cacheKey = p + '_' + self._state.index;
//       var d = cache[cacheKey];
```

完整改动在 L386-389：
```javascript
periods.forEach(function(p, i) {
  var cacheKey = p + '_' + self._state.index;
  var d = cache[cacheKey];
  // ... 后续不变
```

3. 验证：在浏览器中操作——本周视图 → 切深证 → 切创业板 → 切回上证。每次 benchmark 线颜色/数值正确对应。

4. 提交：
```bash
git add widgets/pnl-curve.js
git commit -m "fix(w22): make _periodCache key period+index aware

Previously cache key was only the period ('week'), so switching
index from SH→SZ would overwrite SH data with SZ data in cache.
Switching back to SH would show stale SZ benchmark values.

Now key is 'period_index' (e.g. 'week_sz'), isolating cache per index.

Found by 黑米 audit."
```

---

### 任务 6: onResize 修复

**文件：** `widgets/pnl-curve.js:884-886`

**问题**（稳米+黑米发现）：`onResize()` 无参调用 `_drawChart()`，chartData=undefined，直接 return。

**步骤：**

1. 修改 `onResize`：

```javascript
onResize(w, h) {
  if (this._lastChartData) this._drawChart(this._lastChartData);
  if (this._posCache) this._drawPosChart();
}
```

2. 验证：拖动 GridStack 边框改变 W22 组件大小 → 主图表和仓位子图均正确重绘，无拉伸变形。

3. 提交：
```bash
git add widgets/pnl-curve.js
git commit -m "fix(w22): onResize now redraws with cached chart data

Previously onResize called _drawChart() without arguments, causing
early return (chartData undefined). Charts appeared stretched after
resize.

Now passes _lastChartData (saved at end of _drawChart) and redraws
position sub-chart too.

Found by 稳米+黑米 audit."
```

---

### 任务 7: 抽屉累计行 & 回撤修复

**文件：** `widgets/pnl-curve.js:375-423`

**问题：** 累计行取 5 个时段末点连乘（quarter/year 的末点是单日值），累计 DD 取各时段 min。

**步骤：**

1. 重写 `_updateDrawer()` 中的累计行计算（L386-422）：

```javascript
// 各时段行（不变）
periods.forEach(function(p, i) {
  var cacheKey = p + '_' + self._state.index;
  var d = cache[cacheKey];
  if (!d || !d.portfolio || !d.portfolio.length) {
    html += '<tr><td class="pnl-td-period">' + labels[i] + '</td><td class="pnl-td-num" colspan="4">加载中...</td></tr>';
    return;
  }
  // 计算该时段的 TWR 累计（从该时段第一条开始连乘）
  var tP = 1.0, tB = 1.0, tPk = -Infinity, tDD = 0, tRP = 0;
  for (var j = 0; j < d.portfolio.length; j++) {
    tP *= (1 + d.portfolio[j] / 100);
    tB *= (1 + d.benchmark[j] / 100);
    tRP = (tP - 1) * 100;
    if (tRP > tPk) tPk = tRP;
    if (tRP - tPk < tDD) tDD = tRP - tPk;
  }
  var periodPnl = (tP - 1) * 100;
  var periodBm = (tB - 1) * 100;
  html += '<tr>' +
    '<td class="pnl-td-period">' + labels[i] + '</td>' +
    '<td class="pnl-td-num" style="color:' + (periodPnl >= 0 ? 'var(--up)' : 'var(--down)') + '">' + pctStr(periodPnl) + '</td>' +
    '<td class="pnl-td-num" style="color:' + (periodBm >= 0 ? 'var(--up)' : 'var(--down)') + '">' + pctStr(periodBm) + '</td>' +
    '<td class="pnl-td-num" style="color:' + ((periodPnl - periodBm) >= 0 ? 'var(--up)' : 'var(--down)') + ';font-size:11px">' + pctStr(periodPnl - periodBm) + '</td>' +
    '<td class="pnl-td-num" style="color:var(--down)">' + pctStr(tDD) + '</td>' +
    '</tr>';
});

// 累计行：从 _allDailyData 全量日频数据计算
if (self._allDailyData && self._allDailyData.portfolio && self._allDailyData.portfolio.length) {
  var allP = self._allDailyData.portfolio;
  var allB = self._allDailyData.benchmark;
  var cumP = 1.0, cumB = 1.0, pk = -Infinity, cumDD = 0, rp = 0;
  for (var k = 0; k < allP.length; k++) {
    cumP *= (1 + allP[k] / 100);
    cumB *= (1 + allB[k] / 100);
    rp = (cumP - 1) * 100;
    if (rp > pk) pk = rp;
    if (rp - pk < cumDD) cumDD = rp - pk;
  }
  html += '<tr class="pnl-cum-row">' +
    '<td class="pnl-td-period pnl-td-bold">累计</td>' +
    '<td class="pnl-td-num" style="color:' + ((cumP - 1) * 100 >= 0 ? 'var(--up)' : 'var(--down)') + '">' + pctStr((cumP - 1) * 100) + '</td>' +
    '<td class="pnl-td-num" style="color:' + ((cumB - 1) * 100 >= 0 ? 'var(--up)' : 'var(--down)') + '">' + pctStr((cumB - 1) * 100) + '</td>' +
    '<td class="pnl-td-num" style="color:' + (((cumP - 1) * 100 - (cumB - 1) * 100) >= 0 ? 'var(--up)' : 'var(--down)') + ';font-size:11px">' + pctStr((cumP - 1) * 100 - (cumB - 1) * 100) + '</td>' +
    '<td class="pnl-td-num" style="color:var(--down)">' + pctStr(cumDD) + '</td>' +
    '</tr>';
}
```

2. 验证：
- 打开抽屉 → 各时段行的收益 = 该时段内各日收益率 TWR 连乘（非末点单日值）
- 累计行收益 ≈ `_updateSummary()` 中的 `(lastNav-1)*100`
- 累计 DD 从全时段序列计算（非 min of mins）

3. 提交：
```bash
git add widgets/pnl-curve.js
git commit -m "fix(w22): drawer cumulative row uses full-period TWR, not last-point hack

Previously:
- Each period row showed last data point (single-day return for quarter/year)
- Cumulative row multiplied 5 last-points (meaningless)
- Cumulative DD was min(dd_of_5_periods), not true max drawdown

Now:
- Each period row computes TWR chain within that period
- Cumulative row computes TWR from full allDailyData history
- Cumulative DD uses standard peak-to-trough algorithm on full series"
```

---

### 任务 8: KPI 标签改名

**文件：** `widgets/pnl-curve.js:163-168, 328-358`

**问题：** "收益"标签误导——实际是浮动盈亏/总资产。

**步骤：**

1. 修改 `_buildLayout()` L165：
```javascript
// 改前: <div class="pnl-kpi-lbl">持仓盈亏</div>
// 改后:
'<div class="pnl-kpi-lbl">浮动盈亏</div>' +
```

2. 修改 `_updateKPI()` L328：
```javascript
// 改前: perStr + '收益'
// 改后:
document.getElementById('pnl_period_label').textContent = perStr + '净值变化';
```

3. 修改 `_updateKPI()` L335：
```javascript
// 改前: '持仓浮动'
// 改后:
document.getElementById('pnl_period_sub').textContent = '浮动盈亏/总资产';
```

4. 验证：浏览器刷新 → KPI 卡片显示"浮动盈亏""今日净值变化""浮动盈亏/总资产"

5. 提交：
```bash
git add widgets/pnl-curve.js
git commit -m "fix(w22): rename KPI labels from '收益' to accurate descriptions

'收益' implied TWR period return, but the calculation is
(market_value - cost) / total_asset — floating P&L ratio.

Renamed: '持仓盈亏'→'浮动盈亏', '今日收益'→'今日净值变化',
subtitle '持仓浮动'→'浮动盈亏/总资产'.

Per user decision: label change only, calculation logic unchanged."
```

---

### 任务 9: 死按钮 + 数字对齐

**文件：** `widgets/pnl-curve.js:184, 65`

**步骤：**

1. 删除"自定义"按钮 L184：
```javascript
// 删除这行:
'<button class="pnl-period pnl-period-custom">自定义</button>' +
```

2. 修改 CSS L65：
```css
/* 改前: text-align:center */
/* 改后: */
'.pnl-sum-cell{background:var(--bg-card);padding:10px 14px;text-align:right}' +
```

3. 验证：浏览器刷新 → 无"自定义"按钮，底部汇总数字右对齐

4. 提交：
```bash
git add widgets/pnl-curve.js
git commit -m "fix(w22): remove dead '自定义' button, right-align summary numbers"
```

---

### 任务 10: week 边界修复（前端）

**文件：** `widgets/pnl-curve.js:217-227`

**问题**（黑米发现）：周一 `new Date().getDay()=0 → day=7 → setDate(now.getDate()-6)`，跨月时会把上月最后几天算进本周。

**步骤：**

1. 修改 `_filterByPeriod()` 的 week 分支：
```javascript
// 改前: var mon = new Date(now); mon.setDate(now.getDate() - day + 1);
// 改后: 用 setDate 正确处理跨月
case 'week':
  var dow = now.getDay();
  var diffToMon = dow === 0 ? -6 : 1 - dow;  // Sunday→-6, Monday→0, Tuesday→-1 ...
  var mon = new Date(now);
  mon.setDate(now.getDate() + diffToMon);
  mon.setHours(0, 0, 0, 0);
  return daily.filter(function(d) { return new Date(d.date) >= mon; });
```

2. 验证：
```javascript
// 浏览器 console 中模拟周一场景
var d = new Date('2026-05-11'); // 一个周一
// 预期 mon = 2026-05-11（当天），不是 2026-04-27
```

3. 提交：
```bash
git add widgets/pnl-curve.js
git commit -m "fix(w22): fix week boundary calculation for Monday cross-month

On Monday (getDay()=0), the old formula day=(0||7)=7, then
setDate(d-7+1)=setDate(d-6) which crosses into previous month.

New formula: diffToMon = Sunday?-6:1-dow, then setDate(date+diffToMon),
which correctly handles all days including Monday.

Found by 黑米 audit."
```

---

## 完成验证

全部 10 步完成后，做端到端验证：

```bash
# 1. 确认所有文件无语法错误
cd /Users/YouMing/Documents/YM_Capital/live-dashboard
python3 -c "from scripts.db import query_pnl; print('db.py OK')"
python3 -c "from scripts.poll_live import rollup_daily; print('poll_live.py OK')"
node -c widgets/pnl-curve.js && echo "pnl-curve.js OK"

# 2. 启动看板，检查 W22 渲染正常
python3 scripts/bridge.py 8088 &
sleep 2
curl -s http://localhost:8088/api/pnl?range=week | python3 -m json.tool | head -20
curl -s http://localhost:8088/api/pnl/summary | python3 -m json.tool
kill %1

# 3. 确认 git log 10 个 commit
git log --oneline -10
```
