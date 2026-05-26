# 2026-05-26 数据看板故障报告

> 日期: 2026-05-26 盘前~盘中
> 影响范围: live-dashboard（弈沐资本数据看板）
> 严重程度: 高（PnL 曲线丢失、总资产错误、收益计算错误、部分组件不显示）

---

## 故障一：PnL 数据库损坏

### 现象
`data/pnl.db` SQLite 数据库报 "database disk image is malformed"，btree 多页损坏。W22 收益曲线数据源中断。

### 根因
- `pnl.db` 使用 WAL 模式（`PRAGMA journal_mode=WAL`）
- bridge 的 APScheduler 多个 job 通过 `db.py` 线程独立连接并发写入 `intraday_snapshots`
- 非正常退出/进程杀停导致 WAL checkpoint 未完成，WAL 状态不一致→btree 损坏

### 修复
1. 从损坏库的 WAL 文件抢救出完整 `daily_summary`（18 条，含 5/19~5/25 数据）
2. 合并 pnl_history.json（22 条，至 5/15）和 WAL 数据，`pnl.db` 重建为 27 条日线数据
3. 备份损坏文件为 `pnl.db.corrupted_bak`

### 复现条件
bridge 在运行中被 kill + WAL 未 checkpoint → 下次启动时 corruption

---

## 故障二：Bridge 重启失败

### 现象
kill bridge 后无法重启：`ModuleNotFoundError: No module named 'apscheduler'`

### 根因
bridge 依赖的 Python 包未在系统环境安装：
- `apscheduler`（APScheduler 调度器）
- `filelock`（atomic_write_json 依赖）
- `ym-stock-data`（YM-data-pipeline，数据采集层）

### 修复
```bash
pip3 install --break-system-packages apscheduler filelock
cd YM-data-pipeline && pip3 install --break-system-packages -e .
```

同时修复 `YM-data-pipeline/pyproject.toml`，增加 `[tool.setuptools.packages.find]` 排除 `outputs/` 目录（否则 editable install 失败）。

---

## 故障三：持仓股无实时报价

### 现象
`/api/live/quotes` 不含中芯国际(688981)和沪电股份(002463)，导致：
- 持仓市值 mv=0 → 总资产 = 仅可用资金（~95k）
- 今日浮动盈亏计算不到中芯/沪电

### 根因
`bridge.py:970` 监听代码列表只加了"已清仓"标的，**"持有"标的未加入**：

```python
# 错误：仅已清仓
[p.get('代码') for p in dd.get('positions', []) if p.get('代码') and '清' in str(p.get('状态',''))]
```

持仓票（中芯、沪电）的代码不在 PyTDX 采集列表里，bridge 不拉取它们的实时行情。

### 修复
改为全量监听所有持仓标的：
```python
# 正确：全部持仓（含持有和已清仓）
[p.get('代码') for p in dd.get('positions', []) if p.get('代码')]
```

---

## 故障四：总资产显示错误

### 现象
PnL Summary 显示 `total_asset=153,561`（或重启后 132,475），实际应为 ~210,477。

### 根因
两层独立问题：

**A. pnl_history.json 元数据陈旧**
`pnl_history.json` 的 `meta.last_total_asset` 停在了 2026-05-19 的 153,561。bridge 重启后读此值做 `day_start_asset` 基准。

**B. dashboard_data.json 的 pnl 段全为 0**
gen 脚本保留 pnl 段但从未写有效值，导致 baseline API 返回 `{总资产: 0, 可用资金: 0}`。
→ W03 三层仓位计拿到 totalCapital=0，全部归零。

### 修复
- A: 从 `daily_summary` 最新行（NAV=1.0524, deposit=200000）反算 `total_asset=210,477`，写入 pnl_history.json
- B: 将 `dashboard_data.json.pnl` 更新为 `{总资产: 210477, 可用资金: 95725, 累计入金: 200000, 持仓市值: 114752}`
- 同步到 bridge CACHE（通过 `/api/sync` POST）

---

## 故障五：W22 收益曲线组件不渲染

### 现象
点击"📈 收益曲线"按钮添加 W22 后，图表区域空白（KPI、画布均不显示），Console 无报错。

### 根因
"今日TWR" KPI 取 `chartData.portfolio[portfolio.length-1]` 作为今日收益。
- 日内 API（`/api/pnl?range=today`）返回 48 个时段的完整时间轴
- 当前时间之后的时段 portfolio 值为 `null`
- `portfolio[47]`（14:55 时段）= `null`
- `null.toFixed(2)` 抛异常 → 整个 `_updateKPI` 链中断 → 所有 KPI 不更新

异常被 `_fetchChartData` 的 Promise 链吞掉（catch 只设 `callback(null)`），不冒泡到 Console。

### 修复
改用最后一个非空值代替末尾索引：
```javascript
var _n = chartData.portfolio.length, _lastI = _n - 1;
while (_lastI >= 0 && chartData.portfolio[_lastI] == null) _lastI--;
var lastPnl = _lastI >= 0 ? chartData.portfolio[_lastI] : null;
```

---

## 故障六：W22 "今日浮动盈亏" 计算错误

### 现象
中芯国际今日跌 -4.56%，但"今日浮动盈亏"显示 **+7,010**（盈利）。用户反馈与感受严重不符。

### 根因
算法用 `现价 - 成本价` 算"今日"浮动盈亏：

```javascript
// 错误：这是累计浮盈，不是今日盈亏
var cp = parseFloat(p['成本']) || 0;
var cur = parseFloat(live['最新价']) || cp;
mv += qty * cur;
cost += qty * cp;
pnlAmount = mv - cost;  // → +7,010（中芯成本135→现价149，还是正数）
```

实际今日盈亏应为 **现价 - 昨收**（从行情涨幅反推）。

### 修复
改为从实时涨幅反推昨收，计算今日变动：
```javascript
var chgPct = parseFloat(String(live['涨幅']||'0').replace('%','')) || 0;
var yestClose = chgPct !== 0 ? cur / (1 + chgPct / 100) : cur;
todayChg += qty * (cur - yestClose);  // → -997（今日实际盈亏：中芯-3,700 + 沪电+2,703）
```

同时将 sub 文案从"浮动"改为"今日"避免歧义。

---

## 修复后状态（10:07）

| 指标 | 值 |
|------|------|
| PnL 日线 | 27 条（完整） |
| bridge PID | 87012 |
| 总资产 | 209,055 |
| 累计 TWR | +8.70% |
| 今日 PnL | -997（-0.47%） |
| 中芯国际 | 148.88 (-4.56%) |
| 沪电股份 | 130.88 (+6.81%) |
| 日内快照 | 7 个（持续收集中） |

## 需要后续关注的

1. **WAL 损坏预防**：考虑改为 DELETE 模式或加 graceful shutdown 信号处理
2. **持仓代码列表**：逻辑已改全量，但 gen 脚本写入 pools 时若持仓不在池里仍需 bridge 重启才能更新监听列表
3. **pnl_history.json 自动更新**：bridge 收盘时（15:00+）会自动写入，但若在收盘前重启会丢当日数据 → 可加一个定时落盘（如每小时）
4. **gen 脚本运行**：当前 gen 日期停在 5/19，需跑 `python3 scripts/gen_dashboard_data.py` 更新基线

---

## SSOT 实施闭环记录（2026-05-26 下午）

> 本节记录账户资产 SSOT 系统的落地验证全过程，对应 `docs/superpowers/plans/2026-05-26-account-asset-ssot.md` 实施计划。

### 核验结果

| 模块 | 文件 | 状态 |
|------|------|------|
| 核心逻辑 | `scripts/account_ssot.py` | ✅ `reduce_account_state` / `ensure_today_anchor` / `generate_closing_anchor` / `load_current_account_state` 全部落地 |
| 数据库锚点 | `scripts/db.py` | ✅ `account_baselines` / `trade_records` / `fund_events` / `intraday_snapshots` / `daily_summary` 五表齐全，含 `trade_id_cutoff` / `_meta_json` 扩展字段 |
| bridge 接入 | `scripts/bridge.py` | ✅ `/api/account/state` / `/api/account/correct` / `/api/sync` 拒绝资产字段 / `log_pnl_snapshot` 消费 SSOT / 15:05 日结 job |
| 快照改造 | `scripts/collectors/quotes.py` | ✅ `_snapshot_from_account` 走 SSOT / 5% 偏差告警 / `valuation_complete` 完整性标记 |
| 前端接入 | `widgets/pnl-curve.js` | ✅ 接入 `/api/account/state` |
| 测试用例 | `tests/test_account_ssot.py` | ✅ 17/17 全绿 |

### Bug 修复

**Bug 1：`test_full_day_replay_lifecycle` setUp anchor 日期错误**
- 症状：阶段1 找不到 previous_close 锚点，fallback 到 recovery，`day_start_asset` 丢失
- 根因：`FullLifecycleReplayTests.setUp` 创建了 `"date": "2026-05-25"` 锚点，但测试用例用 `now="2026-05-26"` 调用，`ensure_today_anchor` 查的是 2026-05-26 的锚点
- 修复：setUp 改为创建 `"date": "2026-05-26"` 的 previous_close 锚点，注释说明这是"日结流程次日预生成"状态的模拟

**Bug 2：`generate_closing_anchor` 漏查 fund_events**
- 症状：`ClosingAnchorTests.test_full_day_replay_lifecycle` 收盘锚点 cash 比期望少 10,000（入金金额）
- 根因：`generate_closing_anchor` 只 query 了 `trades`，漏了 `fund_events`，导致入金事件没被重放进收盘 cash
- 修复：添加 `query_fund_events` 调用，传入 `reduce_account_state`，fund_events 按 `event_date` + `id` 排序

### API 验证（实测）

```
/api/account/state
  cash=125,279 | mv=84,411 | total_asset=209,690 | pnl=-0.37% | anchor=recovery | positions=2

/api/pnl/summary
  total_asset=209,690 | pnl_amount=-787 | pnl_pct=-0.37% | day_start_asset=210,477
  last_nav=1.0524 | today_snapshots=98 | daily_count=27 | _updated=2026-05-26T13:45:15+08:00

一致性验证：209,690 - 210,477 = -787 ✅
```

### 后续任务

任务 8 为本节，任务 1-7 已全部完成：
- 任务 1：✅ 正式日初基线生成（`ensure_today_anchor` → `load_current_account_state`）
- 任务 2：✅ 收盘日结（`generate_closing_anchor` → 写次日锚点 + daily_summary + pnl_history.json）
- 任务 3：✅ 清理 dashboard_data.json.pnl 遗留（gen 不再覆盖实时持仓）
- 任务 4：✅ 资金事件类型扩展（`fund_events` 表 + `FUND_EVENT_TYPES` 白名单 + `insert_fund_event` / `query_fund_events`）
- 任务 5：✅ 纠错机制（`insert_correction_trade` → `is_reversal=1` + `reversal_of_id`）
- 任务 6：✅ 异常告警（5% 快照偏差告警 + `valuation_complete` 降级）
- 任务 7：✅ 回放演练（`FullLifecycleReplayTests` 完整生命周期测试）
- 任务 8：✅ 更新事故报告（本文档）
