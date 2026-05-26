# 统一账户资产 SSOT 设计

## 目标

将盘中账户资产从 `dashboard_data.json`、浏览器本地状态、`CACHE["pnl"]` 和 PnL 快照的多点写入，收束为一条可审计、可重放的后端状态链，保证 W15、W22 与 API 始终消费同一份账户结果。

## 权威边界

| 数据 | 权威性 | 写入规则 |
| --- | --- | --- |
| `account_baselines` | 权威 | 每日一个锁定锚点；事故日允许建立恢复锚点 |
| `trade_records` | 权威 | 交易事件追加写入，唯一索引保证重复同步幂等 |
| 实时行情缓存 | 估值输入 | 只能改变市值、总资产和日内 PnL |
| `intraday_snapshots` | 派生记录 | 从账户状态生成，可重建，不可反写现金或持仓 |
| `dashboard_data.json.positions` | 展示镜像 | 兼容当前前端展示，不参与权威账户计算 |
| `/api/sync` | 命令入口 | 接收新增成交；拒绝 `pnl` 资产字段覆盖 |

## 状态模型

账户锚点字段：

- `date`: 交易日。
- `effective_at`: 锚点创建时刻，用于审计与界面解释。
- `trade_id_cutoff`: 锚点创建前已经存在的最大流水 ID；仅重放 ID 更大的新增事件。
- `cash`: 锚点时刻已结算可用资金。
- `positions_json`: 锚点时刻的实际持仓。
- `day_start_asset`: 当日收益计算基准，来自昨收资产。
- `total_deposit`: NAV 所需累计入金。
- `source`: `recovery`、`previous_close` 或 `manual_seed`。

由锚点与锚点后追加的交易事件重放得到：

- `cash = anchor.cash + sum(trade_cash_effect)`。
- `positions = anchor.positions + buy_qty - sell_qty`。
- `mv = sum(current_price * open_qty)`。
- `total_asset = cash + mv`。
- `pnl_amount = total_asset - day_start_asset`。
- `pnl_pct = pnl_amount / day_start_asset`。

卖出、买入只通过流水改变现金和数量。事件按成交时间展示、按同一时间内的追加 ID 保序重放。行情只参与 `mv` 计算；缺少任一开放持仓实时价或行情超过五分钟未更新时，状态可供展示兜底，但不得生成权威快照。

## 状态机

| 状态 | 事件 | 转换与不变量 |
| --- | --- | --- |
| `UNINITIALIZED` | 建立锚点 | 进入 `ANCHORED`；保存现金、持仓、收益基准 |
| `ANCHORED` | 开盘或首次盘中读取 | 进入 `OPEN`；锚点不可被普通同步覆盖 |
| `OPEN` | 新成交 | 保持 `OPEN`；仅新增流水驱动现金/数量变化 |
| `OPEN` | 重复成交同步 | 保持 `OPEN`；数据库忽略重复事件，状态不变 |
| `OPEN` | 行情变化 | 保持 `OPEN`；仅估值和 PnL 改变 |
| `OPEN` | 生成快照 | 保持 `OPEN`；快照只读取当前派生状态 |
| `OPEN` | 行情缺失 | 标记 `degraded`；停止写入权威快照 |
| `OPEN` | 收盘 | 进入 `CLOSED`；日结供下一日锚点生成 |

## 事故日迁移

`2026-05-26` 不能重新假定一个未经核验的开盘状态。首次部署后，从已经核验的午盘状态创建 `source=recovery` 的账户锚点，记录当时 `trade_records` 的最大 ID 为 `trade_id_cutoff`；已经存在的成交保留供审计，不再次计入现金。之后新增成交即使补录的是更早成交时间，也会因 ID 更大而正确纳入 reducer。

## 接口行为

- `GET /api/account/state`: 返回当前账户 SSOT 派生结果、完整当日交易账本及锚点信息。
- `GET /api/pnl/summary`: 资产、仓位和日内收益字段来自账户 SSOT；快照计数等图表元信息可保留现有读取。
- `POST /api/sync`: 出现 `pnl` 字段即返回冲突错误；成交列表按唯一键追加流水；`positions` 只作为页面兼容镜像写入。
- `log_pnl_snapshot`: 调用账户 SSOT；估值不完整时不写新快照。
- bridge 启动先绑定唯一监听端口，再启动调度器和冷启动采集；端口冲突的重复进程不得写入任何快照。

## 测试契约

1. 锚点重放一次买入和一次部分卖出，现金、数量、总资产与 PnL 结果正确。
2. 锚点创建前已有的事故日流水不被重复计算，锚点后补录早时刻成交仍会计算。
3. 行情变化不会改变现金或持仓数量。
4. 缺少开放持仓实时价或报价过期时，状态标记为不可写权威快照。
5. `/api/sync` 无法以 `pnl` 覆盖现金或总资产。
6. PnL 摘要以状态机结果覆盖坏快照结果。
7. 重复 bridge 无法绑定端口时，不会在退出前生成快照。
8. 前端不再直接编辑账户现金或已成交流水，W15 从账本渲染完整当日成交。
