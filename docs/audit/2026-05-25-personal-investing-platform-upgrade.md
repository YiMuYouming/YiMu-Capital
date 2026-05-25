# 个人股票投资平台升级计划

> 2026-05-25 | 目的：把 `live-dashboard` 从“实盘看板”升级为更适合个人投资者长期使用的操作平台

---

## 一、结论

当前项目已经具备个人交易系统的核心骨架：实时行情、复盘笔记 SSOT、风控、持仓、PnL、AI 盯盘、竞价和自选池都已接上。但它现在更像“能跑的监控台”，离“稳定、可信、适合日常交易决策的平台”还差四个关键能力：

1. 运行底座必须稳定，不能依赖碰运气。
2. 盘前必须先判断“今天这套数据能不能信”。
3. 交易规则必须统一，不能让 widget 和 AI 各讲各的。
4. 交易必须能回放、能归因、能复盘。

这份计划按优先级拆成四阶段，先稳住，再提效，最后做闭环。

---

## 二、现状判断

### 已经做对的部分

- 已有 `bridge.py + store.js + widget` 的完整数据闭环。
- 已有 `dashboard_data.json / pnl.db / llm_insights.json / auction_snapshot.json` 等结构化资产。
- 已有 W03/W14/W15/W22 等核心交易视图。
- 已有规则文档 `LLM_RULES.md`，AI 盯盘不是纯聊天，而是围绕交易纪律工作。
- 已有 `ymwm_report.json` 这种健康检查雏形。

### 当前主要问题

- Python 运行环境不完整，部分脚本导入会失败。
- 采集路径存在硬编码，机器迁移后容易断。
- 文档版本和组件版本有漂移，盘中很难判断“当前到底是哪一版”。
- 健康状态没有成为前端第一信息，用户仍然要靠经验判断平台是否可靠。
- 交易规则分散在 `LLM_RULES.md`、widget 逻辑、AI prompt 中，容易出现口径不一致。
- 缺少交易归因闭环，长期只能“看盈亏”，不能系统性发现自己的错误模式。

---

## 三、升级目标

### 目标 1：可信

开盘前能快速判断今天的数据是否新鲜、行情是否覆盖、PnL 是否正常、持仓是否一致。

### 目标 2：高效

盘中默认界面要围绕真实交易流程组织，而不是 22 个组件平铺让人自己找重点。

### 目标 3：统一

规则引擎、组件提示、AI 研判、风控判断必须共用同一套口径。

### 目标 4：可复盘

每笔交易都要能回到“当时看到什么、规则是否通过、为什么做、最后结果如何”。

---

## 四、实施分期

### P0：运行底座修复

#### 任务

- 补齐 Python 依赖说明和安装方式。
- 把写死的 `/Users/YouMing/...` 路径改成可配置路径或 `Path.home()` 推导。
- 新增运行自检脚本，检查依赖、路径、桥接端口、关键数据文件。
- 统一 README 和启动说明，避免文档和实际入口不一致。

#### 重点文件

- `scripts/bridge.py`
- `scripts/collectors/quotes.py`
- `scripts/collectors/market_data.py`
- `scripts/collectors/iwencai_poll.py`
- `scripts/snapshot_auction.py`
- `scripts/style_detect.py`
- `README.md`
- `scripts/check_runtime.py`

#### 验收

- `python3 scripts/check_runtime.py` 能明确告诉我哪里正常、哪里失败。
- `python3 scripts/bridge.py 8088` 可以启动。
- `/api/pnl/summary`、`/api/live/quotes`、`/api/debug/snapshot` 都能返回可用数据。

---

### P1：盘前健康中心

#### 任务

- 新增统一健康 API `/api/health`。
- 把 bridge、基线、行情覆盖、PnL、持仓一致性、竞价、AI 状态做成统一检查项。
- 新增一个健康总览组件，放到第一屏或顶栏入口。
- 让 `ymwm_report.json` 成为可视化入口，而不是仅供脚本写盘。

#### 重点文件

- `scripts/bridge.py`
- `index.html`
- `widgets/health-center.js` 或同类新组件
- `data/ymwm_report.json`

#### 验收

- 盘前一眼能看出今天是否适合开工。
- 任何 fail/warn 都必须显式显示，不允许静默降级成“看起来正常”。

---

### P2：交易驾驶舱布局

#### 任务

- 提供三套内置布局：盘前准备、盘中交易、盘后复盘。
- 恢复布局切换入口，让默认视图更贴近真实工作流。
- 顶栏固定关键指标：情绪值、实时盈亏、仓位、可用资金、连接状态、健康状态。
- 默认不再是空白画布或纯自由摆放。

#### 重点文件

- `index.html`
- `css/theme.css`
- `widget-registry.js`
- `store.js`

#### 验收

- 首次打开不需要手动拼装布局。
- 盘中第一屏即可完成“看情绪、看仓位、看持仓风险、看机会”的主流程。

---

### P3：统一规则引擎

#### 任务

- 把交易规则结构化为单独规则模块。
- 让 W03/W08/W09/W14/W15/W20 都读取同一份规则结果。
- 让 AI 输出引用规则引擎的结果，而不是自己自由解释硬规则。
- 保留 `LLM_RULES.md` 作为人类说明，不再承担机器执行逻辑。

#### 重点文件

- `scripts/rule_engine.py`
- `scripts/bridge.py`
- `widgets/w1-check.js`
- `widgets/w2-check.js`
- `widgets/position-calc.js`
- `widgets/risk-panel.js`
- `widgets/llm-monitor.js`
- `widgets/llm-chat.js`

#### 验收

- 禁买、熔断、连亏、高潮、周五限制等规则只有一套口径。
- AI 不会直接输出未经规则验证的 BUY 结论。

---

### P4：交易复盘闭环

#### 任务

- 扩展交易记录结构，保存当时快照、规则结果、人工备注、事后归因。
- 新增交易复盘视图，按交易列出“做了什么、当时为何能做/不能做、结果如何”。
- 盘后输出当日执行摘要，方便长期观察自己的错误模式。

#### 重点文件

- `scripts/db.py`
- `scripts/bridge.py`
- `index.html`
- `widgets/today-ops.js`
- `widgets/positions.js`
- 新增 `widgets/trade-review.js`

#### 验收

- 每笔交易都能回到当时的规则判断和快照。
- 可以统计最近交易里最常见的错误类型。
- 盘后复盘不再只看收益曲线，而是看决策质量。

---

## 五、推荐执行顺序

1. 先做 P0，保证系统可启动、可采集、可验证。
2. 再做 P1，把“今天这套平台能不能信”变成显式信号。
3. 接着做 P2，让界面符合个人交易者的真实工作流。
4. 然后做 P3，把规则统一起来。
5. 最后做 P4，把交易闭环补完整。

---

## 六、测试与验收

### 启动检查

- `python3 scripts/check_runtime.py`
- `python3 scripts/bridge.py 8088`
- `curl http://localhost:8088/api/health`

### API 检查

- `/api/baseline`
- `/api/live/quotes`
- `/api/live/iwencai`
- `/api/pnl/summary`
- `/api/debug/snapshot`
- `/api/llm/history`

### 规则检查

- 熔断归零
- 连亏空仓
- 周五趋势上限
- 高潮保护
- W1/W2 禁买条件

### 复盘检查

- 新交易记录是否带上快照和规则结果。
- 盘后摘要是否能回看执行偏差。

---

## 七、文件落点

本计划建议保留在：

`/Users/yimu/Documents/YM_Capital/live-dashboard/docs/audit/2026-05-25-personal-investing-platform-upgrade.md`

