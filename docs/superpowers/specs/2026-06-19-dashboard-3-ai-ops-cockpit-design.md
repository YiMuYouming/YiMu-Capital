# Dashboard 3.0 AI Ops Cockpit Design

## 背景

弈沐资本看板 2.x/3.1 已经完成稳定性底座：账户 SSOT、健康门禁、行情 fallback、票据闭环、开收盘脚本和 W25 作战态势。下一阶段不应继续堆组件，而是把看板收口成 AI 可协作的盘中作战台。

当前真实工作流是：用户看同花顺实时盘面和动态仪表盘，洋米负责盘中盯盘，稳米负责复盘沉淀，欧米负责方案、代码和疑难修复。Dashboard 3.0 的目标是让 AI 承担 90% 的采集、整理、解释、排队、留痕和复盘，用户保留 10% 的判断、风险授权和关键交易确认。

## 目标

1. 简化首屏，让盘中只看最关键的事实、风险和下一步动作。
2. 保持灵活，不把用户锁进固定流程；不同交易日可以按实际盘面展开侧屏证据。
3. 让 AI 和人读同一份结构化事实，减少口径漂移。
4. 交易动作保持人审：AI 起草、解释、提醒，人确认买卖和重要风险动作。
5. 让复盘自然闭环：盘中证据、AI 判断、用户动作、交易结果和规则修正建议都可追溯。

## 非目标

- 不做全自动实盘交易。
- 不把聊天框、派单台或复杂 Agent 控制台塞进仪表盘首屏。
- 不一次性重写 25 个组件。
- 不改变账户 SSOT、票据 API、健康门禁和生产/预览边界。
- 不把同花顺替代掉；同花顺仍是用户观察实时盘面的关键外部工具。

## 设计原则

- **瘦身优先**：默认展示更少模块，保留可展开证据，不追求信息铺满。
- **事实先行**：仪表盘只负责事实、状态、异常和证据，不替用户做最终交易判断。
- **AI 可读**：核心状态必须能被 Codex、洋米、稳米通过稳定字段读取，而不是靠截图或 DOM 猜。
- **人审闭环**：买卖、加仓、清仓、修正规则和提高风险上限都必须留在人类确认边界内。
- **失败显性**：数据 stale、行情缺失、账户不可信、票据冲突必须明确显示，不能用旧数据装作实时。

## 3.0 工作模式

### 盘前模式

盘前关注今天能不能交易、主线是什么、风险预算是多少、候选从哪里来。

核心模块：

- W25 作战态势：健康、风险、今日命令。
- W04 市场全景：基础市场环境。
- W12/W13 候选池：连板/趋势候选。
- W14 风控：总仓位、单票上限、熔断线。
- W24 交易票据：AI 预备票据和待确认动作。

### 盘中模式

盘中关注现在是否可交易、持仓是否安全、有没有可执行票据、异常是什么。

核心模块：

- W25 作战态势：首屏总态势和下一步。
- W15 持仓快照：持仓、盈亏、清仓后跟踪。
- W24 票据 Inbox：待处理、可执行、已完成、审计记录。
- W14 账户风控：熔断、仓位和风险阻断。
- W04 市场全景：情绪、涨跌停、指数。
- W22 收益曲线：账户日内曲线。
- W08/W09：只在需要判断 W1/W2 时展开。

### 复盘模式

复盘关注交易质量、错过机会、票据闭环、AI 判断质量和规则修正。

核心模块：

- W23 逐笔复盘。
- W24 票据闭环与审计记录。
- W22 收益曲线。
- W25 当日态势摘要。
- LLM 历史摘要。
- 自动生成的复盘事实包和稳米交接材料。

## 组件分层

### 首屏必看

- W25 作战态势
- W15 持仓快照
- W24 票据 Inbox
- W14 账户风控
- W04 市场全景
- W22 收益曲线

### 侧屏核对

- W08 W1 早盘确认
- W09 W2 实时观察
- W10 板块热力图
- W12 连板自选池
- W13 趋势自选池
- W21 涨停梯队
- W06 竞价 5 维

### 复盘/低频

- W20 研判摘要
- W23 逐笔复盘
- W05 情绪节点对比
- W11 15min 量价图
- W17 今日操作
- W18 锚定股状态
- W19 午盘复核

### 默认隐藏或后续评估

使用率低、信息与 W25/W04/W14 重叠、或只在特定场景使用的组件不删除，但不进入默认驾驶舱。隐藏不是废弃，后续根据一个月实际使用日志再决定是否归档。

## AI 状态出口

新增只读状态出口，建议路径为 `/api/ai/context`。它不是给浏览器首屏用的花哨接口，而是给 Codex、洋米、稳米和后续 sidecar agent 读的事实协议。

建议字段：

```json
{
  "date": "YYYY-MM-DD",
  "mode": "preopen|intraday|review|closed",
  "situation": {
    "health": {},
    "connection": {},
    "trade_entry_allowed": false,
    "pnl": {},
    "position": {},
    "sentiment": {}
  },
  "evidence": [],
  "alerts": [],
  "risks": [],
  "tickets": {},
  "positions": [],
  "candidates": [],
  "freshness": {},
  "next_actions": [],
  "human_required": []
}
```

口径要求：

- 所有字段只读，不触发交易写入。
- 数据新鲜度必须随字段返回，不能只返回数值。
- `human_required` 用来列出必须人审的动作，例如买入确认、卖出确认、风险上限调整、规则改动。
- 该接口优先复用现有 W25 `EvidenceSummary`、`rule_state`、`/api/health`、`/api/account/state` 和票据数据。

## AI 协作边界

### 欧米

- 负责架构、代码、审查、疑难问题和规则工程化。
- 默认在本仓库完成设计、计划、实现、测试、提交和推送。

### 洋米

- 负责盘中盯盘执行和终端侧落地。
- 通过 `/api/ai/context` 和 W25 编号读取事实，不靠主观转述。

### 稳米

- 负责复盘、沉淀、记录和低成本整理。
- 使用收盘复盘事实包、票据闭环和 AI 历史判断生成日度材料。

### 用户

- 保留交易确认、风险授权、规则方向和资金管理最终判断。
- 不需要被固定流程束缚，可以随盘面临时展开侧屏证据。

## 实施阶段

### Phase 0：基线保护

在任何 3.0 代码改动前，先保证当前生成代码已提交并推送。工作区必须明确干净或明确列出未提交原因。

验收：

- `git status --short` 清晰。
- 已有改动单独提交，不混入 3.0 新方案。
- 相关测试通过。

### Phase 1：组件瘦身方案落地

目标是确定三种模式的默认布局和隐藏策略，不改数据口径。

工作：

- 给 25 个组件补充 `usageRole` 或等价元数据。
- 定义 `intraday_cockpit` 默认布局。
- 保留组件库和侧屏入口，避免不可逆删除。
- 顶栏操作入口只保留高频动作。

验收：

- 首屏默认只出现核心组件。
- 侧屏证据仍可打开 W10/W12/W13/W21。
- 布局保存、驾驶舱切换、核心视图不互相打架。
- 前端规则测试通过，必要时补充布局测试。

### Phase 2：AI 状态出口

目标是让 AI 通过一个稳定接口读取盘中事实。

工作：

- 新增 `/api/ai/context` 只读 GET。
- 复用 W25 证据摘要的字段和编号。
- 暴露数据新鲜度、风险阻断、人审动作和下一步建议。
- 添加后端单元测试，覆盖 stale、阻断、收盘快照和票据冲突。

验收：

- `curl /api/ai/context` 能返回稳定 JSON。
- stale/dead 数据不会被包装成可交易建议。
- 生产 8088 不做 POST 测试。
- 相关 Python 测试通过。

### Phase 3：复盘事实包自动化

目标是让稳米可直接拿到一天的材料。

工作：

- 收盘后生成 `review_source_packet.json`：账户、PnL、持仓、成交、票据闭环、健康/新鲜度、AI context 风险和人审动作。
- 保持运行数据不进 git。
- 输出 JSON 事实包给 WorkBuddy `daily-review` / `auto-review-fill` 使用；Vault 复盘笔记仍是最终 Markdown/次日计划 SSOT。
- 稳米 skill 必须优先尝试读取事实包，但 packet 缺失或 stale 不阻断复盘，只进入缺失/复核清单。

验收：

- 收盘脚本 dry-run 可预览产物。
- 真实 apply 不覆盖生产数据。
- 事实包不调用 POST，不创建账户锚点，不把 stale/dead/untrusted 数据包装成确定结论。
- 稳米规则明确：packet 是证据输入，不是最终复盘 SSOT，W12/W13 仍读 Vault 复盘附录。

### Phase 4：盯盘 Sidecar Agent（下一版本）

Phase 4 从 Dashboard 3.0 中拆出，作为下一版本的主题。V3 收口后不继续在本版实现 sidecar 代码。

目标是把 90% 的盯盘整理工作交给 AI，但不越过人审边界。

工作：

- 独立 sidecar 读取 `/api/ai/context`。
- 定时生成观察、异常、候选排序和票据草稿。
- 重要动作进入 `human_required`，不自动成交。
- 可通过 agent-board 分派给洋米执行、稳米复盘。

验收：

- sidecar 关闭不影响仪表盘和交易录入。
- AI 输出可追溯到 `S/E/A/R` 证据编号。
- 所有交易写入仍通过既有票据/成交确认路径。

## 测试策略

- 前端：优先扩展 `tests/test_frontend_rule_state.py`，覆盖布局、核心组件可见性、W25/W24 文案和只读模式。
- 后端：新增或扩展 `tests/test_health_api.py`、`tests/test_rule_state_api.py`、`tests/test_ticket_api.py`，覆盖 `/api/ai/context`。
- 运维：涉及开收盘脚本时先 dry-run，再决定是否 apply。
- 浏览器：涉及布局和文字溢出时，用本地预览 `18088` 或静态测试验证桌面/半屏。

## 风险与约束

- 当前仓库有生产和预览边界，禁止对真实 8088 发 POST 测试。
- `data/*` 不走 git，复盘事实包和运行快照要遵守数据边界。
- hermes PyTDX 不稳定是已知限制，3.0 不以恢复 PyTDX 为前提。
- AI 建议必须携带证据编号和数据新鲜度，否则不进入行动队列。
- 默认布局瘦身可能短期改变用户习惯，必须保留一键展开和回退。

## 推荐下一步

Dashboard 3.0 到 Phase 3 收口。下一步不是继续扩本版功能，而是进入 V3 closeout：确认文档、WorkBuddy skill、AGENTS/README、开收盘 SOP、SSOT 边界和测试证据一致。

Sidecar Agent 作为下一版本启动，先写新的 spec/plan，再实现。

## Phase 1 Implementation Note

Phase 1 implemented the cockpit slimming layer:

- Widgets now declare `usageRole` metadata.
- Intraday cockpit defaults to six first-screen modules: W25, W15, W24, W14, W04, W22.
- W08/W09/W10/W12/W13/W21/W06 remain available through the evidence shelf or component panel.
- Topbar direct shortcuts are limited to high-frequency modules plus evidence shelf and full component panel.
- No account SSOT, ticket API, health gate, data source, or POST behavior changed.

## Phase 3 Closeout Note

Phase 3 implemented the review source packet layer:

- `scripts/ops/generate_review_source_packet.py` builds `review_source_packet.v1`.
- `scripts/ops/close_day.py --apply` generates the packet after close sync, local integrity check, and ticket review summary, before the project data backup.
- Packet files live under `data/review_packets/YYYY-MM-DD/review_source_packet.json` and remain out of git.
- WorkBuddy `daily-review` and `auto-review-fill` are the consumers; Vault review notes remain the final daily review and next-day-plan SSOT.
- Phase 4 sidecar-agent watch service is deferred to the next version.
