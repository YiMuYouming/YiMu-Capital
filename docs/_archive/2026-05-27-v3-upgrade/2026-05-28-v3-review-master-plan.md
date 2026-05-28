# 弈沐资本数据看板 v3.0 Review 总控

> 日期：2026-05-28  
> 审查人：欧米  
> 范围：`1efcc65 feat: finalize trading dashboard upgrade` 之后的当前工作区  
> 约束：只读审查；不改业务代码；不写真实 `data/`；不对真实 8088 发写请求

---

## 1. 本轮结论

当前系统已经从“文件基线 + 手工覆盖”推进到“账户 SSOT + rule_state + 健康门禁 + W15/W22/W23 闭环”的可用架构，P0 级成交写入门禁主体已落地：后端有输入校验与并发卖出事务门禁，前端有 pending 与同一 `event_id` 重试。

v3.0 不应推翻现有架构，重点应放在三件事：

1. **把剩余可信链闭合**：当前成交写入仍固定不绑定 `rule_state` / `market_snapshot`，W23 大量显示“人工记录 / 未验证”，复盘无法还原当时规则上下文。
2. **修正账户锚点和日初基准的运维一致性**：当前真实 API 中 `valuation_complete=true`，但隔夜持仓与当日清仓仍出现 `_day_start_price=null` / `realized_today_pnl=null`，与 2026-05-27 运维基线描述冲突。
3. **把健康状态和 UI 行为拆细**：`/api/health` 当前 `degraded` 会被顶栏当作关键不健康处理，容易把非关键延迟等同于交易关键链阻断；界面上仍有大量内联样式、拥挤顶栏、版本文案和 README 不一致。

---

## 2. 开工现场

### 2.1 git / data 状态

只读命令：

```bash
git status --short
git diff -- data/
```

事实：

- `data/auction_snapshot.json`、`data/dashboard_data.json`、`data/llm_insights.json`、`data/pnl.db`、`data/pnl_history.json`、`data/sentiment_auto.json` 均已有真实运行 diff。
- `data/*.bak.*`、`data/pnl.db.corrupted_bak*`、`data/zt_history.json`、`data/ymwm_report.json` 等大量未跟踪运行/备份产物存在。
- 本轮未清理、未恢复、未写入这些文件。

影响：

- v3 实施前必须继续保留“真实 `data/` 不动”的纪律。
- 需要新增只读审计命令和 `.gitignore` 规则，避免备份产物持续污染审查视野。

### 2.2 真实 8088 只读接口现状

只读 GET：

```bash
curl -fsS http://localhost:8088/api/health
curl -fsS http://localhost:8088/api/account/state
curl -fsS http://localhost:8088/api/pnl/summary
curl -fsS 'http://localhost:8088/api/trades/review?date=2026-05-27'
```

关键结果：

- `/api/health`：`status=degraded`；`quotes.status=close_snapshot`；`account.status=ok`；`pnl.status=ok`；`baseline/iwencai=delayed`。
- `/api/account/state`：`valuation_complete=true`、`quote_status=close_snapshot`，但兴森科技 `_day_start_price=null`、两笔当日清仓 `realized_today_pnl=null`。
- `/api/trades/review?date=2026-05-27`：三笔成交均无 `rule_state` / `market_snapshot`。

---

## 3. P0/P1/P2 问题台账

### P0-1：W15 前端数量输入会被 `parseInt` 静默截断

代码位置：

- `widgets/positions.js:351`
- `scripts/bridge.py:1586-1597`
- `tests/test_sync_guard.py:214-217`

现象：

- 后端 validator 已拒绝 `数量=1.5`。
- 但 W15 表单提交前先执行 `parseInt(g('f_qty')) || 0`，用户输入 `1.5` 会变成 `1` 再发给后端，绕过“拒绝小数”的真实意图。

影响：

- 成交写入安全门禁存在 UI 侧漏口，可能把错误输入变成另一笔合法成交。

建议修法：

- 前端保留原始字符串给统一 validator，使用 `Number()` 和 `Number.isInteger()` 判断，不得用 `parseInt` 截断。
- 增加前端行为测试：`f_qty=1.5` 时不调用 `fetch('/api/sync')`，表单保留并提示错误。

验证方式：

```bash
python3 -m unittest tests.test_frontend_g3b tests.test_sync_guard -v
node --check widgets/positions.js
```

### P0-2：账户 reducer 对历史超卖账本仍会先加现金再截断持仓

代码位置：

- `scripts/account_ssot.py:159-166`
- `scripts/account_ssot.py:193-211`
- `scripts/db.py:494-576`

现象：

- 写入路径已通过 `insert_trade_with_context()` 做原子卖出门禁。
- 但 reducer 本身遇到历史坏账本时仍先执行 `cash += trade_cash_effect(trade)`，再用 `min(qty, old_qty)` 截断持仓数量。

影响：

- 一旦历史 DB 中已有超卖记录，回放会虚增现金，并可能继续输出看似可信的资产。
- 这是防御层问题，不是当前主写入路径问题。

建议修法：

- reducer 加账本不变量：卖出数量超过可用数量时返回 `valuation_complete=false` / `ledger_error`，不得增加超卖部分现金。
- 增加隔离测试：手工插入超卖历史记录，`reduce_account_state()` 返回错误状态且现金不虚增。

验证方式：

```bash
python3 -m unittest tests.test_account_ssot tests.test_sync_guard -v
```

### P1-1：成交复盘上下文仍未绑定，W23 无法验证当时规则

代码位置：

- `scripts/bridge.py:1655-1663`
- `scripts/db.py:494-576`
- `widgets/trade-review.js:123-170`
- `tests/test_trade_review.py:340-392`

现象：

- `/api/sync` 调用 `insert_trade_with_context(..., rule_state=None, market_snapshot=None)`。
- `trade_records` 当前三笔 2026-05-27 成交 `has_rule=0`、`has_snapshot=0`。
- W23 只能显示“人工记录 / 未验证”。

影响：

- Gate 3 的“成交可追溯”没有真正闭环。
- AI/规则复盘只能看事后结果，不能判断当时是否满足规则。

建议修法：

- 后端收到当日在线单笔成交时，服务端自行采集 `context_captured_at`、`rule_state`、精简 `market_snapshot`。
- 历史补录、健康关键链不可信、客户端夹带上下文时标记 `context_status=unavailable/untrusted`，但不伪装 verified。
- W23 分开展示“成交时间”和“上下文采集时间/不可用原因”。

验证方式：

```bash
python3 -m unittest tests.test_trade_review tests.test_sync_guard tests.test_frontend_g3b -v
```

### P1-2：LLM 快照持仓仍从 `dashboard_data.json` 构建，可能与账户 SSOT 冲突

代码位置：

- `scripts/bridge.py:946-967`
- `scripts/bridge.py:989-1005`

现象：

- `_build_full_snapshot()` 的 `持仓` 使用 `dd.get('positions')`，再套实时行情。
- 账户风控和 `rule_state` 读取的是 `_current_pnl_summary()` / SSOT。

影响：

- LLM 同一份 prompt 中可能同时包含“SSOT 风控/规则”和“旧基线持仓”两套口径。
- 对已清仓标的、补录标的、日初基准异常标的，AI 可能给出过期持仓建议。

建议修法：

- `_build_full_snapshot()` 的持仓域改为 `account_state.positions`，清仓跟踪单独输出 `closed_positions`。
- 对 `valuation_complete=false` 的价格、盈亏字段输出不可用，不用 dashboard 成本/现价兜底成可信数据。

验证方式：

```bash
python3 -m unittest tests.test_llm_validation tests.test_account_ssot -v
```

### P1-3：当前真实账户 API 与 2026-05-27 运维基线冲突

代码/数据位置：

- `docs/audit/2026-05-27-升级改造完成验收与运维基线.md:85-112`
- `scripts/account_ssot.py:120-143`
- `scripts/account_ssot.py:281-304`
- 真实只读 API：`/api/account/state`
- 只读 DB：`account_baselines._meta_json`

现象：

- 运维基线记录兴森科技、沪电股份、中芯国际已经补录 `day_start_price`。
- 当前 `data/pnl.db` 中 2026-05-27 `manual_correction` 锚点 `_meta_json` 只有 `nav/pnl_pct/total_asset/mv`，没有 `day_start_prices`。
- 真实 API 返回兴森科技 `_day_start_price=null`，两笔清仓 `realized_today_pnl=null`。

影响：

- 今日盈亏/清仓复盘在 UI 上会显示“基准不可用”。
- `/api/health` 仍显示账户 ok，无法暴露“有持仓但日初基准缺失”的细分风险。

建议修法：

- 先只读审计：输出每个持仓/清仓标的的 `day_start_price` 完整性报告。
- 修复路径必须继续走受控补录脚本，不允许测试写真实 `data/`。
- 健康检查新增 `day_start_basis` 子域：有隔夜持仓或当日清仓但基准缺失时 `degraded`，并在 W15/W22 明确显示。

验证方式：

```bash
sqlite3 data/pnl.db "SELECT date, source, substr(_meta_json,1,500) FROM account_baselines ORDER BY date DESC LIMIT 5;"
curl -fsS http://localhost:8088/api/account/state
```

### P1-4：顶栏健康把 `degraded` 等同于关键不健康，会误关交易入口

代码位置：

- `scripts/bridge.py:1193-1207`
- `index.html:802-816`
- `widgets/w1-check.js:388`
- `widgets/w2-check.js:192`

现象：

- 当前 `/api/health` 为 `degraded`，主要原因是 `baseline/iwencai=delayed`，而 `quotes/account/pnl` 均可用。
- 顶栏逻辑用 `ok = h.status === 'healthy'`，随后 `window._healthConfirmed = (ok && !hasCritical)`，导致所有非 healthy 都被视为 critical。
- W1/W2 的“录入”按钮依赖 `!window._healthCritical`。

影响：

- 非关键延迟会被 UI 表达为“不健康”，并可能隐藏可用的录入入口。
- 关键链阻断和可解释降级没有分层。

建议修法：

- `/api/health` 输出 `critical_ok` / `trade_entry_allowed` / `degraded_reasons`。
- 顶栏展示 `healthy/degraded/unhealthy` 三态；只有关键域失败或 `rule_state.tradable=false` 才关入口。
- W1/W2 入口同时显示被关闭原因。

验证方式：

```bash
python3 -m unittest tests.test_health_api tests.test_frontend_rule_state -v
```

### P1-5：被拒绝的 `tlist + positions` 请求仍会先改内存 `CACHE['_stock_codes']`

代码位置：

- `scripts/bridge.py:1535-1552`
- `scripts/bridge.py:1694-1700`

现象：

- `entry+positions` 和 `positions-only` 已提前拒绝。
- 但 `今日操作` 批量格式 `tlist` 若夹带 `positions`，会先进入 `positions_updated` 分支改 `CACHE['_stock_codes']`，之后才返回 `409 batch format deprecated`。

影响：

- 拒绝请求仍有内存副作用，可能污染当前 PyTDX 采集代码列表。

建议修法：

- 在任何 mutation 前统一拒绝所有 deprecated batch / positions payload 组合。
- 增加隔离测试：`{'今日操作': [...], 'positions': [...]}` 返回 409 且 `CACHE`、临时 data 文件均不变。

验证方式：

```bash
python3 -m unittest tests.test_sync_guard -v
```

### P1-6：LLM conversation JSON 写入没有进程内锁，存在并发丢消息风险

代码位置：

- `scripts/bridge.py:541-586`
- `scripts/bridge.py:1788-1799`
- `widgets/llm-chat.js:152-177`
- `widgets/llm-chat.js:179-263`

现象：

- 自动研判和手动问答都读 `llm_insights.json`，追加后 `atomic_write_json()`。
- 文件写是原子的，但“读旧值 -> 追加 -> 写回”没有锁。

影响：

- 自动触发与手动问答重叠时，后写入者可能覆盖先写入者的 conversation 追加。

建议修法：

- 使用进程内 `Lock` 或 file lock 包裹 conversation read-modify-write。
- 或把 LLM conversation 主存储迁入 SQLite，JSON 只作为导出视图。

验证方式：

```bash
python3 -m unittest tests.test_llm_validation -v
```

### P2-1：W22 不可信状态仍可能残留旧副标题

代码位置：

- `widgets/pnl-curve.js:395-408`
- `tests/test_frontend_w22.py:147-166`

现象：

- `valuation_complete=false` 时，`periodVal/ddVal/alpha` 会置为 `—`。
- 但当前测试没有断言 `alphaSub`，代码也没有在该分支设置 `pnl_today_alpha_sub` 和 `pnl_dd_sub`，可能保留上一次“实时收益/TWR−基准”的旧文案。

影响：

- 数值不可用但说明文本仍像实时可信，造成体验和语义不一致。

建议修法：

- 不可信分支统一清空/标记所有动态 KPI 的 value 和 sub。
- 行为测试补断言 `alphaSub/ddSub`。

### P2-2：布局预设文档与实现不一致

代码/文档位置：

- `README.md:54`
- `README.md:84`
- `index.html:629-672`
- 当前仓库无 `presets/` 目录

现象：

- README 仍写 `presets/ # 4 套布局预设`，快捷键表仍写 `1/2/3/4 切换预设布局`。
- 实现中只保留 localStorage 布局加载，注释写“preset select removed”。

影响：

- 新接手 agent 或主人按 README 操作会找不到功能。

建议修法：

- 二选一：恢复预设目录和快捷键，或删除 README 中的预设承诺。

### P2-3：顶栏和多个组件仍大量使用内联样式与 emoji 文案，视觉一致性差

代码位置：

- `index.html:43-92`
- `index.html:97-113`
- `widget-base.js:89-99`
- `widgets/pnl-curve.js:5-64`
- 多个 widgets 内联 `style="..."`

现象：

- 顶栏所有按钮、搜索框、状态指标集中在一行，移动/窄屏时靠 `flex-wrap` 换行，缺少明确分组。
- 多个按钮用 emoji 表意，例如 `🤖 AI盯盘`、`📈 收益曲线`、`🔄 立即研判`。
- W22 自注入 CSS，W21 样式写在 `index.html`，组件样式分散。

影响：

- 盘中高密度界面可用，但视觉层级和状态含义不够稳定。
- 后续组件扩展时容易继续堆内联样式。

建议修法：

- v3 建立 `css/components.css` 或 widget scoped class 命名规范。
- 顶栏按“健康/账户/操作/搜索”分组；关键操作使用一致按钮组件和图标策略。

### P2-4：`check_runtime.py` 把 8088 已运行标为错误，混淆启动前检查和运行中健康

代码位置：

- `scripts/check_runtime.py:156-169`

现象：

- 端口 8088 被占用时输出错误。
- 对“启动前检查”合理，对“盘中运维体检”不合理。

影响：

- 真实服务正在运行时，运行环境检查会返回非 0，容易制造误报。

建议修法：

- 增加模式：`--preflight` 检查端口空闲，`--health` 检查端口可访问并读取 `/api/health`。

---

## 4. 已确认良好项

- `scripts/bridge.py:1554-1630` 已有动作、代码、名称、价格、数量、时间后端校验。
- `scripts/db.py:494-576` 已有 `BEGIN IMMEDIATE` 原子卖出门禁和 `event_id` 幂等。
- `widgets/positions.js:361-377` 已有 pending 禁用、失败保留表单、成功后关闭。
- `scripts/db.py:259-341` 已返回 `data_date/is_fallback`，并兼容 `+08:00` 时间戳。
- `widgets/pnl-curve.js:713-724` 已处理全零曲线和 `null` 槽位绘图。
- `scripts/rule_engine.py` 是纯函数，无 I/O，适合作为 rule_state 核心继续扩展。

---

## 5. v3.0 审查路线

1. 先关闭 P0：W15 前端输入截断、账户 reducer 坏账本防御。
2. 再关闭 P1 可信链：成交上下文、LLM 快照 SSOT、健康分层、真实 day_start basis 审计。
3. 最后做 P2 体验和运维整理：W22 文案残留、README/预设一致性、顶栏/样式系统、runtime 模式拆分。

详细实施路线见 `docs/plans/2026-05-28-v3-upgrade-plan.md`。
