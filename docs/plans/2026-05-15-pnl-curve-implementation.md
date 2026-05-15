# 账户收益曲线 W22 实施计划

**目标：** 在弈沐资本数据看板中实现实时 P&L 曲线组件（W22），含 TWR 累计收益、大盘对比、周期选择和损益明细抽屉。

**架构：** 扩展 poll_live.py 补充 P&L 采集 → pnl_history.json → store.js 第四层 → Canvas 折线图组件

**技术栈：** 纯 HTML/CSS/JS + Canvas API + GridStack v12 + PyTDX

---

## 任务清单

### 任务 1: 扩展 bridge.py — 支持 pnl 数据同步

**文件：**
- 修改: `scripts/bridge.py:193-228`

**改动：** 在 `POST /api/sync` 中添加 `pnl` 字段处理逻辑，将 `总资产` 和 `累计入金` 写入 `dashboard_data.json` 的 `pnl` 域。

当前 `/api/sync` 处理 `positions` 和 `今日操作`。增加分支处理 `payload.pnl`：

```python
# 在 do_POST /api/sync 中现有代码后追加
if 'pnl' in payload:
    if 'pnl' not in data:
        data['pnl'] = {}
    for key in ['总资产', '累计入金']:
        if key in payload['pnl'] and payload['pnl'][key] is not None:
            data['pnl'][key] = payload['pnl'][key]
```

**验证：** 启动 bridge，curl POST 测试：

```bash
curl -X POST http://localhost:8088/api/sync \
  -H 'Content-Type: application/json' \
  -d '{"pnl":{"总资产":1012000,"累计入金":2000000}}'
# → {"ok": true}
# 检查 data/dashboard_data.json 应有 pnl 域
```

---

### 任务 2: 扩展 W16 input-panel.js — 新增累计入金 + 桥接同步

**文件：**
- 修改: `widgets/input-panel.js:452-524`

**改动：**
1. 在字段列表 `fields` 中新增 `累计入金`（type: number）
2. W15 的 `_bridgeSync` 逻辑独立出来或共享——W16 也需要在刷新时推总资产和入金到 bridge

新增桥接函数（可放在全局作用域或与 W15 的共享）：

```js
// 在文件末尾或现有 _bridgeSync 旁
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
```

在 W16 的「刷新全部数据」按钮处理中，读取 `总资产` 和 `累计入金` 输入值，调用 `_bridgeSyncPnl()`。

**验证：** 在 bridge 模式下打开看板，报数面板填总资产和入金，点刷新 → 检查 bridge 终端日志有 "Synced" 输出 → curl 读 dashboard_data.json 看 pnl 域。

---

### 任务 3: 扩展 poll_live.py — P&L 计算 + 快照写入

**文件：**
- 修改: `scripts/poll_live.py` (1437行)

**改动：** 在 `--watch` 模式循环体中：

1. **新增函数 `calc_pnl(data, quotes, total_asset)`**:
   - 读 data.positions → 遍历每个持仓
   - 从 quotes 取实时价
   - 算 持仓市值 = Σ(数量×最新价), 持仓成本 = Σ(数量×成本价)
   - 返回 { mv, cost, pnl_amount, pnl_pct, pos_pct }

2. **新增函数 `log_pnl_snapshot(pnl_result, live_index, nav_history)`**:
   - 构建快照: `{t, nav, pnl_pct, sh_pct, sz_pct, cy_pct, pos_pct, mv}`
   - 读/写 `data/pnl_history.json`
   - 每日首次调用时创建新的 intraday 数组
   - 60s 节流（非每次5s都写）

3. **在 watch 主循环中**：
   - 获取 quotes 后调用 calc_pnl
   - 如果距上次快照 >= 60s，调用 log_pnl_snapshot

4. **NAV 逻辑**：
   - 读取 pnl_history.json > meta.last_twr_nav
   - 当日首次计算：从 last_twr_nav 接过
   - 日内：NAV = last_twr_nav × (1 + 当日累计P&L%)

**关键代码框架：**

```python
WATCH_INTERVAL = 5  # seconds between quote fetches
PNL_LOG_INTERVAL = 60  # seconds between P&L snapshots
_last_pnl_log = 0

def calc_pnl(data, quotes):
    """从持仓+报价计算实时浮动盈亏"""
    total_asset = (data.get('pnl', {}) or {}).get('总资产', 0)
    positions = data.get('positions', [])
    mv, cost = 0, 0
    for p in positions:
        status = str(p.get('状态', ''))
        if '清' in status:
            continue
        code = str(p.get('代码', ''))
        qty = float(str(p.get('数量', '0')).replace('股', '')) if p.get('数量') else 0
        cost_price = float(p.get('成本', 0))
        live = quotes.get(code, {})
        cur_price = float(live.get('最新价', 0)) or cost_price
        mv += qty * cur_price
        cost += qty * cost_price
    pnl_amount = mv - cost
    pnl_pct = (pnl_amount / total_asset * 100) if total_asset > 0 else 0
    pos_pct = (mv / total_asset * 100) if total_asset > 0 else 0
    return {'mv': round(mv, 2), 'cost': round(cost, 2),
            'pnl_amount': round(pnl_amount, 2), 'pnl_pct': round(pnl_pct, 4),
            'pos_pct': round(pos_pct, 2), 'total_asset': total_asset}


def log_pnl_snapshot(pnl, live_index, history_path):
    """追加一条日内快照到 pnl_history.json"""
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    ts = now.strftime('%H:%M')

    # 读取现有历史
    history = {'meta': {'version': '1.0', 'last_twr_nav': 1.0,
                        'total_deposit': 0, 'updated': now.isoformat()},
               'intraday_histories': {}, 'daily': []}
    if history_path.exists():
        try:
            with open(history_path) as f:
                history = json.load(f)
        except Exception:
            pass

    # NAV 计算
    last_nav = history['meta'].get('last_twr_nav', 1.0)
    intraday_today = history.get('intraday_histories', {}).get(today, [])
    if not intraday_today:
        # 本日首条：从上日NAV接过
        nav = last_nav
    else:
        # 日内累计P&L% = 当日快照P&L
        daily_pnl_pct = pnl['pnl_pct']
        # 简单模式: NAV = last_nav × (1 + 日累计收益率)
        # 日内第一条？基准哪来？这里简化：日内每笔记录累计值
        nav = last_nav  # 用 last_nav 为基线，实际 P&L% 已是当日累计

    snapshot = {
        't': ts,
        'pnl_pct': pnl['pnl_pct'],
        'sh_pct': round(float(live_index.get('上证指数涨幅', '0').replace('%', '') or 0), 4),
        'sz_pct': round(float(live_index.get('深证指数涨幅', '0').replace('%', '') or 0), 4),
        'cy_pct': round(float(live_index.get('创业指数涨幅', '0').replace('%', '') or 0), 4),
        'pos_pct': pnl['pos_pct'],
        'mv': pnl['mv'],
    }

    if today not in history['intraday_histories']:
        history['intraday_histories'][today] = []
    history['intraday_histories'][today].append(snapshot)
    history['meta']['updated'] = now.isoformat()

    with open(history_path, 'w') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    log(f"P&L snapshot logged: {ts} pnl={pnl['pnl_pct']:.2f}%")
```

在主循环中插入：

```python
# 在 watch 循环获取 quotes 之后
now = time.time()
if now - _last_pnl_log >= PNL_LOG_INTERVAL:
    pnl = calc_pnl(data, result)  # result = live quotes
    log_pnl_snapshot(pnl, live_index, PNL_HISTORY_PATH)
    _last_pnl_log = now
```

**验证：** 启动 poll_live.py --watch，等 60s+ → 检查 `data/pnl_history.json` 出现 intraday 快照。

---

### 任务 4: 扩展 store.js — 第四层 pnlData

**文件：**
- 修改: `store.js`

**改动：**
1. 新增 `pnlData = null` 变量（类似 `liveData`）
2. 新增 `adapter.fetchPNL()`：
```js
fetchPNL: function() {
  return fetch('data/pnl_history.json?t=' + Date.now())
    .then(function(r) { return r.ok ? r.json() : null; })
    .catch(function() { return null; });
}
```
3. 在 `fetchAll()` 链中添加 `adapter.fetchPNL()` 调用，结果存到 `pnlData`
4. 暴露 `getPNL()` 方法
5. 在 `refresh()` 的 tick 层级也加入 pnl 刷新（每 60s 一次）
6. merged 对象不合并 pnlData（太大），通过 `getPNL()` 单独获取

---

### 任务 5: 注册 W22 + 添加到 index.html

**文件：**
- 修改: `widget-registry.js`
- 修改: `index.html`

**widget-registry.js 改动：** 在 widgets 数组末尾追加：
```js
{ id:'W22', type:'pnl-curve', title:'账户收益曲线', category:'data',
  tier:'tick', defaultSize:{w:12,h:10},
  dataPaths:['live_quotes','positions'], priority:'P1' }
```

**index.html 改动：** 在 `</body>` 前、现有 widget 脚本后增加：
```html
<script src="widgets/pnl-curve.js"></script>
```

---

### 任务 6: 实现 pnl-curve.js — W22 组件

**文件：**
- 新建: `widgets/pnl-curve.js`

**结构：**

```
class PnLCurveWidget extends YiMuWidget {
  └─ constructor/config
  └─ render(data) → 主渲染入口
     ├─ _renderKPI(data) → 5卡KPI
     ├─ _renderControls(data) → 时间选择+指数切换
     ├─ _drawChart(data) → Canvas 折线图
     │  ├─ 选择数据源（今日→intraday, 其他→daily）
     │  ├─ 计算坐标映射
     │  ├─ 绘制网格/零线/坐标轴
     │  ├─ 绘制仓位线（灰虚线）
     │  ├─ 绘制基准指数线（蓝虚线）
     │  ├─ 绘制账户收益线（红实线）+ 面积填充
     │  └─ 绘制回撤高亮（橙色峰谷标注）
     ├─ _renderLegend()
     ├─ _renderDrawer(data) → 损益明细抽屉
     └─ _bindEvents() → 时间选择/指数切换/抽屉展开
}
```

**Canvas 绘图要点：**
- 响应式：监听 resize，重绘
- DPR 适配：`canvas.width = W * DPR; ctx.scale(DPR, DPR)`
- 鼠标 hover：计算鼠标在 chart 坐标系中的位置，显示 tooltip
- 动画：首次渲染渐进线（可选）

**关键尺寸（匹配设计样稿）：**
- KPI: 5 card row, padding 14px 18px, font 26px mono
- Controls: 8px 14px padding
- Chart: canvas 280px height
- Drawer: 12px table with summary strip

**数据读取：**
```js
// 获取实时报价（用于实时持仓市值计算）
var liveQ = (data && data.live_quotes) || {};
// 获取持仓
var positions = (data && data.positions) || [];
// 获取总资产基线
var totalAsset = (data && data.pnl && data.pnl['总资产']) || 0;
// 获取累计入金
var totalDeposit = (data && data.pnl && data.pnl['累计入金']) || 0;
// 获取 P&L 历史
var pnlHistory = DataStore.getPNL ? DataStore.getPNL() : null;
```

**Canvas 图表绘制顺序（从底到顶）：**
1. 白色背景填充
2. 回撤高亮区域（橙色底色+粗线+峰谷点）
3. 水平网格线（4条）+ 零轴线
4. Y轴标签（左：收益率%，右：仓位%）
5. X轴时间标签（每30min）
6. 仓位线（灰虚线）
7. 基准指数线（蓝虚线）
8. 账户收益线（红实线）+ 面积渐变填充
9. 曲线末端标签（百分比数值）
10. hover tooltip（mousemove 更新）

---

### 任务 7: 创建种子 pnl_history.json

**文件：**
- 新建: `data/pnl_history.json`

**内容：** 基本结构（空数据），待 poll_live.py 填充：

```json
{
  "meta": {
    "version": "1.0",
    "currency": "CNY",
    "total_deposit": 0,
    "last_twr_nav": 1.0,
    "updated": ""
  },
  "intraday_histories": {},
  "daily": []
}
```

---

### 任务 8: end-of-day 结算脚本（可选，v1.1）

收盘后运行，取当日最后一条 intraday 转为 daily 记录。可以独立脚本或 poll_live.py 的 `--eod` 模式。

```python
# python3 scripts/poll_live.py --eod
# 读取 pnl_history.json → 取今日最后一条 intraday → 追加到 daily
# 如果有 deposit 变化 → TWR 分段计算
# 更新 meta.last_twr_nav
```

v1.0 暂不实现，先用手动方法。

---

## 提交顺序

1. bridge.py 扩展 → 验证
2. W16 input-panel 扩展 → 验证
3. 种子 pnl_history.json + store.js 第四层 → 验证
4. poll_live.py P&L 扩展 → 验证（需 bridge 运行 + 看板打开）
5. widget-registry + index.html 注册 → 验证
6. pnl-curve.js 组件 → 验证（需前面全部完成）
7. 端到端测试 → 验证全部链路通
