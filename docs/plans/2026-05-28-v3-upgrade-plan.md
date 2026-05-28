# 弈沐资本数据看板 v3.0 升级计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` or `subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.  
> 日期：2026-05-28  
> 基线：`1efcc65 feat: finalize trading dashboard upgrade` + 当前真实运行数据现场  
> 禁止：实施阶段不得写真实 `data/`，不得对真实 8088 发测试性写请求

> **执行状态更新（2026-05-27）：** v3.0 主线已完成。Phase 1 通过聊天验收；Phase 2-6 已在 Agent Board 验收通过。当前运维基线见 `docs/audit/2026-05-27-v3-completion-and-ops-baseline.md`。本文保留为计划与追溯材料，不再作为活跃派单入口。

**Goal:** 将当前 v2.5 看板升级为 v3.0：成交、账户、规则、AI、健康和 UI 体验形成更可信、更可审计、更容易运维的闭环。

**Architecture:** 保留现有零构建 HTML/CSS/JS + Python bridge + SQLite 架构。v3.0 只收紧契约和展示边界，不重写主系统；新增能力优先落在后端只读状态、隔离测试和组件小步改造。

**Tech Stack:** Python `unittest` / SQLite / APScheduler / 原生 JS / GridStack v12 / CSS variables。

---

## 1. 当前系统现状判断

当前系统已具备生产可用骨架：

- 账户 SSOT：`account_baselines + trade_records + fund_events + live_quotes -> account_state` 已成为 W15/W22 主要口径。
- 成交写入：后端 `/api/sync` 已有输入校验、`event_id` 幂等、原子卖出门禁。
- 规则链：`scripts/rule_engine.py` 输出 `rule_state`，组件和 LLM 校验能消费同一机器口径。
- 复盘闭环：W23 能读逐笔成交、outcome、review_note。
- 健康门禁：`/api/health` 已能识别 close snapshot、account、pnl 等状态。

但 v3.0 前仍有几个会影响实盘可信度的缺口：

- W15 UI 仍能把小数数量截断成整数提交。
- 历史坏账本防御不足，reducer 遇到超卖会先加现金。
- `/api/sync` 成交上下文固定为空，W23 不能验证当时规则。
- LLM prompt 的持仓快照仍使用 dashboard 基线，不完全服从账户 SSOT。
- 当前真实账户 API 中 day_start basis 与运维基线不一致。
- 健康 `degraded` 被顶栏当作 critical，容易误关入口。

---

## 2. 分级问题清单

### P0

| ID | 问题 | 代码位置 | 影响 | 修法 |
| --- | --- | --- | --- | --- |
| V3-P0-01 | W15 数量小数被 `parseInt` 截断 | `widgets/positions.js:351` | 错误输入可能变成合法成交 | 前端原始字符串校验；小数不发请求 |
| V3-P0-02 | reducer 历史超卖先加现金 | `scripts/account_ssot.py:159-166` | 坏账本会虚增现金并输出可信资产 | reducer 加 ledger invariant，超卖 fail-closed |

### P1

| ID | 问题 | 代码位置 | 影响 | 修法 |
| --- | --- | --- | --- | --- |
| V3-P1-01 | 成交上下文未绑定 | `scripts/bridge.py:1655-1663` | W23 无法验证当时规则 | 服务端采集 `context_captured_at/rule_state/market_snapshot` |
| V3-P1-02 | LLM 快照持仓不是 SSOT | `scripts/bridge.py:946-967` | AI 可能看到旧持仓 | LLM snapshot 改用 account_state.positions |
| V3-P1-03 | 真实 day_start basis 缺失未被健康暴露 | `scripts/account_ssot.py:120-143` | 今日/清仓盈亏不可用但 account 仍 ok | 增加只读审计与 health 子域 |
| V3-P1-04 | 顶栏健康误把 degraded 当 critical | `index.html:802-816` | 非关键延迟会隐藏录入按钮 | 后端输出 critical/trade_entry_allowed；前端三态展示 |
| V3-P1-05 | 拒绝 batch 时可能先改 CACHE | `scripts/bridge.py:1535-1552` | 被拒请求仍有内存副作用 | mutation 前统一拒绝 deprecated payload |
| V3-P1-06 | LLM conversation 无锁写 JSON | `scripts/bridge.py:541-586` | 自动/手动并发可能丢消息 | 加锁或迁入 SQLite |

### P2

| ID | 问题 | 代码位置 | 影响 | 修法 |
| --- | --- | --- | --- | --- |
| V3-P2-01 | W22 不可信状态可能残留旧副标题 | `widgets/pnl-curve.js:395-408` | UI 文案与数据可信状态不一致 | 动态 KPI value/sub 一起置不可用 |
| V3-P2-02 | README 预设布局与实现不一致 | `README.md:54`、`index.html:629-672` | 新接手按文档操作失败 | 恢复预设或删文档承诺 |
| V3-P2-03 | 样式分散且顶栏拥挤 | `index.html:43-113`、`widgets/pnl-curve.js:5-64` | 扩展和移动端体验差 | 抽组件样式，重分组顶栏 |
| V3-P2-04 | `check_runtime.py` 运行中误报端口占用 | `scripts/check_runtime.py:156-169` | 盘中体检非 0 | 拆 `--preflight` / `--health` |

---

## 3. 功能提升建议

1. **逐笔成交可信上下文**
   - 当日在线单笔成交自动绑定服务端接收时的 `rule_state`、账户状态摘要、情绪 freshness、候选池字段。
   - W23 展示“成交时间 / 上下文采集时间 / context_status / unavailable_reason”。

2. **账户基准完整性面板**
   - 新增 `/api/account/audit` 只读端点，输出今日锚点、隔夜持仓、当日清仓、`day_start_prices` 覆盖率。
   - W15/W22 只展示摘要，不给修复按钮；修复仍走受控脚本。

3. **健康三态与可交易状态分离**
   - `/api/health` 增加 `critical_ok`、`trade_entry_allowed`、`degraded_reasons`。
   - 顶栏用“正常 / 降级 / 阻断”三态，不再把所有 degraded 都当 critical。

4. **LLM prompt 可信瘦身**
   - LLM 只接收 SSOT 持仓、rule_state、关键情绪、候选池、健康摘要。
   - 明确把 stale/untrusted 数据放入 `risk_notes`，避免混在普通字段中。

---

## 4. 样式体验建议

- 顶栏分四组：健康状态、账户指标、操作按钮、搜索/布局。窄屏时每组整组换行。
- 统一按钮：主操作、次操作、危险操作、图标按钮四种 class，减少内联 style。
- W22 KPI 保持当前信息密度，但把“累计”和“今日动态”视觉分区更清楚。
- W15 表单增加本地校验错误区域，错误不只靠 toast。
- W23 增加 context 状态筛选：全部 / 已验证 / 未验证 / 上下文不可用。
- README 和页面标题统一到 v3.0，避免 v2.0/v2.5/v3.0 混用。

---

## 5. 技术债与重构建议

- 将 `/api/sync` validator 从 `BridgeHandler.do_POST()` 抽为纯函数，前后端测试更容易对齐。
- 将 account reducer 增加 `errors/warnings` 输出契约，而不是只返回资产字段。
- 将 LLM conversation 从 JSON 主存储迁到 SQLite，JSON 作为只读导出或兼容层。
- 将 W22 注入 CSS、W21 内联 CSS、顶栏内联 style 逐步移入 `css/theme.css` 或新增 `css/components.css`。
- 将 `DataStore` 中 legacy `positions` 与 `pnl_live.positions` 的含义拆开，避免后续组件继续误用。

---

## 6. 风险和禁止事项

- 禁止直接编辑真实 `data/pnl.db`、`data/*.json` 做测试。
- 禁止对真实 `http://localhost:8088` 发 POST、纠错、刷新、日结或压力测试请求。
- 禁止用 `git restore`、`git clean` 清理现有数据现场。
- 禁止把 day_start_price 用成本价替代；只能用已核验昨收/收盘价来源。
- 禁止把客户端传入的成交时间当作可信规则快照时间。
- 禁止把 W22/W15 的合法零值和未知值混用。

---

## 7. 分阶段实施路线

### Phase 0：基线冻结与只读审计

**Files:**
- Create: `docs/audit/2026-05-28-v3-readonly-baseline.md`

- [ ] 记录 `git status --short`。
- [ ] 记录 `git diff -- data/` 是否已有变动，只写摘要，不粘贴大 diff。
- [ ] 只读记录 `/api/health`、`/api/account/state`、`/api/pnl/summary`。
- [ ] 只读记录 `sqlite3 data/pnl.db "PRAGMA integrity_check;"`。

验收：

```bash
git status --short
sqlite3 data/pnl.db "PRAGMA integrity_check;"
```

### Phase 1：成交写入与账本防御 P0

**Files:**
- Modify: `widgets/positions.js`
- Modify: `scripts/account_ssot.py`
- Modify: `tests/test_frontend_g3b.py`
- Modify: `tests/test_account_ssot.py`

- [ ] RED：W15 输入 `数量=1.5` 不调用 `/api/sync`，表单保留。
- [ ] 实现 W15 本地 validator：代码/名称非空，价格有限正数，数量正整数，时间合法。
- [ ] RED：历史超卖账本回放不能虚增现金，返回 `ledger_error`。
- [ ] 实现 reducer ledger invariant：超卖 fail-closed。
- [ ] GREEN：专项和全量测试。

验收：

```bash
python3 -m unittest tests.test_frontend_g3b tests.test_account_ssot tests.test_sync_guard -v
python3 -m compileall -q scripts tests
node --check widgets/positions.js
```

### Phase 2：成交上下文与 W23 可信复盘

**Files:**
- Modify: `scripts/db.py`
- Modify: `scripts/bridge.py`
- Modify: `widgets/trade-review.js`
- Modify: `tests/test_trade_review.py`
- Modify: `tests/test_sync_guard.py`
- Modify: `tests/test_frontend_g3b.py`

- [ ] RED：当日健康在线成交写入 trusted context。
- [ ] RED：历史补录或健康关键链失败写入 `context_status=unavailable`。
- [ ] RED：客户端夹带 `rule_state/market_snapshot` 被忽略或拒绝。
- [ ] 后端在同一请求中构建只读 context，不信任客户端成交时间。
- [ ] W23 展示 context 状态、采集时间、不可用原因。

验收：

```bash
python3 -m unittest tests.test_trade_review tests.test_sync_guard tests.test_frontend_g3b -v
python3 -m compileall -q scripts tests
node --check widgets/trade-review.js
```

### Phase 3：LLM 与 rule_state 可信快照

**Files:**
- Modify: `scripts/bridge.py`
- Modify: `tests/test_llm_validation.py`
- Modify: `widgets/llm-monitor.js`
- Modify: `widgets/llm-chat.js`

- [ ] RED：LLM snapshot 使用 SSOT positions，不包含已清仓持仓为 active。
- [ ] RED：`valuation_complete=false` 时 LLM snapshot 的价格/盈亏为不可用。
- [ ] 给 conversation read-modify-write 加锁。
- [ ] 保持 BUY 信号 hard validation 不回退。

验收：

```bash
python3 -m unittest tests.test_llm_validation tests.test_account_ssot -v
python3 -m compileall -q scripts tests
node --check widgets/llm-monitor.js widgets/llm-chat.js
```

### Phase 4：健康分层与账户基准审计

**Files:**
- Modify: `scripts/bridge.py`
- Modify: `scripts/account_ssot.py`
- Modify: `index.html`
- Modify: `tests/test_health_api.py`
- Modify: `tests/test_frontend_rule_state.py`

- [ ] 新增只读 account basis audit 数据结构。
- [ ] `/api/health` 输出 `critical_ok`、`trade_entry_allowed`、`degraded_reasons`。
- [ ] 顶栏显示 healthy/degraded/unhealthy 三态。
- [ ] W1/W2 录入入口只按 critical/trade_entry_allowed 关闭，并展示原因。

验收：

```bash
python3 -m unittest tests.test_health_api tests.test_frontend_rule_state tests.test_account_ssot -v
python3 -m compileall -q scripts tests
node --check index.html widgets/w1-check.js widgets/w2-check.js
```

### Phase 5：W22/W15/W23 体验收口

**Files:**
- Modify: `widgets/pnl-curve.js`
- Modify: `widgets/positions.js`
- Modify: `widgets/trade-review.js`
- Modify: `tests/test_frontend_w22.py`
- Modify: `tests/test_frontend_g3b.py`

- [ ] W22 不可信时所有动态 KPI value/sub 同步置不可用。
- [ ] W15 表单错误内嵌展示，不只依赖 toast。
- [ ] W23 增加 context 状态筛选。
- [ ] 保持红涨绿跌、零值语义、XSS 转义。

验收：

```bash
python3 -m unittest tests.test_frontend_w22 tests.test_frontend_g3b -v
for f in widgets/*.js store.js widget-base.js widget-registry.js; do node --check "$f" || exit 1; done
```

### Phase 6：样式系统与文档一致性

**Files:**
- Modify: `css/theme.css`
- Modify: `index.html`
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] 统一页面标题、README、AGENTS 到 v3.0。
- [ ] 决定恢复或删除 `presets/` 文档承诺。
- [ ] 抽出顶栏/按钮/表格/状态标签 class，减少新增内联 style。
- [ ] `check_runtime.py` 拆 `--preflight` 和 `--health`。

验收：

```bash
python3 scripts/check_runtime.py --health
node --check index.html store.js widget-base.js widget-registry.js
```

---

## 8. 后续派单拆分建议

### 洋米

适合执行需要后端事务、SQLite、隔离测试的包：

- `YM-V3-P0-LEDGER`：W15 前端输入校验 + reducer 坏账本防御。
- `YM-V3-G3-CONTEXT`：成交上下文写入 + W23 展示。
- `YM-V3-HEALTH`：健康分层 + account basis audit。

要求：

- 每包独立分支、独立提交。
- 测试全部用 temp DB/temp file。
- 交付时必须报告 `git diff -- data/` 相对开工前是否新增变化。

### 黑米

适合执行前端小范围 UI/交互：

- `HM-V3-W22-KPI`：W22 不可信/fallback 文案收口。
- `HM-V3-TOPBAR`：顶栏分组、按钮 class、视觉一致性。
- `HM-V3-W23-FILTER`：W23 context 状态筛选。

要求：

- 不碰后端写接口。
- 必须跑 JS syntax 和对应前端行为测试。

### 稳米

适合执行只读文档和运维整理：

- `WM-V3-DOCS`：README/AGENTS/操作手册版本一致性。
- `WM-V3-DATA-AUDIT`：只读汇总 day_start basis 缺失清单，不执行修复。
- `WM-V3-RUNBOOK`：把 preflight、health、盘后日结、补录流程写成 runbook。

要求：

- 不写真实 data。
- 不对 8088 发 POST。

---

## 9. v3.0 完成标准

- P0 全部关闭，新增 RED/GREEN 证据。
- `/api/trades/review` 至少能区分 verified / unavailable / untrusted context。
- LLM snapshot 与 W15/W22 账户口径一致。
- `/api/health` degraded 不再被顶栏误判为 critical。
- 当前真实 account state 的 day_start basis 缺失能被只读审计准确报告。
- README、AGENTS、页面标题、实际功能一致。
- 全量验证通过：

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q scripts tests
for f in widgets/*.js store.js widget-base.js widget-registry.js; do node --check "$f" || exit 1; done
git diff -- data/
```
