# 弈沐资本 AI Assist 需求文档

> 日期：2026-06-21
> 范围：Live Dashboard 下一阶段 AI 辅助层
> 状态：需求稿，供 W25 完成后继续开发使用

## 1. 一句话目标

AI Assist 不是另做一个完整 App，也不是再加一个聊天组件，而是把弈沐资本的盘前、盘中、票据、收盘复盘流程，沉淀成一套可被 Codex、洋米、W25、未来菜单栏小窗共同读取的结构化辅助层。

表面交互仍以对话框为主：主人继续在 Codex / Claude Code 中问“今天怎么做”“这个票能不能做”“帮我生成票据”。底层由 Live Dashboard 提供事实包、规则检查、票据状态、数据新鲜度和复盘证据，保证 AI 的回答更稳定、更可追溯、更能闭环。

## 2. 背景

当前 Live Dashboard 已经具备：

- 26 个组件，覆盖行情、情绪、账户、持仓、风控、票据、AI 研判、作战态势。
- `/api/ai/context` 只读事实包，向 Agent 暴露健康状态、freshness、风险、票据和人工待处理事项。
- W24 交易票据组件，支持票据生成、预览成交、确认成交和状态展示。
- W25 作战态势组件，已经承担首屏裁决和证据聚合的雏形。
- `review_source_packet.json`，在收盘流程中生成，供稳米复盘读取。

当前主要痛点：

1. 组件太多，盘中容易看不过来。
2. 部分信号不是实时数据，但 live / delayed / stale / baseline / manual 的区别没有被足够前置。
3. 票据流程仍然偏组件功能，盘中更需要一个待处理队列和闭环提醒。
4. Codex、洋米、稳米都会参与盯盘或复盘，需要共享同一份事实，而不是靠主人反复口头描述。

独立评估结论：AI Assist 的正确方向不是新增独立 App，而是在 Dashboard 内把 `/api/ai/context`、W25、W24、W15、W22/PnL 和收盘事实包连成一个更硬的盘前/盘中/收盘闭环。后续开发必须尊重 8088 生产写入、18088 只读预览、Vault 复盘 SSOT、W25 只读指挥台这四条边界。

## 3. 设计原则

### 3.1 聊天是入口，系统是底座

AI Assist 不改变主人当前最顺手的对话方式。盘前研判、盘中问票、收盘复盘，仍然可以在 Codex / Claude Code 对话框里完成。

AI Assist 要做的是把对话背后的输入和动作结构化：

- AI 每次先读同一份事实包。
- 交易判断必须携带 freshness 和规则门状态。
- 票据动作必须落到结构化 ticket，而不是停留在聊天文字。
- 收盘复盘必须能回看当天事实、票据、成交、阻断和数据缺口。

### 3.2 W25 是盘中状态中枢，不是大杂烩

W25 不承载所有组件内容，也不直接执行交易。它负责回答：

- 当前能不能交易。
- 如果不能，为什么。
- 如果能，下一步先处理什么。
- 当前只需要看哪 1-3 个组件。
- 哪些信号不是实时的。
- 哪些票据或人工事项未闭环。

### 3.3 任何交易动作都必须人审

AI Assist 可以生成票据、解释规则、提示风险、排序待办，但不能自动下单、自动确认成交、自动跳过人工复核。

买入、卖出、减仓、清仓、做 T、确认成交等动作，都必须保留明确的人审边界。

### 3.4 数据新鲜度是一等公民

任何可影响盘中动作的信号，都必须标注来源和新鲜度：

```text
live / delayed / stale / dead / baseline / manual / unknown
```

默认规则：

- live 可进入盘中裁决理由。
- delayed 可以进入裁决，但必须标注延迟。
- stale / dead 不能支持可交易动作，只能触发复核或阻断。
- baseline / manual 只能作为背景或人工输入，不应伪装成实时信号。

当前 `/api/ai/context.freshness` 已覆盖 quotes、iwencai、account、baseline。tickets、llm/research history、review_packet 若暂未进入 freshness，前端和 Agent 必须显示为 unknown 或 unsupported，不能默认当成 live。

## 4. 系统边界

### 4.1 放在 live-dashboard 的内容

以下内容属于 Live Dashboard 项目：

- `/api/ai/context` 事实包。
- `/api/health`、`/api/account/state`、`/api/trade/tickets?date=YYYY-MM-DD` 等盘中状态接口。
- W25 盘中指挥台。
- W24 票据工作台。
- W15 持仓/成交入口。
- freshness、风险、next_actions、human_required 的聚合逻辑。
- AI Assist 相关需求、设计、运行手册。

推荐目录：

```text
docs/ai-assist/
scripts/ai_assist/
```

### 4.2 放在 ai-rule-system 的内容

以下内容仍属于 AI 执行层和规则门：

- 交易规则运行包。
- Rule Gate 输出协议。
- Agent 读取规则、生成 ticket、输出观察/建议的边界说明。
- 提示词、规则 manifest、运行时规则解释。

### 4.3 放在 Vault 的内容

以下内容仍以 Vault 为最终权威源：

- 交易规则解释。
- 复盘正文。
- 次日计划。
- 交易教训。
- 长期市场认知。

### 4.4 暂不新建独立 App

当前不新建完整独立 App，也不把 Sidecar Agent 纳入本阶段实现范围。`docs/audit/2026-06-20-dashboard-3-closeout.md` 已把 Sidecar 作为下一版本种子，本需求只要求 Dashboard 内的 AI Assist 指挥能力先稳定。

未来如果 W25 和 `/api/ai/context` 稳定，可以再做菜单栏小窗或 sidecar。

菜单栏/sidecar 的定位只能是 W25 的精简伴随版：

- 当前状态。
- 待处理票据数。
- 关键风险数。
- 数据新鲜度。
- 下一步。
- 点击跳回 dashboard 对应组件。

## 5. 核心能力

### 5.1 盘前作战事实包

盘前 AI 研判时，应能读取固定结构的事实输入，而不是临场拼接。

输入应包括：

- 昨日复盘摘要入口。
- 今日候选池：连板池、趋势池、锚定股。
- 当前风格状态。
- 账户总资产、现金、持仓、仓位。
- 风控线：日内、周、月、连亏、特殊禁令。
- 今日允许窗口：W1 / W2 / 午盘 / 尾盘。
- 昨日未闭环票据。
- 数据新鲜度和缺口。

输出应包括：

- 今日可做 / 不可做。
- 优先观察标的。
- 关键风险。
- 最容易犯的错。
- AI 盘中盯盘重点。
- 是否需要先处理旧票据或数据缺口。

第一阶段可以不新增复杂界面，只要求对话 Agent 读取 `/api/ai/context`、Vault 次日计划和规则门后，用固定格式回复。

### 5.2 盘中注意力雷达

盘中 AI Assist 的核心不是给更多信息，而是替主人排序注意力。

必须回答：

```text
现在最该看哪 1-3 件事？
哪些信号发生变化？
哪些数据不能信？
有没有票据没闭环？
有没有规则门或健康门禁阻断？
```

建议由 W25 和 `/api/ai/context.next_actions` 共同承载。

最低要求：

- 每个 next_action 都有 code、title、reason、target。
- target 能映射到 W24/W15/W14/W08/W09/W10/W20/W23 等组件。
- next_actions 按优先级排序：阻断 > 人审 > 票据 > 风控 > 数据新鲜度 > 观察。
- stale/dead 数据自动进入风险或人工复核，不得作为买卖依据。

交易门禁口径：

- 盘中是否允许交易，以 `ai_context.situation.trade_entry_allowed` 为核心口径。
- 阻断或允许原因，以 `ai_context.situation.trade_entry_reason` 为核心口径。
- 顶栏“降级”不自动等于“阻断”；是否关闭交易入口必须回到 health 和 rule_state 的合成结果。

### 5.3 票据流程助手

票据是 AI Assist 的核心闭环对象。对话框可以发起票据请求，但票据本身必须结构化。

票据流程应覆盖：

```text
intent_text
  -> prepare ticket
  -> rule gate check
  -> draft / confirmed / executable / blocked / audit_degraded
  -> fill preview
  -> human confirmation
  -> trade record
  -> post-trade review
  -> close / closed_with_conflict
```

AI Assist 对票据的能力：

- 根据自然语言意图生成票据草稿。
- 解释票据为什么 blocked、confirmed、executable 或 audit_degraded。
- 提醒待确认、可执行、冲突、待复核票据。
- 成交后关联 W15 持仓和 W23 逐笔复盘。
- 收盘时检查今日票据是否全部闭环。

禁止事项：

- 不允许 AI 自动确认成交。
- 不允许在健康阻断时生成买入可执行结论。
- 不允许用 stale 行情支持买入/加仓票据。
- 不允许把聊天文本当成票据 SSOT。
- 不允许 W25 发送任何 POST；出票据、预览成交、确认成交仍归 W24/W15 相关流程。
- 不允许在 18088 只读预览环境录真实交易；真实成交写入只允许 8088 生产入口。

### 5.4 数据新鲜度守门

AI Assist 必须把 freshness 作为回答和展示的硬约束。

关键数据源：

- quotes：行情。
- iwencai：情绪。
- account：账户和持仓估值。
- baseline：日初/复盘基线。
- tickets：票据。
- llm：外部研判历史。
- review_packet：收盘事实包。

最低要求：

- `/api/ai/context.freshness` 必须足以支撑 Agent 判断哪些数据可交易、哪些只能参考。
- W25 必须集中展示关键 freshness。
- Agent 输出涉及交易动作时，必须说明关键数据 freshness。
- stale/dead 必须进入 `risks` 或 `human_required`。
- tickets 和 llm 若无法提供实时 freshness，必须显式显示 unknown，不允许静默当作 live。

### 5.5 AI 协作摘要

Codex、洋米、稳米应尽量围绕同一事实源协作。

盘中 Agent 标准开场应类似：

```text
我读取当前 /api/ai/context：
交易入口：可用 / 阻断
行情：live / delayed / stale
账户：正常 / 降级 / 错误
票据：待确认 N，可执行 N，冲突 N
关键风险：...
下一步：...
```

目标是减少主人重复描述盘面，让不同 Agent 对“当前事实”达成一致。

### 5.6 持仓与收益事实联动

W15 持仓、W22/PnL 和 `/api/account/state` 是 W25 与 AI Assist 的关键证据源。

必须进入盘中解释的事实：

- 当前持仓数。
- 可卖数量和 T+1 限制。
- 总资产、现金、市值、仓位。
- 当日盈亏和收益率。
- valuation_complete 是否为真。
- 账户 anchor 是否可信。
- 估值缺口或行情缺失导致的 block_reason。

要求：

- W25 可以展示持仓/收益摘要，但不要复制 W15/W22 的完整明细。
- 若 valuation_complete 为 false，AI 不得给出基于完整账户估值的交易结论。
- 若可卖数量不足，卖出/减仓/清仓票据必须进入人审或阻断说明。

### 5.7 事实包失败降级

`/api/ai/context` 失败时，Dashboard 不能白屏，也不能假装事实包可用。

要求：

- W25 显示“AI 事实包不可用”。
- 可回退到当前 `DataStore.merged` 展示有限态势。
- 交易建议降级为只观察或人工复核。
- Agent 若读不到事实包，应先查 `/api/health`，并明确说明事实缺口。

### 5.8 收盘复盘教练

收盘后 AI Assist 不只生成复盘文本，还要检查闭环质量。

应读取：

- `review_source_packet.json`。
- 今日票据状态。
- 成交记录。
- PnL 和持仓变化。
- 健康/freshness 记录。
- 当天 AI 研判历史。

应输出：

- 今日是否按规则执行。
- 哪些票据闭环完整，哪些有冲突。
- 哪些动作是计划内，哪些可能是临场冲动。
- 哪些信号因 stale/dead 不应被使用。
- 哪些规则或提示词需要升级。
- 哪些经验应写回 Vault feedback / insights。

## 6. W25 对接要求

W25 完成当前开发后，AI Assist 的第一阶段应与 W25 对齐，而不是另起炉灶。

W25 应稳定承载四块：

```text
S0 当前裁决
A1 待处理队列
E1 关键证据
F1 数据新鲜度
```

### 6.1 S0 当前裁决

S0 必须给出一句明确裁决：

- 可执行。
- 只观察。
- 阻断。
- 降级可用。
- 收盘/复盘。

并给出：

- 当前阶段。
- 交易入口状态。
- 一句话原因。
- 下一步。

### 6.2 A1 待处理队列

A1 应合并：

- 票据待确认。
- 票据可执行。
- 成交待复核。
- 票据冲突。
- 健康降级待确认。
- freshness stale/dead 待复核。

每条待办至少包含：

- code。
- title。
- reason。
- target。
- priority。

优先级建议：

```text
critical health/rule block
  > stale/dead trading data
  > human_required
  > executable tickets
  > pending tickets
  > account/valuation issues
  > ordinary observation
```

### 6.3 E1 关键证据

E1 展示不超过 3-5 条证据：

- 账户/持仓。
- 票据闭环。
- 市场情绪。
- 账户收益。
- 风控/规则门。

每条证据必须显示 source 和 freshness。

### 6.4 F1 数据新鲜度

F1 集中展示：

- quotes。
- iwencai。
- account。
- baseline。
- tickets。
- llm。

其中 stale/dead 必须有明显视觉提示，并影响 S0 和 A1。

## 7. API 合约要求

### 7.1 `/api/ai/context`

该接口继续作为 AI Assist 的主要事实入口。

必须保持：

- 只读。
- 不写 DB。
- 不写文件。
- 不调用交易 mutation endpoint。
- 出错时返回可解析的 error payload，而不是让 Agent 猜测。

建议逐步增强字段：

```json
{
  "schema_version": "ai_context.v1",
  "generated_at": "...",
  "mode": "preopen|intraday|closed|review",
  "situation": {},
  "freshness": {},
  "tickets": {},
  "risks": [],
  "alerts": [],
  "next_actions": [],
  "human_required": [],
  "evidence": [],
  "positions": [],
  "candidates": []
}
```

新增字段必须向后兼容。不要让 Codex、洋米、W25 因字段缺失崩溃。

真实字段口径：

- `trade_entry_allowed` 位于 `situation.trade_entry_allowed`。
- `trade_entry_reason` 位于 `situation.trade_entry_reason`。
- `freshness` 当前至少包含 quotes、iwencai、account、baseline。
- tickets 汇总位于 `tickets`，包括 pending、executable、completed、blocked、other、items。
- 阻断、风险、人工要求分别位于 `risks`、`alerts`、`human_required`。

### 7.2 票据 API

票据相关 API 是动作中枢，不是展示辅助。

要求：

- prepare ticket 时必须经过规则和健康上下文检查。
- preview fill 和 confirm fill 必须分离。
- confirm fill 必须有人审字段。
- close ticket 必须通过受控端点写入终态和审计原因，不能把 Markdown 审计副本或裸 SQL 当作票据闭环入口。
- 票据状态必须能被 `/api/ai/context.tickets` 汇总。
- 冲突必须进入 alerts 或 human_required。

W25 与 AI Assist 只能消费票据摘要、解释状态、跳转目标组件。具体写入仍由 W24/W15 的既有门禁保护，不能新增旁路写入。

### 7.3 Agent 输出协议

任何 Agent 若基于 AI Assist 给出盘中建议，必须使用这个顺序：

1. 事实源读取状态。
2. 数据新鲜度。
3. 交易入口/规则门状态。
4. 票据状态。
5. 建议或观察。
6. 人审要求。

不允许直接跳到“可以买/可以卖”。

## 8. 第一阶段开发范围

W25 完成后，第一阶段 AI Assist 不做大系统，优先做小闭环。

### 8.1 必做

- 梳理 `/api/ai/context` 是否覆盖 W25 所需的 S0/A1/E1/F1。
- 给 next_actions 增加稳定 code、priority、target。
- 给 freshness 补齐 tickets、llm 或明确暂不支持。
- 让 W25 能消费或映射这些字段。
- 若 `/api/ai/context` 拉取失败，W25 明确显示事实包不可用并回退到有限态势。
- 写一份 Agent 盘中读取 `/api/ai/context` 的 runbook。
- 写一份票据状态到 AI 协作的说明。

### 8.2 可选

- 增加盘前事实包命令或脚本。
- 增加收盘复盘教练提示词。
- 增加菜单栏/sidecar 的只读摘要设计。
- 增加 Agent 输出模板。

### 8.3 暂不做

- 独立完整 App。
- 自动交易。
- 自动确认成交。
- 新聊天 UI。
- 替代 Vault 的最终复盘。
- 替代 ai-rule-system 的规则源。

## 9. 后续菜单栏 / Sidecar 方向

Dashboard 3.0 Phase 4 曾将 Sidecar Agent 延后。AI Assist 稳定后，可以重新评估。

Sidecar 的第一版必须只读：

- 读取 `/api/ai/context`。
- 显示状态摘要。
- 触发本地通知。
- 点击打开 dashboard。
- 不发 POST。
- 不修改账户或票据。

建议展示：

```text
状态：可交易 / 阻断 / 只观察
行情：live / stale
票据：待确认 N / 可执行 N
风险：N
下一步：核对 W24 / 复核 W14 / 保持观察
```

## 10. 验收标准

第一阶段完成后，应满足：

1. 主人在盘中打开 W25，10 秒内知道当前能不能交易、为什么、下一步是什么。
2. Codex 或洋米读取 `/api/ai/context` 后，不需要主人复述盘面即可给出事实摘要。
3. 任何 stale/dead 关键数据都会进入风险、待办或人审要求。
4. 票据待确认、可执行、冲突、待复核能进入 W25 或 AI 摘要。
5. Agent 给交易相关建议时，会先说明 freshness、规则门和票据状态。
6. W25 不直接执行交易，只跳转到 W24/W15 等具体操作组件。
7. 收盘复盘能基于 review packet 和票据状态检查闭环，而不是只写流水账。
8. 文档清楚标明 Vault、ai-rule-system、live-dashboard 的边界，不把规则源复制进 dashboard。
9. `GET /api/ai/context` 保持只读，不写 DB、不建 anchor、不触发交易 mutation。
10. W25 的任务队列能合并 `risks / alerts / human_required / tickets / next_actions`，并能跳转目标组件。
11. 18088 预览环境不允许真实写入；8088 生产入口的写入门禁不被绕过。
12. `/api/ai/context` 不可用时，W25 不白屏，且明确显示事实包不可用。

建议验证：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_health_api.AIContextApiTest -v
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q scripts tests
git diff --check
```

如涉及 W25 前端渲染，还需要在 18088 预览环境检查：无白屏、无文本重叠、首屏半屏内可读、跳转目标正确。

## 11. 给后续开发 Agent 的开工清单

开发前先读：

1. `/Users/yimu/Documents/YM_Capital/live-dashboard/AGENTS.md`
2. `/Users/yimu/Documents/YM_Capital/live-dashboard/README.md`
3. `/Users/yimu/Documents/YM_Capital/live-dashboard/docs/audit/2026-06-20-dashboard-3-closeout.md`
4. `/Users/yimu/Documents/YM_Capital/live-dashboard/widget-registry.js`
5. `/Users/yimu/Documents/YM_Capital/live-dashboard/evidence-summary.js`
6. `/Users/yimu/Documents/YM_Capital/live-dashboard/widgets/evidence-board.js`
7. `/Users/yimu/Documents/YM_Capital/live-dashboard/widgets/trade-tickets.js`
8. `/Users/yimu/Documents/YM_Capital/live-dashboard/scripts/bridge.py`

开发时注意：

- 不要对真实 8088 发 POST 测试。
- 不要提交 `data/*` 运行数据。
- 不要把 W25 改成交易执行入口。
- 不要绕过 W24/W15 的健康门禁和人审流程。
- 不要把 Vault 规则正文复制到 dashboard 文档里。
- 新字段和新 UI 都要兼容缺字段、API 降级、只读预览环境。

## 12. 独立评估补充

本需求文档已经过一个只读 Agent 评估，关键补充如下：

- W25 只能提醒、跳转、解释，不发送 POST。
- W24/W15 保留出票据、预览成交、确认成交和真实写入门禁。
- 真实生产写入只允许 8088；18088 是只读预览。
- `ai_context.situation.trade_entry_allowed` 和 `ai_context.situation.trade_entry_reason` 是交易入口判断核心。
- tickets/llm freshness 当前可能缺字段，需求应要求补齐或显式 unknown。
- `review_source_packet.json` 只是收盘复盘输入，不是最终复盘 SSOT。
- Sidecar/Menu bar 属于后续版本，不进入第一阶段实现范围。
