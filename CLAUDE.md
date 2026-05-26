# 弈沐资本数据看板 v2.5

> 弈沐资本盘中交易决策指挥台。22 组件 + AI 盯盘 + 实时数据管线。
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
├── widget-registry.js      # 22组件注册表
├── LLM_RULES.md            # AI研判用交易规则(蒸馏~70行)
├── widgets/ (22 files)     # W01-W22 独立组件
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
└── CLAUDE.md                # 本文件
```

## 关键架构决策

- **账户 SSOT**：account_baselines（锚点）+ trade_records（追加流水）+ 实时行情（估值）→ 当前状态。pnl.db 快照仅派生，不可反写。
- **gen 防覆盖**：每天只跑一次，盘中 bridge 重启不覆盖 W15 实时持仓
- **竞价面板**：自选池自动过滤已清仓/不追标的，清仓标的 PyTDX 仍跟踪
- **SSOT 全部一致**：8 大数据域唯一来源，2026-05-20 审计通过
- **实时 vs 每日**：PyTDX 5s 行情实时，iwencai 10min 情绪准实时，复盘笔记每日基线
- **W20 AI 系统**：DeepSeek V4-Flash → 浮动聊天框 → 15min自动研判+手动问答+3轮对话记忆+后端APScheduler

## API 端点

| 端点 | 方法 | 说明 | 频率 |
|------|------|------|------|
| `/api/baseline` | GET | dashboard_data.json | 60s |
| `/api/live/quotes` | GET | 实时行情(含iwencai/北向/热榜/15minK) | 5s |
| `/api/live/iwencai` | GET | 情绪指标 | 10min |
| `/api/account/state` | GET | 账户SSOT状态(锚点+流水+实时估值) | 实时 |
| `/api/account/correct` | POST | 冲销/纠错一条成交记录 | 随录 |
| `/api/llm` | POST | AI研判(支持mode=auto/manual+question+userMsg) | 实时 |
| `/api/llm/history` | GET | 今日对话历史(v2 conversation) | — |
| `/api/debug/snapshot` | GET | 全盘8域快照(调试) | — |
| `/api/pnl?range=today&index=sh` | GET | PnL曲线 | 5min |
| `/api/pnl/summary` | GET | PnL摘要(SSOT资产+图表元信息) | 实时 |
| `/api/sync` | POST | W15持仓同步(仅事件，拒绝pnl覆盖) | 随录 |
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
| 看板白屏 | bridge 在跑吗？`curl localhost:8088/api/pnl/summary` |
| 情绪数据空/过时 | iwencai 10min 轮询在跑吗？`/api/live/quotes` 有 iwencai 字段吗？ |
| W22 图跳 70%+ | 检查 `day_start_asset` 与 pnl_history.json 是否一致；检查锚点 source 是否为 recovery |
| 竞价面板无数据 | 9:28 过了吗？auction_snapshot.json mtime 今天？ |
| 成交额对比无显示 | `collect_yesterday_compare` 数据被 collect_index 覆盖了？检查 quotes.py 是否用 update |
| LLM 研判不触发 | `~/.claude/settings.json` 有 ANTHROPIC_BASE_URL 和 ANTHROPIC_AUTH_TOKEN 吗？ |
| 清仓跟踪现价空 | 清仓标的代码在 PyTDX 采集列表吗？bridge 重启会重新加载代码列表 |
| 账户资产数据异常 | 检查 `GET /api/account/state` 返回值；`pnl_pct` 来源为锚点+流水+行情，缺行情会降级 |
| 前端 sync 返回 409 | 前端仍在提交 `pnl` 字段，W16 已不允许直接写入资产 |
| 锚点 recovery 日结后未切换 | 检查 `generate_closing_anchor` 日结日志；15:05 收盘 job 是否正常执行 |
| snapshot 偏差告警 | bridge console 出现 `⚠️ SNAPSHOT DEVIATION`；检查 SSOT 总资产 vs 快照总资产偏离是否 >5% |

## 开发原则

1. **先查文档再改**：GridStack、API 签名不确定先查官方文档，不试错
2. **组件独立**：每个 widget 只订阅自己的 dataPaths
3. **零构建**：纯 HTML/CSS/JS，CDN 仅 GridStack.js@12.x
4. **红涨绿跌**：涨跌颜色+符号必须同时使用
5. **内联 CSS**：所有组件用内联样式，优先 CSS 变量
6. **Component extends YiMuWidget**：所有组件继承基类管理生命周期
