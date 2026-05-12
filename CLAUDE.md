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

2026-05-11: 实时数据管线 v2.0 上线
  poll_live.py (NEW) → dashboard_live.json  (PyTDX TCP, 5s个股+指数)
  poll_iwencai.py → 盘后复盘查询 (--review: 热榜/龙虎榜/连板生态)
  store.js tick(5s)+fast(30s) 已恢复
  已知限制: 东方财富板块API境外IP受限(rc=102), 板块实时数据回退Layer 1基线
  详细计划: docs/plans/2026-05-11-实时数据管线v2.md

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

## 调通状态

| 组件 | 状态 | 备注 |
|------|------|------|
| W01 时段时间线 | ✅ 完成 | 7段制，?time=HH:MM 调试 |
| W02 风格检测卡 | ✅ 完成 | 规则引擎自动判定 |
| W03 三层仓位计 | ✅ 完成 | 读报数总资产联动 |
| W04 市场全景 | ✅ 完成 | 含昨日收盘基线 |
| W05 情绪仪表盘 | ✅ 完成 | 13 KPI 卡片 |
| W06 竞价5维 | ✅ 完成 | 上下分区卡片布局 |
| W07 高潮保护 | ✅ 完成 | 分级保护表 |
| W08 W1早盘确认 | ✅ 完成 | 实时条件判定+3股票观察 |
| W09 W2实时观察 | ✅ 完成 | 实时条件判定+3股票观察 |
| W10 板块热力 | ⏳ 待调 | |
| W11 上证15min量价 | ⏳ 待调 | |
| W12 连板自选池 | ⏳ 待调 | |
| W13 趋势自选池 | ⏳ 待调 | |
| W14 账户风控 | ✅ 完成 | 进度条+盈亏金额 |
| W15 持仓明细 | ✅ 完成 | 自动算市值/盈亏/仓位 |
| W16 报数面板 | ✅ 完成 | 浮窗模式，顶栏一键 |
| W17 今日操作 | ⏳ 待调 | 改自助录入 |
| W18 锚定股状态 | ⏳ 待调 | |
| W19 午盘复核 | ✅ 完成 | V反+双冰 |

## 待办（明天继续）

- [ ] W10-W13、W17-W18 调通样式和数据
- [ ] 实时条件判定补全（W08/W09 已做，剩余条件需要 AI Hook）
- [ ] 稳米接入：`gen_dashboard_data.py --watch` 盘中持续运行
- [ ] `poll_iwencai.py` 盘中轮询配置 cron/launchd
- [ ] 实盘数据验证：HTTP 方式 + 稳米管线跑通

## 会话上下文

- 独立 Git 仓库：`live-dashboard/.git`，60+ commits
- 启动命令：`python3 scripts/bridge.py 8088` → `http://localhost:8088`
- PRD v2.0：`00_Capture/Planning/弈沐资本数据看板_PRD_v2.0.md`
- PRD v1.0（含四方针审阅）：`00_Capture/Planning/弈沐资本数据看板_PRD_v1.0.md`
- 复盘笔记：`复盘笔记/W19_第19周/2026_5_8_Friday_ReviewNote.md`（已加数据附录）
- 模板：`templates/daily-review-template.md`（已更新数据附录格式）
- 关联规则文件：`trading-core.md`、`Core-连板.md`、`Core-趋势.md`、`references/`、`rules/`
