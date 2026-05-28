# 弈沐资本数据看板 v3.0

> 弈沐资本盘中交易决策指挥台。23 组件 + AI 盯盘 + 实时数据管线。
> 启动：`python3 scripts/bridge.py 8088` → Chrome `http://localhost:8088`

## 核心数据管线

```
复盘笔记(SSOT) → gen_dashboard_data.py → dashboard_data.json(每日基线)
PyTDX 通达信 5s → bridge CACHE → /api/live/quotes (实时行情)
iwencai pywencai 10min → CACHE["iwencai"] → 情绪指标
同花顺 5min → CACHE["hot_list"] → 涨停梯队
同花顺 60s → CACHE["northbound"] → 北向资金
log_pnl_snapshot 5min → pnl.db (PnL曲线)
sentiment_snapshot 30min → sentiment_auto.json (情绪节点快照)
snapshot_auction 9:28 → auction_snapshot.json (竞价5维)
APScheduler auto → 15min AI研判 (后端,浏览器关了也跑)

注意：复盘笔记占位符"—"自动回退昨天数据。gen每天只跑一次。
```

## 架构

```
live-dashboard/
├── index.html              # GridStack v12 画板 + W20浮动聊天框
├── store.js                # DataStore 三层合并(基线+实时+手工)
├── widget-base.js          # YiMuWidget 基类(生命周期+错误隔离)
├── widget-registry.js      # 23组件注册表
├── LLM_RULES.md            # AI研判用交易规则(蒸馏~70行)
├── widgets/                # W01-W23 组件 + W20浮动聊天框
│   ├── timeline.js         # W01 时段
│   ├── style-detect.js     # W02 风格
│   ├── position-calc.js    # W03 仓位
│   ├── market-overview.js  # W04 全景
│   ├── sentiment-dash.js   # W05 情绪节点
│   ├── auction-5d.js       # W06 竞价
│   ├── climax-guard.js     # W07 高潮
│   ├── w1-check.js         # W08 W1早盘
│   ├── w2-check.js         # W09 W2尾盘
│   ├── sector-heat.js      # W10 板块
│   ├── volume-bars.js      # W11 量价
│   ├── lianban-pool.js     # W12 连板池
│   ├── trend-pool.js       # W13 趋势池
│   ├── risk-panel.js       # W14 风控
│   ├── positions.js        # W15 持仓
│   ├── input-panel.js      # W16 报数
│   ├── today-ops.js        # W17 操作
│   ├── anchor-stocks.js    # W18 锚定
│   ├── midday-review.js    # W19 午盘
│   ├── llm-monitor.js      # W20 AI摘要
│   ├── zt-echelon.js       # W21 梯队
│   ├── pnl-curve.js        # W22 收益曲线
│   ├── trade-review.js     # W23 逐笔复盘
│   └── llm-chat.js         # W20浮动聊天框(extends YiMuWidget)
├── scripts/
│   ├── bridge.py            # HTTP桥接+APScheduler(20+job)
│   ├── collectors/          # 数据采集器
│   ├── gen_dashboard_data.py# 笔记→JSON(含-pnl风控自动算)
│   ├── snapshot_auction.py  # 竞价5维快照(9:28)
│   └── db.py                # pnl.db CRUD
├── css/theme.css            # 暖砚设计系统
├── data/                    # JSON+SQLite数据文件
├── docs/                    # 计划+审计+操作手册
└── AGENTS.md                # 本文件
```

## 关键架构决策

- **账户 SSOT**：账户锚点 + 成交流水 + 资金事件 + 实时行情统一派生账户状态，2026-05-27 专项验收通过
- **实时规则**：`rule_state` 是组件与 AI 的盘中规则唯一机器口径
- **健康门禁**：`/api/health` 及顶栏在关键数据不可信时 fail-closed
- **实时 vs 每日**：PyTDX 5s 行情实时，iwencai 10min 情绪准实时，复盘笔记每日基线
- **W20 AI 系统**：DeepSeek V4-Flash → 浮动聊天框 → 15min自动研判+手动问答+3轮对话记忆+后端APScheduler
- **PnL 曲线**：3层保护（gen冷启动守护+preserve_pnl+日内基准用昨日收盘）
- **gen 防覆盖**：每天只跑一次，盘中bridge重启不覆盖W15实时持仓
- **竞价面板**：自选池自动过滤已清仓/不追标的，清仓标的PyTDX仍跟踪

## API 端点

| 端点 | 方法 | 说明 | 频率 |
|------|------|------|------|
| `/api/baseline` | GET | dashboard_data.json | 60s |
| `/api/live/quotes` | GET | 实时行情(含iwencai/北向/热榜/15minK) | 5s |
| `/api/live/iwencai` | GET | 情绪指标 | 10min |
| `/api/llm` | POST | AI研判(支持mode=auto/manual+question+userMsg) | 实时 |
| `/api/llm/history` | GET | 今日对话历史(v2 conversation) | — |
| `/api/debug/snapshot` | GET | 全盘8域快照(调试) | — |
| `/api/health` | GET | 服务与关键数据健康状态 | 实时 |
| `/api/account/state` | GET | 账户 SSOT 派生状态 | 实时 |
| `/api/pnl?range=today&index=sh` | GET | PnL曲线 | 5min/日结 |
| `/api/pnl/summary` | GET | PnL摘要 | 实时 |
| `/api/trades/review?date=YYYY-MM-DD` | GET | W23逐笔复盘 | 按需 |
| `/api/sync` | POST | W15单笔成交录入 | 随录 |
| `/api/refresh` | POST | 触发gen | — |

## 股票数据处理

- 接口字段名通常带日期后缀（如`竞价评级[20260520]`），代码必须用`find_field()`/`_v()`模糊匹配，别用`d.get()`精确查找
- liveCACHE指数/行情每5s覆盖一次，collect_index需用update而非赋值，否则yesterday_compare数据被抹
- 万亿成交额解析先判断万亿再处理亿，顺序反了抛异常
- 持仓状态同时过滤"清"和"删"，只过滤"清"会漏掉已删除标的
- iwencai数据小数vs百分数格式不一致：晋级率(0.38=38%)需×100，涨跌收益(0.05=0.05%)不需要
- 清仓标的代码需加入PyTDX采集列表，否则清仓跟踪无现价

## 故障排查速查

| 症状 | 排查 |
|------|------|
| 看板白屏 | bridge在跑吗？`curl localhost:8088/api/pnl/summary` |
| 情绪数据空/过时 | iwencai 10min轮询在跑吗？`/api/live/quotes` 有iwencai字段吗？ |
| W22资产/曲线异常 | 先核查`/api/account/state`与`/api/pnl/summary`的SSOT资产和日初锚点是否一致 |
| 竞价面板无数据 | 9:28过了吗？auction_snapshot.json mtime 今天？ |
| 成交额对比无显示 | `collect_yesterday_compare` 数据被 collect_index 覆盖了？检查 quotes.py 是否用 update |
| LLM研判不触发 | `~/.Codex/settings.json` 有 ANTHROPIC_BASE_URL 和 ANTHROPIC_AUTH_TOKEN 吗？ |
| 清仓跟踪现价空 | 清仓标的代码在 PyTDX 采集列表吗？bridge 重启会重新加载代码列表 |
| W15显示“基准不可用” | 核查隔夜标的是否缺 `_meta.day_start_prices`；仅用受控补录脚本修复已核验开盘价/日初价 |

## 开发原则

1. **先查文档再改**：GridStack、API 签名不确定先查官方文档，不试错
2. **组件独立**：每个 widget 只订阅自己的 dataPaths
3. **零构建**：纯 HTML/CSS/JS，CDN 仅 GridStack.js@12.x
4. **红涨绿跌**：涨跌颜色+符号必须同时使用
5. **内联 CSS**：所有组件用内联样式，优先 CSS 变量
6. **Component extends YiMuWidget**：所有组件继承基类管理生命周期

---

## 任务派单标准路径（Agent Board 最佳实践）

### 触发词

当你说「欧米给你派了任务你去拿一下」或「有新的任务清单」，立即执行以下步骤。

### 第一步：找任务文档

2026-05-25 发起的升级改造主体和 2026-05-27 v3.0 升级主线已落地。当前有效基线与任务位置：

```
docs/audit/2026-05-27-v3-completion-and-ops-baseline.md   ← 当前 v3.0 完成状态与运维基线
docs/_archive/2026-05-27-v3-upgrade/                      ← v3.0 Review/派单/返工过程，仅供追溯
docs/_archive/2026-05-25-dashboard-upgrade/                ← 旧升级计划/派单/交付，仅供追溯
docs/audit/YYYY-MM-DD-给{米名}-{任务名}.md                ← 后续新任务指令
```

命名规律：
- `给洋米` = 给洋米的执行指令（直接复制发给洋米）
- `给黑米` = 给黑米的执行指令（直接复制发给黑米）
- `v3-completion-and-ops-baseline` = 当前架构、验收边界与运维基线（欧米先读）

后续开工先读当前基线；不得从归档 Gate/v3 派单文件自行续做。

### 第二步：读任务的结构

每个任务章节固定有以下区块，按顺序处理：

```
## 任务 ID：HM-G0A
### HM-G0A：固定运行环境、路径解析和测试隔离
**负责人：** 黑米
**目标：** 简洁说明要达成什么
**文件范围：** 新增/修改哪些文件
---
## 执行清单
- [ ] 逐条执行项（先读一遍再动手）
## 欧米验收
```bash   ← 复制粘贴运行
验证命令
```
**通过条件：** 简洁说明
```

### 第三步：执行原则

1. **严格 TDD**：先写/调测试，确认 RED，再写最小实现，最后 GREEN
2. **不超范围**：禁止范围（禁止做什么）必须严格遵守，遇到需要改禁止范围的立即 BLOCKED 并报告
3. **真实数据最高保护**：所有 `data/*` 文件只读不写；测试必须用 `TemporaryDirectory` 或 mock
4. **每个任务单独分支、单独提交**：`data/` 运行产物不得混入提交
5. **先保存开工基线**：
   ```bash
   git status --short
   git diff -- data/       # 确认为空
   ```
6. **禁止对真实 8088 实例做写操作**：POST、纠错、日结、压力测试必须用隔离实例或测试 harness

### 第四步：交付格式

每完成一个任务，回传以下内容：

```
状态：DONE / DONE_WITH_CONCERNS / BLOCKED
任务：（与新任务文档中的 ID 一致）

实际修改文件：
- （列出每个文件及改动摘要）

每项需求对应实现：
- [需求1] → 已实现，验证方式：（命令或描述）
- [需求2] → 已实现，验证方式：（命令或描述）

RED 测试命令及失败摘要：
（每个行为先失败时的错误输出，1-3行摘要）

GREEN/完整验证命令及结果：
（所有欧米验收命令 + 输出结果）

git status --short 输出：
（当前所有改动）

git diff -- data 是否为空：
（为空 or 非空及原因）

是否触碰真实 8088 或真实数据：
（是/否，触碰了什么）

尚存风险或需欧米决策的问题：
（0-N 条）
```

### 第五步：交付后停下

- 交付后立即停下，不继续下一个任务
- 等欧米回传下一包新任务，再继续
- 不自行扩大范围或添加功能

### 常见陷阱

| 陷阱 | 正确做法 |
|------|----------|
| 遇到新 bug 顺手修了继续做 | 记录为 TODO，单独开任务处理 |
| 改到禁止范围 | 立即 STOP，报告 BLOCKED，等欧米决策 |
| 测试后忘了恢复真实 data | 始终用 TemporaryDirectory，永远不写 data/ |
| 一次做两个 Gate | 每次只做一个 Gate 内的任务 |
| 把未确认改动混入提交 | 先 `git status`，确认干净再 commit |
