# AI Evidence Cockpit Design

## Goal

把弈沐资本仪表板从“数据展示 + 手工录入入口”优化为外部 AI 协同场景下的只读态势证据屏。用户在 CodexIDE、终端、洋米会话中完成追问、派单、确认和执行；仪表板负责半屏常亮、快速扫读、证据定位和异常提示。

## Non-Goals

- 不在仪表板里新增聊天、追问、派单、确认、审批等 AI 交互。
- 不让新组件读取其他组件 DOM。
- 不改交易录入 API，不对生产 `8088` 发 POST 测试。
- 不重构 DataStore、账户 SSOT、行情管线或 GridStack 架构。
- 不把 24 个组件一次性重写；只先深改核心证据链组件，其余做视觉规范收口。

## Primary Workflow

用户左侧打开仪表板和同花顺终端，右侧或独立窗口打开 CodexIDE / 终端 / 洋米会话。AI 对话中引用仪表板稳定编号，例如“看 `E1` 和 `A2`，判断光讯是否继续 W2”。仪表板需要让这些编号在视觉上稳定、可扫读、可复核。

## Evidence Taxonomy

编号是跨 Agent 的引用协议，必须稳定。

| Prefix | Meaning | Examples |
| --- | --- | --- |
| `S` | Situation，总态势 | `S0` 当前健康、情绪、盈亏、仓位、可交易状态 |
| `E` | Evidence，关键证据 | `E1` 核心持仓，`E2` 票据闭环，`E3` 市场情绪，`E4` 账户收益 |
| `A` | Alert，异常/注意项 | `A1` 数据源降级，`A2` 收盘快照，`A3` 票据缺口 |
| `R` | Risk，风险/规则状态 | `R1` 熔断/阻断，`R2` 仓位上限，`R3` 交易入口允许状态 |

编号分配原则：

- `S0` 固定为总态势。
- `E1-E9` 按证据重要性排序，不按 DOM 顺序排序。
- `A1-A9` 只放需要用户或 AI 注意的异常，不列正常项。
- `R1-R9` 只表达规则和风控，不混入普通市场数据。
- 同一交易日内编号含义尽量稳定；数据刷新只更新数值和状态，不随意重排。

## Architecture

新增纯函数模块 `evidence-summary.js`，输入 `DataStore.merged` 和轻量运行时状态，输出标准化证据快照。新增 `widgets/evidence-board.js` 注册为 `W25 态势证据屏`，只读渲染该快照。后续核心组件通过共享样式和可选 `data-evidence-id` 标注与 `W25` 对齐。

```text
DataStore / API / SSOT
        ↓
evidence-summary.js
        ↓
W25 态势证据屏
        ↓
外部 CodexIDE / 终端 / 洋米对话引用 S0/E1/A1
```

## Data Sources

`W25` 不发 POST，不读其他组件 DOM。数据来源：

- `DataStore.merged.pnl_live`：账户、仓位、盈亏、持仓、清仓、quote_status、valuation_complete、anchor_blocked。
- `DataStore.merged.trade_tickets`：票据状态、成交/关闭闭环、待确认/可执行/阻断。
- `DataStore.merged.iwencai`、`sentiment`、`live_index`、`market`：情绪、涨跌家数、涨跌停、数据新鲜度。
- `DataStore.merged.rule_state`：规则阻断、仓位上限、窗口状态。
- 运行时状态：`window._tradeEntryAllowed`、`window._healthCritical`、`window._healthConfirmed`、`DataStore.getConnectionStatus()`、`window._quoteHealthStatus`。

## UI Design

`W25` 默认 12x4 或 12x5，适合放在首屏顶部。布局采用四段：

1. `S0` 态势条：健康、连接、情绪、今日盈亏、仓位、可用资金、是否可交易。
2. 关键证据：`E1-E4` 卡片，强调持仓、票据、市场情绪、账户收益。
3. 异常/注意：`A1-A3` 紧凑列表，只显示需要关注的异常。
4. 风险/规则：`R1-R3` 规则状态，突出阻断和仓位限制。

视觉要求：

- 看板是只读态势屏，控件数量少，不出现聊天框。
- 编号必须醒目但不抢占数值；推荐蓝色小徽标。
- 异常项使用琥珀/红色，但避免把收盘快照这类非致命状态渲染成灾难感。
- 适配半屏宽度，文本不能溢出；长原因用两行截断。
- 所有数字使用等宽字体和 A 股红涨绿跌。

## Component Scope

Phase 1 深改：

- `W25 态势证据屏`：新增。
- 顶栏：保留健康和关键账户状态，后续可减少快捷按钮拥挤。
- `W15 持仓+操作+清仓`：加证据锚点和状态文案收口。
- `W24 交易票据`：加票据闭环证据锚点和只读摘要。
- `W04 市场全景`：加情绪/数据源证据锚点。
- `W22 收益曲线`：加账户收益证据锚点。

Phase 2 轻量统一：

- `W08/W09/W12/W13/W21` 等组件统一异常徽标、空状态、数字格式、标题层级。
- 组件选择面板里显示 `W25`，核心视图默认包含 `W25`。

## Acceptance Criteria

- `W25` 能在本地预览 `18088` 渲染，且不需要任何 POST。
- `W25` 在 `DataStore.merged` 缺字段时不崩溃，显示 `—` 或明确降级原因。
- `S0/E/A/R` 编号在同一份 fixture 下稳定。
- 当 `pnl_live.quote_status === "close_snapshot"` 时，显示“收盘快照/非实时”，但不误判为行情 dead。
- 当 `window._tradeEntryAllowed === false` 或 `rule_state.tradable === false` 时，`R` 风险项显示阻断。
- `pytest` 中新增的 evidence summary 测试通过。
- 手工浏览桌面和半屏宽度无文本重叠、无空白白屏。
