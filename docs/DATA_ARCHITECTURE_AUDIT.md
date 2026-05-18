# 弈沐资本 live-dashboard 数据架构审计与重构方案

> 审计日期：2026-05-18 | 审计范围：22 组件 + 10 脚本 + 7 数据文件 + 1 SQLite 库
> 审计方法：3 个 Agent 并行 — 组件依赖 / 数据管线 / 最佳实践调研

---

## 一、现状诊断：核心问题

### 问题 1：多 SSOT 双写不一致

```
同一份数据 → 两条写入路径 → 两份存储

bridge.py POST /api/sync
  ├── → 写 dashboard_data.json（文件）
  └── → 写 pnl.db trade_records（SQLite）

gen_dashboard_data.py
  └── → 写 dashboard_data.json（覆盖 bridge 写入的 positions）
```

**后果**：W16 手工录入的持仓可能被 gen 脚本覆盖；JSON 文件和 SQLite 可能不同步。

### 问题 2：数据无新鲜度标记

所有组件读数据时**不检查时效**。5 天前的竞价快照照样展示，2 小时前的行情不提示过期，用户看不出数据是实盘还是历史。

### 问题 3：三个松耦合管线没有统一入口

```
管线 A: gen_dashboard_data.py     → dashboard_data.json     (复盘基线，手动跑)
管线 B: poll_live.py              → dashboard_live.json     (实时行情，--watch)
管线 C: snapshot_auction.py       → auction_snapshot.json   (竞价快照，launchd)
管线 D: poll_iwencai.py --auction → dashboard_data.json     (竞价研判，launchd)
管线 E: bridge.py                 → pnl.db                  (HTTP桥接，手动启)
```

5 个进程，3 种启动方式（手动 / --watch / launchd），没有健康检查。哪个挂了用户不知道。

### 问题 4：复盘笔记「数据附录」vs「附录A」分裂

- **附录A**（次日盘前速查）：红方对抗定稿，真正的次日计划
- **数据附录**（机器解析区）：复盘全量数据，包含已被排除的标的（蒙娜丽莎）

gen 脚本读数据附录 → 看板展示已被排除的标的 → 用户困惑。

### 问题 5：数据源降级是隐式的

PyTDX 挂了 -> 东方财富 -> 问财 -> Layer0 兜底。但这个链是 `try/except` 嵌套的，没有显式配置，出问题时不知道降到了哪一层。

---

## 二、现状全貌

### 2.1 数据存储矩阵

| 存储 | 类型 | 用途 | 写入者 | 读取者 |
|------|------|------|--------|--------|
| dashboard_data.json | JSON | Layer1 基线 | gen_dashboard_data, bridge/sync | store.js, poll脚本 |
| dashboard_live.json | JSON | Layer2 实时 | poll_live.py | store.js |
| auction_snapshot.json | JSON | 竞价快照 | snapshot_auction.py | W06 组件 |
| embedded-data.js | JS | Layer0 兜底 | sync_embedded.py | store.js (file://) |
| pnl.db | SQLite | P&L+交易+LLM | poll_live, bridge, backfill | bridge API |
| llm_insights.json | JSON | LLM研判 | bridge POST /api/llm | W08/W10/W20/W21 |

### 2.2 组件数据依赖密度（22 组件）

| 依赖级别 | 组件 | 特点 |
|---------|------|------|
| **重依赖** (>10 dataPaths) | W08, W09, W10, W14, W20, W22 | 跨多个数据域读取 |
| **中依赖** (3-10) | W02, W03, W04, W05, W06, W12, W13, W15, W18, W21 | 主数据域 + live_quotes |
| **轻依赖** (0-2) | W01, W07, W11, W16, W17, W19 | 时钟/手工/静态 |

### 2.3 数据域交叉引用热力图

```
              sentiment style market risk positions pools live_* decision manualData
W02 风格卡       —       ★     —     —      —       —     —       —        —
W03 仓位计       —       ★     —     ★      ★       —     —       —        ★
W04 市场全景     —       —     ★     —      —       —     ★       —        —
W05 情绪仪表     ★       —     —     —      —       —     ★       —        —
W06 竞价5维      ★       ★     ★     —      —       —     —       —        —
W08 W1确认       ★       —     ★     —      —       ★     ★       —        —
W09 W2确认       ★       —     —     —      —       ★     ★       —        —
W10 板块热力     —       —     —     —      —       ★     ★       —        —
W12 连板池       —       —     —     —      —       ★     ★       —        —
W13 趋势池       —       —     —     —      —       ★     ★       —        —
W14 账户风控     —       —     —     ★      ★       —     ★       —        ★
W15 持仓明细     —       —     —     —      ★       —     ★       —        ★
W16 报数面板     —       —     —     —      —       —     —       —        ★(读写)
W22 P&L曲线      —       —     —     —      ★       —     ★       —        —
```

★ = 该组件的主要数据依赖

### 2.4 刷新层级现状

| Tier | 频率 | 组件数 | 组件 |
|------|------|--------|------|
| tick | 5s | 10 | W03,W04,W08,W09,W12,W13,W14,W15,W18,W21 |
| fast | 30s | 2 | W10,W22 |
| slow | 停用 | 2 | W01,W11 |
| manual | 按需 | 7 | W05,W06,W07,W16,W17,W19,W20 |
| daily | 按需 | 1 | W02 |

---

## 三、重构方案

### 3.1 目标架构

```
                        ┌─────────────────────────────┐
                        │        pnl.db (SQLite)        │
                        │  唯一 SSOT — 所有结构化数据     │
                        │                              │
                        │  intraday_snapshots (已有)     │
                        │  daily_summary (已有)          │
                        │  trade_records (已有)          │
                        │  llm_insights (已有)           │
                        │  🆕 positions                 │
                        │  🆕 watchlist_pools           │
                        │  🆕 review_baseline           │
                        │  🆕 sentiment_snapshots       │
                        └──────────┬──────────────────┘
                                   │
                        ┌──────────▼──────────────────┐
                        │      bridge.py (统一入口)     │
                        │  端口 8088，一个进程启动全部    │
                        │                              │
                        │  /api/live/quotes    (REST)  │
                        │  /api/live/stream    (SSE)   │
                        │  /api/baseline       (REST)  │
                        │  /api/pnl/:range     (REST)  │
                        │  /api/pools          (REST)  │
                        │  /api/sync           (POST)  │
                        │  /api/llm            (POST)  │
                        │                              │
                        │  内嵌 APScheduler：           │
                        │  - 每5s: 采集行情→内存→SQLite │
                        │  - 每30s: 采集板块/宽度      │
                        │  - 9:25: 竞价快照            │
                        │  - 8:30: 盘前基线刷新        │
                        └──────────┬──────────────────┘
                                   │
                        ┌──────────▼──────────────────┐
                        │    前端 store.js (重构)       │
                        │                              │
                        │  Layer 0: embedded-data.js   │
                        │  Layer 1: GET /api/baseline  │
                        │  Layer 2: SSE /api/live/stream│
                        │  Layer 3: manualData (不变)  │
                        │                              │
                        │  每个数据字段附带 _freshness: │
                        │  live | delayed | stale | dead│
                        └──────────────────────────────┘
```

### 3.2 关键设计决策

#### 决策 1：SQLite 作为唯一 SSOT

**选 SQLite，不选 DuckDB/InfluxDB/纯文件。**

| 方案 | 为什么行/不行 |
|------|-------------|
| SQLite ✅ | 已有 4 张表在跑；零依赖；单文件备份；schema 约束 |
| DuckDB ❌ | OLAP 引擎，强在百万行聚合，你的查询是点查用不上 |
| InfluxDB ❌ | 高吞吐时序写入（10k+/s），你每秒 1 条快照，过度设计 |
| 纯 JSON ❌ | 当前问题根源——无 schema、双写、无原子性 |

**迁移策略**：分 3 批，不一次性全迁。

```
Phase 1 (本文执行)：新增 4 张表 + API 层
  ├── CREATE TABLE positions (...)
  ├── CREATE TABLE watchlist_pools (...)
  ├── CREATE TABLE review_baseline (...)
  └── CREATE TABLE sentiment_snapshots (...)

Phase 2 (并行运行)：bridge API 同时读 SQLite 和 JSON
  └── 2 周对比期，确认数据一致

Phase 3 (切换)：前端改从 API 读，JSON 文件降级为备份
```

#### 决策 2：SSE 替代行情轮询

**选 SSE，不选 WebSocket。**

| 方案 | 适用性 |
|------|--------|
| SSE ✅ | 单向推送（服务器→前端）；EventSource 自带重连；HTTP 兼容 |
| WebSocket ❌ | 双向通信用不上；额外连接管理；可能被代理阻断 |
| 轮询（现状）| 保留作为 SSE 断开时的降级 |

改动量：bridge.py 加 ~30 行 SSE endpoint，前端改 EventSource。

#### 决策 3：APScheduler 替代手动 --watch

不引入 Celery（需要 Redis 消息队列，单用户场景纯属浪费）。

```python
# bridge.py 启动时自动注册
scheduler.add_job(采集行情, 'interval', seconds=5)
scheduler.add_job(采集板块, 'interval', seconds=30)
scheduler.add_job(竞价快照, 'cron', hour=9, minute=25)
scheduler.add_job(盘前基线, 'cron', hour=8, minute=30)
```

一个 `python3 scripts/bridge.py 8088` 启动全部。

#### 决策 4：复盘笔记保留 YAML + 数据附录，但 SSOT 迁移到 SQLite

- 笔记格式不变（仍是人类可读的主文档）
- gen_dashboard_data.py 解析完 → **写入 SQLite**（而非 JSON 文件）
- 数据附录改名 `## 次日自选池`（明确这是机器读的次日计划，不是复盘全量）
- 红方对抗定稿后 → 稳米更新次日自选池 → gen 读到 SQLite → 前端展示

#### 决策 5：数据新鲜度四级体系

每个 API 响应附带 `_freshness` 字段：

| 级别 | 条件示例 | 前端表现 |
|------|---------|---------|
| `live` | 行情 < 10s 前 | 正常 |
| `delayed` | 行情 10-30s | 黄点 + "15s前" |
| `stale` | 行情 > 5min，竞价 > 1h | 灰显 + "历史数据" |
| `dead` | 源不可用 > 1天 | 显示"—"，降级 Layer0 |

### 3.3 数据源显式降级链

```yaml
# config/sources.yaml（新文件）
quotes:
  primary: pytdx
  fallback: [eastmoney_http, easyquotation]
  timeout_per_source: 3s

auction:
  primary: iwencai
  fallback: null
  max_staleness: 1h  # 竞价数据 >1小时过期

baseline:
  primary: review_note  # 复盘笔记
  fallback: yesterday_note
```

---

## 四、实施路线图

### P0：立即执行（本周）

| 任务 | 文件 | 工作量 |
|------|------|--------|
| 数据新鲜度标记 | bridge.py + store.js + 各组件 | 中 |
| Pydantic schema 验证 gen 解析 | gen_dashboard_data.py | 小 |
| 复盘笔记 SSOT 解耦（pools_ssoT.json 过渡方案） | 新增文件 + gen 改造 | 中 |

### P1：架构统一（1-2 周）

| 任务 | 文件 | 工作量 |
|------|------|--------|
| SQLite 新增 4 张表 + 迁移脚本 | db.py + migration script | 中 |
| bridge API 统一从 SQLite 读 | bridge.py | 大 |
| APScheduler 替代 --watch + launchd | bridge.py | 中 |
| 前端 fetch API 替代 JSON 文件加载 | store.js + index.html | 大 |

### P2：体验优化（2-4 周）

| 任务 | 文件 | 工作量 |
|------|------|--------|
| SSE 替代行情轮询 | bridge.py + store.js | 小 |
| 数据源降级链显式配置 | config/sources.yaml | 小 |
| 前端过期可视化（黄点/灰显） | 各组件 CSS | 中 |

### P3：可靠性加固（持续）

| 任务 | 文件 | 工作量 |
|------|------|--------|
| pytest 测试（解析/写入/API） | tests/ | 中 |
| 复盘解析结果 SQLite 历史查询 | db.py + gen | 中 |

---

## 五、风险与约束

- **file:// 离线模式**：迁到 API 后，离线模式需保留 embedded-data.js 降级路径
- **bridge.py 重启**：当前 ~400 行，改造后 ~800 行，需保持可读性
- **稳米工作流**：数据附录改名 + 红方对抗后更新流程需稳米配合
- **不可逆操作**：JSON → SQLite 迁移先并行验证 2 周再切

---

> 结论：现有架构 90% 合理。核心问题不是选错技术栈，而是缺少数据新鲜度检测、Schema 验证、和统一 SSOT。SQLite + SSE + APScheduler 三个渐进式改进可覆盖所有痛点，不需要推翻重来。
