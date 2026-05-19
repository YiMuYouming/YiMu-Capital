# 弈沐资本数据看板 v2.1

> 弈沐资本第一个自动化项目。纯组件化交易决策指挥台。
> 启动：`python3 scripts/bridge.py 8088` → Chrome `http://localhost:8088`

## 项目定位

将弈沐资本交易系统 v3.0 的规则体系外化为可视化组件。每个组件对应一个独立决策维度。

**用户**：弈沐哥（杨弈沐），A 股短线+趋势混合交易。
**打开方式**：`file://` 双击 index.html（离线模式），或 `python3 -m http.server` → `localhost:8080`（实时模式）。

## 技术架构

```
live-dashboard/
├── index.html              # 主入口（GridStack v12 画板）
├── store.js                # DataStore 数据中枢（三层合并+订阅发布）
├── widget-base.js          # 组件基类（生命周期+错误隔离）
├── widget-registry.js      # 19 组件注册表
├── widgets/                # 19 个独立组件
│   ├── timeline.js         # W01 时段时间线（7段制，支持?time=HH:MM）
│   ├── style-detect.js     # W02 风格检测卡
│   ├── position-calc.js    # W03 三层仓位计
│   ├── market-overview.js  # W04 市场全景
│   ├── sentiment-dash.js   # W05 情绪仪表盘
│   ├── auction-5d.js       # W06 竞价5维面板
│   ├── climax-guard.js     # W07 高潮保护
│   ├── w1-check.js         # W08 W1早盘确认（实时条件判定）
│   ├── w2-check.js         # W09 W2实时观察（实时条件判定）
│   ├── sector-heat.js      # W10 板块热力图
│   ├── volume-bars.js      # W11 上证15min量价
│   ├── lianban-pool.js     # W12 连板自选池
│   ├── trend-pool.js       # W13 趋势自选池
│   ├── risk-panel.js       # W14 账户风控
│   ├── positions.js        # W15 持仓明细（自动算市值/盈亏）
│   ├── input-panel.js      # W16 报数面板（浮窗模式）
│   ├── today-ops.js        # W17 今日操作
│   ├── anchor-stocks.js    # W18 锚定股状态
│   └── midday-review.js    # W19 午盘复核（V反+双冰）
├── css/theme.css           # 全局主题（阴影4级+紫色高亮+交互四态）
├── data/
│   ├── dashboard_data.json     # Layer 1 基线数据（gen_dashboard_data.py 产出）
│   ├── dashboard_live.json     # Layer 2 实时数据（poll_iwencai.py 产出）
│   └── embedded-data.js        # Layer 0 兜底数据（sync_embedded.py 产出）
├── scripts/
│   ├── gen_dashboard_data.py   # 复盘笔记→JSON（支持--watch）
│   ├── poll_iwencai.py         # iwencai 轮询
│   └── sync_embedded.py        # JSON→兜底JS
├── assets/logo.svg
├── README.md
├── CHANGELOG.md
├── DATA_APPENDIX_FORMAT.md     # 复盘笔记附录格式规范
└── CLAUDE.md                   # 本文件
```

## 数据管线

```
复盘笔记 frontmatter + 数据附录
         ↓
gen_dashboard_data.py
  ├─ 解析 YAML frontmatter → market/sentiment/risk
  ├─ 调用 style_detect.py → style 域
  ├─ 规则引擎 → 实际执行（硬卡/熔断/连亏/周五）
  ├─ 解析数据附录 → positions/pools/sectors/decision
  └─ → dashboard_data.json

2026-05-13: v2.3 三大管线就绪

  === 管线1: 数据采集 ===
  poll_live.py --watch    → dashboard_live.json  (PyTDX 5s: 个股+指数+MA+板块MA5)
  snapshot_auction.py      → auction_snapshot.json (问财竞价5维, 9:25跑)
  gen_dashboard_data.py    → dashboard_data.json   (复盘笔记→基线, 自动回退昨天)

  === 管线2: 规则引擎 ===
  style_detect.py --review → 四维度风格判定+分层晋级率+分配表
  W08/W09 前端实时判定      → 60分钟MA10回踩+缩量+未大跌=🟢买入信号
  store.js 三层合并         → Layer1基线+Layer2实时+Layer3手工

  === 管线3: AI 研判 (ReAct) ===
  W20 llm-monitor.js        → 15min自动触发, 收集全盘快照
  bridge.py POST /api/llm   → DeepSeek V4 Flash (读~/.claude/settings.json)
  → LLM生成结构化研判 [TEXT]+[SIGNALS]
  → _verify_signals() 规则交叉验证 → ✅/⚠️ 标记
  → data/llm_insights.json 持久化
  W10板块卡🤖槽位            → 自动匹配板块名展示最新研判

  === 五节点情绪 ===
  复盘笔记 表1+表2 → gen 解析 → sentiment_nodes → W05矩阵表+W09市场行
  稳米填完节点→面板点🔄刷新→gen重跑→面板更新

## 开发原则

1. **先查文档再改**：GridStack、API 签名不确定时先查官方文档，不试错
2. **组件独立**：每个 widget 只订阅自己的 dataPaths，不跨组件通信
3. **零构建**：纯 HTML/CSS/JS，CDN 仅 GridStack.js@12.x
4. **兼容 file://**：所有数据文件优先用 `<script>` 加载，避免 fetch() CORS
5. **渐进增强**：EMBEDDED_DATA 兜底，外部数据不可用时看板不白屏
6. **字号标准**：结果 15px（`--fs-subtitle`），正文 12px（`--fs-body`），标签 10px（`--fs-label`）
7. **红涨绿跌**：`--up` 仅用于方向数字，`--info/warn/danger` 用于状态判定
8. **CSS 优先**：布局/适配用 CSS 解决，不让 JS 抢 CSS 的活
9. **随时提交**：每个逻辑节点完成后提交（组件调通/bug修复/功能完成），不堆到收工时一次性提交。commit message 写清楚做了什么

## 设计规范（DESIGN.md 精简）

本项目遵循「暖砚」设计系统，完整规范见根目录 `DESIGN.md`。

**CSS 关键规则**：
- 所有 CSS 变量在 `css/theme.css`，不新增冷色变量、不使用 `#000000` 纯黑
- 数字一律用 `JetBrains Mono` 等宽字体，启用 `font-variant-numeric: tabular-nums`
- 圆角用 6-8px（`--radius-md` / `--widget-radius`），不用大圆角
- 涨跌必须同时用颜色 + 符号（`+2.34%` + 红色 / `-1.02%` + 绿色）
- 间距紧凑为主：sp-sm (8px) 是看板基础间距单位
- 阴影用 4 级暖调系统（`--shadow-card/elevated/drag/modal`），不用冷色阴影
- 四个组件类别的色条：决策蓝 `#2563EB` / 数据绿 `#059669` / 风险深红 `#B91C1C` / 工具灰 `#78716C`

**生成新组件时**：
1. 使用 `YiMuWidget` 基类，遵循 mount → render → resize → unmount 生命周期
2. 注册到 `widget-registry.js`，设置正确的 tier（tick/fast/manual/daily）
3. 涨跌数据用 `class="up"/"down"`，KPI 数值用 `class="kpi-value"`
4. 所有内联 style 优先使用 CSS 变量而非硬编码值

## 调通状态

| 组件 | 状态 | 备注 |
|------|------|------|
| W01 时段时间线 | ✅ | 7段制 |
| W02 风格检测卡 | ✅ | V0.3四维度+分层晋级率+分配表 |
| W03 三层仓位计 | ✅ | 读报数总资产联动 |
| W04 市场全景 | ✅ | 含昨日基线 |
| W05 情绪仪表盘 | ✅ | 5节点矩阵表+涨跌⚡实时 |
| W06 竞价5维 | ✅ | 问财快照+THS情绪SSOT |
| W07 高潮保护 | ✅ | 分级保护表 |
| W08 W1早盘确认 | ✅ | 实时条件判定 |
| W09 W2实时观察 | ✅ | 60分钟MA10回踩+🟢买入信号 |
| W10 板块热力 | ✅ | 类型分组+TDX板块数据+LLM槽位 |
| W11 上证15min量价 | ✅ | 三指数+标尺卡 |
| W12 连板自选池 | ✅ | 含MA10(60m)+MA5 |
| W13 趋势自选池 | ✅ | 含MA10(60m)+MA5 |
| W14 账户风控 | ✅ | 实时盈亏联动W15持仓 |
| W15 持仓明细 | ✅ | 记流水+自动算市值/盈亏 |
| W16 报数面板 | ✅ | 浮窗模式 |
| W17 今日操作 | ✅ | 自助录入 |
| W18 锚定股状态 | ✅ | 实时涨幅 |
| W19 午盘复核 | ✅ | V反+双冰 |
| W20 AI盯盘 | ✅ | 15min自动+DeepSeek ReAct验证 |

## 待办

- [ ] 文件归档整理（所有仪表盘文件归到一处）
- [ ] 稳米接入：`gen_dashboard_data.py --watch` 盘中持续运行
- [ ] `poll_iwencai.py` 盘中轮询配置 cron/launchd
- [ ] W10 板块 LLM 槽位接上更多研判上下文

## API 参考 (bridge.py)

bridge.py 在 `http://localhost:8088` 提供以下 API 端点，所有响应均为 `application/json`，带 `Cache-Control: no-cache` 头。

### 基线数据

| 端点 | 方法 | 说明 | 刷新频率 |
|------|------|------|----------|
| `/api/baseline` | GET | dashboard_data.json 全量基线（Layer 1） | 每 60s 重读文件 |
| `/api/pnl?range=today&index=sh` | GET | PnL 曲线数据。range: today/week/month/quarter/year/all，index: sh/sz/cy | 5min（日内）/每日（日级） |
| `/api/pnl/summary` | GET | PnL 摘要：last_nav, daily_count, today_snapshots | 实时 |

### 实时数据（从内存 CACHE 读取，APScheduler 写入）

| 端点 | 方法 | 说明 | 刷新频率 |
|------|------|------|----------|
| `/api/live/quotes` | GET | 全部实时数据：live_index + live_quotes + breadth + sectors + hot_list + northbound + 15min K线 | 5s/30s 混合 |
| `/api/live/iwencai` | GET | 问财情绪指标：涨停收益/连板收益/晋级率/封板率等 | 2min |
| `/api/live/sectors` | GET | 行业板块资金流入数据 | 5min |
| `/api/live/news` | GET | 市场快讯 | 5min |
| `/api/live/stream` | GET | SSE 实时推送（EventSource），5s 间隔推送全量实时数据 | 5s |

### 写入端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/sync` | POST | W15 持仓同步。Body: `{"positions": [...], "今日操作": [...], "pnl": {...}}`。合并写入 dashboard_data.json + pnl.db，使用 filelock 进程安全。 |
| `/api/refresh` | POST | 触发 gen_dashboard_data.py 重跑。Body 可空。 |
| `/api/llm` | POST | AI 盯盘研判。Body: `{"node": "10:00", "data_snapshot": {...}}`。响应含 text（研判文本）+ signals（结构化信号+交叉验证）。结果持久化到 llm_insights.json + pnl.db。 |

所有 `_freshness` 字段：`{level: "live"|"delayed"|"stale"|"dead", type: str, age_seconds: int}`

### pnl.db 表结构

```sql
-- 日内快照（5分钟粒度）
intraday_snapshots (ts TEXT PK, date TEXT, pnl_pct REAL, nav REAL, sh_pct, sz_pct, cy_pct, pos_pct, mv, total_asset)

-- 每日汇总（收盘后写入）
daily_summary (date TEXT PK, nav REAL, pnl_pct REAL, sh_pct, sz_pct, cy_pct, pos_pct, deposit, max_dd, max_dd_start, max_dd_end)

-- 交易记录
trade_records (id INTEGER PK, trade_date TEXT, trade_time TEXT, action TEXT, code, name, price, qty, window, reason, realized_pnl, fee)

-- AI 研判
llm_insights (id INTEGER PK, date TEXT, node TEXT, text TEXT, signals_json TEXT, verified INTEGER, warnings INTEGER)
```

### 故障排查

| 症状 | 排查步骤 |
|------|----------|
| 看板白屏 | 1. 检查 bridge.py 是否运行 2. 检查 data/ 目录 JSON 文件完整性 3. 浏览器 console 查看 fetch 错误 |
| 数据不更新 | 1. 检查 APScheduler job 日志（stdout）2. 检查 data/dashboard_live.json mtime 3. 检查 CACHE dump 是否正常 |
| SQLite 报错 | 1. 确认 WAL 模式已开启 2. 确认 threading.local() 每线程独立连接 3. 检查 pnl.db 文件权限 |
| 文件写入冲突 | file_utils.py 的 FileLock 会在 `.lock` 文件残留时自动超时（5s），删除 `.lock` 文件可手动解锁 |
| LLM 研判不触发 | 1. 确认 `~/.claude/settings.json` 中 ANTHROPIC_BASE_URL 和 ANTHROPIC_AUTH_TOKEN 已配置 2. 检查 bridge.py 日志中的 LLM error |

## 会话上下文

- 独立 Git 仓库：`live-dashboard/.git`，60+ commits
- 启动命令：`python3 scripts/bridge.py 8088` → `http://localhost:8088`
- PRD v2.0：`00_Capture/Planning/弈沐资本数据看板_PRD_v2.0.md`
- PRD v1.0（含四方针审阅）：`00_Capture/Planning/弈沐资本数据看板_PRD_v1.0.md`
- 复盘笔记：`复盘笔记/W19_第19周/2026_5_8_Friday_ReviewNote.md`（已加数据附录）
- 模板：`templates/daily-review-template.md`（已更新数据附录格式）
- 关联规则文件：`trading-core.md`、`Core-连板.md`、`Core-趋势.md`、`references/`、`rules/`
