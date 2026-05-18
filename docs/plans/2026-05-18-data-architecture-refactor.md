# live-dashboard 数据架构重构 实施计划 v2

**目标：** 建立数据获取优先级体系（T1实时→T2阶段→T3计算→T4人工），统一 SSOT，消除多源竞态，让复盘笔记回归策略记录本职。

**架构：** SQLite（结构化 SSOT）+ JSON（文档型数据）+ bridge.py（统一入口 + APScheduler）+ 前端 API 化。不换技术栈。

**技术栈：** Python http.server + SQLite + APScheduler + SSE + YM-data-pipeline + 原生 JS

**审计依据：** 洋米架构审计 v1 + 稳米管线审计 v1 + 代码审计 v1 + 管线实测 v1（四份报告交叉验证）

---

## 零、数据获取优先级（宪法级）

重构后所有数据字段按此优先级获取，不可降级使用低优先级源当高优先级源可用时：

```
T1 实时自动获取（秒级）          ← PyTDX / 系统时钟 / 内存缓存
  ↓ 不可用时降级
T2 阶段自动获取（分钟/小时/日级） ← iwencai / ths_hot / northbound / sector_inflow
  ↓ 不可用时降级
T3 实时计算可得                  ← 从 T1+T2 纯逻辑推导
  ↓ 不可用时降级
T4 复盘笔记 / 人工录入           ← 最后手段，仅策略决策类字段
```

**核心原则：能实时获取的永不靠人填，能计算的永不靠文件传。**

### 当前 72 个仪表盘字段的自动化分级

| 层级 | 数量 | 来源 | 示例 |
|------|------|------|------|
| T1 | ~20 | PyTDX 5s | 行情/指数/涨跌家数/板块/15min量价/MA |
| T2 | ~18 | iwencai/ths_hot/northbound/sector_inflow | 情绪值/涨停收益/封板率/晋级率/北向/热榜 |
| T3 | ~12 | 从 T1+T2 计算 | 情绪区间/赚钱效应/浮盈/信号灯/规则引擎 |
| T4 | ~12 | 人工决策 | 风格检测/自选池构成/交易记录/持仓成本 |

### 复牌笔记 frontmatter 瘦身

**当前（30+ 字段）：** 涨停家数、跌停家数、炸板率、封板率、情绪值、上证指数、市场量能、最高板、赚钱效应、昨日涨停收益、连板风险值……大部分 T1/T2 已覆盖。

**目标（~12 字段，仅 T4）：**
```yaml
---
date: 2026-05-18
weekday: 周一
盘后持仓: 北方华创100股@572.26 + 领益智造3000股@16.82
风格分数验证: "偏连板"          # T4 人工校验 style_detect
熔断触发: false                # T4 人工确认
当日盈亏: +0.5%                 # T4 人工校验 vs T3 计算
W1状态: 开放                    # T4 策略决策
W2状态: 开放                    # T4 策略决策
---
```
所有 T1/T2 字段（涨停家数、情绪值、上证指数……）从 frontmatter 移除，改由管线实时填充。

---

## 一、现状架构图

```
┌──────────────────────────────────────────────────────────────────────┐
│                         当前数据架构（76/100）                          │
│                                                                      │
│  数据入口:  复盘笔记.md(30+字段)    YiMu.xlsx    ~/.claude/settings     │
│                   │                    │               │              │
│                   ▼                    ▼               ▼              │
│  脚本层:   gen_dashboard_data.py   backfill x3    bridge.py           │
│           + style_detect.py        (P&L重复)     (HTTP+写+AI)          │
│                   │                    │               │              │
│  采集层:   poll_live 1663行上帝脚本   poll_iwencai   snapshot_auction  │
│            PyTDX/东方财富/easyquot      问财API        问财API(重叠)    │
│                   │                    │               │              │
│  存储层:   dashboard_data.json    pnl.db(4表)   auction_snapshot.json │
│            dashboard_live.json    llm_insights.json  (4种格式无统一入口)│
│                   │                                               │
│  前端层:   store.js 三层暴力合并 → 22 Widget 消费                     │
│           多源竞态补丁 · 无新鲜度 · thundering herd轮询                │
│                                                                      │
│  启动: 3种(手动+--watch+launchd×2) · 硬编码8处 · .bak残留18个(22%)    │
└──────────────────────────────────────────────────────────────────────┘
```

### 已确认核心问题（三份报告一致）

**P0-1：poll_live.py 1663 行上帝脚本**
一个文件做行情采集+指标计算+持久化写入+缓存管理+板块扫描，拆成 4-5 个模块是当务之急。

**P0-2：情绪值三源竞态**
复盘笔记 → 手工录入 → 涨跌家数反推，同一字段三个写入源。store.js 已有"防旧缓存覆盖"补丁承认了设计缺陷。

**P0-3：板块数据假实时**
东方财富 API 境外 IP 被封，回退昨天基线。W10 仍以 30s 频率刷新——用户以为看实时，实际看昨天。

**P0-4：多 SSOT 双写不一致**
bridge.py 同时写 JSON 和 SQLite，gen 脚本覆盖 bridge 写入。同一份数据两条路径两份存储。

**P0-5：数据无新鲜度标记**
三天前的 auction_snapshot 照样展示，竞价快照过期无感知。任何组件不检查数据时间戳。

**P1-1：三份 P&L 计算代码重复**
import / backfill_history / backfill_intraday 独立实现相同逻辑，硬编码 `CURRENT_TOTAL = 206075`。代码审计发现 backfill_intraday 写死 nav=1.0，backfill_history 只算 realized PnL。

**P1-2：死代码 + 功能重叠**
poll_iwencai.py 有 100+ 行占位函数（watch_mode / fetch_live_* / build_live_data）。snapshot_auction 和 poll_iwencai --auction 两条竞价管线写不同文件，数据可能不一致。

**P1-3：多进程并发写 dashboard_data.json 无文件锁**
bridge / gen / poll_iwencai 可能同时写，非原子 `json.dump + open('w')`。bridge.py POST /api/sync 既写 JSON 又写 SQLite，两件事不是原子的。

**P2-1：18 个 .bak 残留文件（占 22%）**
Git 历史都有记录，完全多余。分布在 data/ scripts/ widgets/ 根目录。

**P2-2：前端 thundering herd 轮询**
10 个 tick 组件独立 setInterval，5s 内同一文件 fetch 多次。无缓存层，无节流。

**P2-3：YM-data-pipeline 半僵尸**
poll_live.py 的 import 静默 fallback，从未真正工作。已裁决：集成，改用 `fetch()`。

**P2-4：SSOT 溯源覆盖率仅 10/50+**
store.js `getSSOT()` 大部分返回 "—"。40+ 个 dataPath 无法溯源。

**P2-5：bridge.py 无认证 + CORS `*`**
`/api/refresh` 可无认证触发 subprocess，`/api/llm` 可无认证消耗 DeepSeek 额度。本地 localhost 低风险，Phase 3 加 token 验证。

**P2-6：db.py 每次查询创建新连接**
低影响但非最佳实践。Python sqlite3 没有连接池，频繁创建/销毁连接在 5s 轮询频率下是不必要的开销。

### 数据管线停运状态（审计时 → 当前已恢复 ✅）

截至审计时间 2026-05-18 09:15 / 当前状态：
| 文件 | 审计时 | 当前 |
|------|--------|------|
| dashboard_live.json | May 15 ❌ | ✅ 实时更新中 |
| pnl.db | May 15 ❌ | ✅ poll_live 写入中 |
| auction_snapshot.json | May 13 ❌ | ✅ 当天已抓取 |
| poll_live.py | 未运行 ❌ | ✅ PID 12660 运行中 |

### 评审历史

| 评审者 | 日期 | 核心意见 |
|--------|------|---------|
| 洋米（架构审计） | 05-18 | 混合存储 + APScheduler + SSE，不换栈 |
| 稳米（管线审计） | 05-18 | 上帝脚本拆分 + 三源竞态 + 假实时修复 |
| 代码审计 | 05-18 | 补充 8 项遗漏 + 4 处不精确 + P&L 重复 |
| 黑米（独立审计） | 05-18 | schema contract 前置 + bridge 膨胀防护 + 分批验证约束 |

---

## 二、目标架构图（全量 ASCII）

```
┌──────────────────────────────────────────────────────────────────────┐
│                     目标数据架构（Phase 2 完成后）                       │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │                    数据获取优先级                               │    │
│  │                                                              │    │
│  │  T1 实时(PyTDX)    T2 阶段(iwencai/同花顺)   T3 计算           │    │
│  │  行情/指数/板块     情绪/晋级率/封板率/       情绪区间/浮盈/     │    │
│  │  涨跌分布/MA        北向/热榜/主力净流入      信号灯/规则引擎    │    │
│  │       │                   │                    │              │    │
│  │       └───────────────────┼────────────────────┘              │    │
│  │                           │ 自动填充                            │    │
│  │                           ▼                                    │    │
│  │  ┌────────────────────────────────────────────────────────┐   │    │
│  │  │               bridge.py 内存缓存 + SQLite                │   │    │
│  │  │   APScheduler 统一调度: 5s/30s/300s/9:25/8:30          │   │    │
│  │  └────────────────────────────────────────────────────────┘   │    │
│  │                           │                                    │    │
│  │  T4 人工 — 复盘笔记（仅策略决策字段）                           │    │
│  │  自选池构成 / 风格校验 / 交易记录 / 持仓成本                    │    │
│  │       │                                                       │    │
│  │       ▼                                                       │    │
│  │  ┌────────────────────────────────────────────────────────┐   │    │
│  │  │  gen_baseline.py（角色变更：数据校验者，非数据生产者）    │   │    │
│  │  │  - 读 T1/T2 已有数据 → 校验一致性 → 写 baseline.json    │   │    │
│  │  │  - 读 附录A → 写 pools.json                            │   │    │
│  │  │  - 不再从 frontmatter 首次写入 T1/T2 字段               │   │    │
│  │  └────────────────────────────────────────────────────────┘   │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │                      存储层                                    │    │
│  │                                                              │    │
│  │  pnl.db (SQLite)          data/dashboard_cache/ (JSON)       │    │
│  │  intraday / daily         baseline / pools                   │    │
│  │  trades / llm             sentiment_auto / auction / llm     │    │
│  │  positions / pools 🆕                                       │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │                      前端层                                    │    │
│  │                                                              │    │
│  │  store.js (重构)           22 Widget (不变)                   │    │
│  │  Layer0 兜底 → Layer1 API  Layer2 SSE  Layer3 localStorage   │    │
│  │  每字段 _freshness + 节流   过期灰显 + 黄点 + "N分钟前"        │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  启动: 1种(python3 bridge.py 8088) · 路径: config统一 · .bak: 0     │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 三、各组件数据源映射（目标架构，带自动化层级）

| 数据域 | 自动化层级 | SSOT | API | 刷新 | 消费组件 |
|--------|----------|------|-----|------|---------|
| 实时行情（最新价/涨幅/量比/换手/MA） | **T1** | 内存→SQLite | SSE stream | 5s | W04 W08 W09 W10 W12 W13 W14 W15 W18 W21 W22 |
| 实时指数（上证/深证/创业/涨跌家数/成交额） | **T1** | 内存→SQLite | SSE stream | 5s | W04 W08 W09 W11 |
| 涨跌分布（10档+涨停跌停数） | **T1** | 内存 | GET /api/live/quotes | 30s | W04 W05 W21 |
| 板块实时（涨跌幅/MA5/20/方向/成交额趋势） | **T1** | 内存 | GET /api/live/quotes | 30s | W10 |
| 15min 量价（三指数） | **T1** | 内存 | GET /api/live/quotes | 5min | W11 |
| 时段/窗口/周五 | **T1** | 系统时钟 | new Date() | 实时 | W01 |
| 情绪值/情绪区间 | **T3 主 / T2 校验** | 内存 | SSE / GET /api/live | 5s/2min | W05 W07 W08 W09 |
| 涨停收益/连板收益/炸板收益 | **T2** | iwencai→内存 | GET /api/live/quotes | 2min | W05 W06 W08 W09 |
| 封板率/炸板率/晋级率（含分层） | **T2** | iwencai→内存 | GET /api/live/quotes | 2min | W02 W05 W08 |
| 最高板/次高板/连板风险值 | **T2** | iwencai→内存 | GET /api/live/quotes | 2min | W05 W07 W08 |
| 赚钱效应 | **T3 主 / T2 校验** | 内存 | GET /api/live/quotes | 2min | W05 W08 W19 |
| 北向资金（分钟级） | **T2** | northbound→内存 | GET /api/live/quotes | 60s | W04（新增） |
| 板块主力净流入 TOP20 | **T2** | sector_inflow→内存 | GET /api/live/quotes | 5min | W10 |
| 同花顺热榜+题材归因+涨停详情 | **T2** | ths_hot→内存 | GET /api/live/quotes | 5min | W21 |
| 竞价快照（全量） | **T2** | auction_snapshot.json | GET /api/live/quotes | 9:25 | W06 |
| 情绪节点（5节点×15指标） | **T2 自动快照 / T4 校验** | sentiment_auto.json | GET /api/baseline | 30min | W05 W08 |
| 风格检测（总分/占比/四维度/总仓位上限） | **T4** | baseline.json | GET /api/baseline | 盘前 | W02 W03 W08 |
| 自选池（连板+趋势+锚定+板块+不碰） | **T4** | pools.json | GET /api/pools | 盘前 | W06 W08 W09 W10 W12 W13 W18 |
| 持仓明细（成本/数量/状态） | **T4** | pnl.db positions | GET /api/baseline | 盘前+sync | W03 W14 W15 W17 W22 |
| 风控基线（熔断声明/当日盈亏声明/W1W2状态） | **T4** | baseline.json | GET /api/baseline | 盘前 | W03 W14 |
| 今日操作 | **T4** | pnl.db trades | GET /api/trades | sync | W15 W17 |
| P&L 历史（NAV链/收益曲线） | **T3 计算 / T2 存储** | pnl.db | GET /api/pnl/:range | 按需 | W22 |
| LLM 研判 | **T2** | llm_insights.json+pnl.db | POST /api/llm | 15min | W08 W10 W20 W21 |
| 手工录入（总资产/可用资金） | **T4** | localStorage | W16→manualData | 随录 | W03 W14 W15 W16 W17 |

### 数据新鲜度规则

| 数据类型 | live | delayed | stale | dead |
|---------|------|---------|-------|------|
| T1 行情 | <15s | 15-60s | 1-5min | >5min |
| T2 iwencai | <3min | 3-10min | 10-30min | >30min |
| T2 竞价快照 | 今日9:25-10:00 | 今日10:00-15:00 | 今日15:00+ | 非今日 |
| T4 复盘基线 | 今日盘前更新 | 今日未更新(用昨天) | 2天前 | >2天 |
| LLM研判 | <20min | 20-60min | >1h | 非今日 |

---

## 四、分阶段执行计划

### 前置准备：YM-data-pipeline 实测验证（已完成 ✅）

> 15 个数据类型全部通过实测（2026-05-18 11:43）。结论：管道可用，直接集成，不维护僵尸 import。

| 类型 | 延迟 | 关键字段 | 仪表盘用途 |
|------|------|---------|----------|
| `index` | 1.0s | 三指数+涨跌家数+成交额 | W04 W08 W09 W11 |
| `quotes` | 1.6s | 最新价/涨幅/量比/换手/MA | W04 W08 W09 W10 W12 W13 W14 W15 W18 W21 W22 |
| `breadth` | 4.2s | 全市场十档分布 | W04 W05 W21 |
| `sector_index` | ~0.5s | 板块涨跌幅/MA5/20/方向 | W10 |
| `iwencai` | 1.4-2.4s | 任意 A 股字段 | T2 情绪/晋级率/竞价 |
| `ths_hot` | 0.43s | 83只热点+题材归因 | W21 |
| `northbound` | 0.88s | 262分钟点北向 | W04（新增） |
| `sector_inflow` | 3.03s | 50行业净流入 | W10（替代东财） |
| `dragon_tiger` | 0.61s | 112条龙虎榜 | 盘后 |
| `news` | 0.29s | 20条财联社电报 | 盘前 |

---

### Phase 0：止血（P0，预计 2-3 天）

> **开工前置 sign-off：**
> 1. `pools.json` schema — 连板池/趋势池/锚定股/板块/不碰，字段名+类型+必填项
> 2. `baseline.json` vs `pools.json` 边界 — baseline 不含池子，pools 不重复 market/sentiment
> 3. 三源自选池优先级：`pools.json` > `auction_snapshot.json`（仅竞价时段） > `localStorage`
> 4. YM-data-pipeline 裁决：**集成**。poll_live.py 改用 `fetch()` 替代内联 PyTDX 调用（不再静默 import）
> 5. gen_dashboard_data.py 角色变更：从"数据生产者"变为"数据校验者"，T1/T2 已覆盖的字段不再从 frontmatter 首次写入

#### 任务 0.1：清理死代码和备份残留
> 6. **codes 参数格式对齐**：`fetch("quotes", codes=["002979"])` 的 codes 与 pools.json `代码` 字段对齐（不含交易所后缀），在 collectors/quotes.py 内部转换；pools.json schema 的 key 名必须和 store.js merge()/getSSOT() 引用完全一致，不能有大小写或中文标点差异。

**文件：**
- 修改: `scripts/poll_iwencai.py` — 删除 `watch_mode`/`fetch_live_index`/`fetch_live_quotes`/`fetch_live_sectors`/`build_live_data`（~120 行死代码）
- 删除: 18 个 `.bak` + `.new` 文件

**步骤：**
1. 定位死代码：`grep -rn "def watch_mode\|def fetch_live_index\|def fetch_live_quotes\|def fetch_live_sectors\|def build_live_data" scripts/poll_iwencai.py`
2. 删除死函数，保留 `auction_mode()` 和 `review_mode()`
3. 清理备份：`find . -name "*.bak" -o -name "*.new" | xargs rm`
4. 验证：`wc -l scripts/poll_iwencai.py` 从 ~500 行减到 ~380 行

**验证：** `python3 scripts/poll_iwencai.py --auction` 正常运行；`--review` 正常运行

---

#### 任务 0.2：情绪值三源竞态修复（store.js 优先级调整）

**问题：** 情绪值同时来自复盘笔记（T4）+ 手工录入（T4）+ 涨跌家数反推（T3），store.js 已有"防旧缓存覆盖"补丁。

**修复：** 改为 T3 主源 → T2 iwencai 校验 → T4 手工覆盖。

**文件：** 修改 `store.js` — merge() 函数中情绪值部分

**步骤 1：重写情绪值优先级**
```javascript
// store.js merge() — 替换现有情绪值逻辑
var autoEmotion = null;

// T3 优先：实时涨跌家数比
var up = parseInt(manualData['上涨']) || d.live_index?.上涨家数 || 0;
var dn = parseInt(manualData['下跌']) || d.live_index?.下跌家数 || 0;
if (up + dn > 0) {
    autoEmotion = Math.round(up / (up + dn) * 100);
}

// T2 校验：iwencai 情绪值（来自 liveData）
var iwencaiEmotion = d._iwencai_情绪值 || d.sentiment?._iwencai_情绪值;

// T4 覆盖：仅当手工明确录入时覆盖（不是旧缓存）
var manualEmotion = manualData['情绪值'] || '';
var isManualOverride = manualEmotion && manualData['_情绪值_手动覆盖'] === 'true';

// 优先级：T4 手工覆盖 > T3 实时计算 > T2 iwencai
var finalEmotion = isManualOverride ? parseFloat(manualEmotion)
    : autoEmotion != null ? autoEmotion
    : iwencaiEmotion != null ? iwencaiEmotion
    : d.sentiment?.情绪值 || 0;

d.sentiment = d.sentiment || {};
d.sentiment['情绪值'] = finalEmotion;
d.sentiment['情绪区间'] = finalEmotion < 20 ? '冰点' : finalEmotion < 40 ? '低迷'
    : finalEmotion < 60 ? '主升' : finalEmotion < 80 ? '强势' : '高潮';
```

**步骤 2：W16 增加手动覆盖开关**
```html
<!-- input-panel.js — 情绪值输入框旁加 checkbox -->
<input type="checkbox" id="in_情绪值_手动覆盖"> 手动覆盖自动计算
```

**验证：** 启动看板 → 情绪值随涨跌家数自动变化 → 手工录入并勾选手动覆盖 → 情绪值锁定为手工值 → 取消勾选 → 恢复自动计算

**验证补充：** 记录 T3→T2→T4 fallback 次数（store.js merge() 中添加 `console.log("[emotion] source:", source)` ），等 0.7+1.1 全部上线后验证 T2 iwencai 数据确实接管了主源。

---

#### 任务 0.3：复盘笔记 SSOT 解耦（pools.json + frontmatter 瘦身）

**文件：**
- 新建: `data/pools.json` — 自选池 SSOT
- 修改: `scripts/gen_dashboard_data.py` — 解析附录A 替代数据附录；T1/T2 字段不再从 frontmatter 首次写入
- 修改: `scripts/snapshot_auction.py` — `get_pool_codes()` 优先读 pools.json

**步骤 1：pools.json schema**
```json
{
  "version": 1,
  "updated": "2026-05-18T08:30:00+08:00",
  "source": "复盘笔记 附录A",
  "lianban_pool": [
    {"标的": "雷赛智能", "代码": "002979", "板块": "机器人", "窗口": "W1", "角色": "W1候选", "操作": "竞价确认"}
  ],
  "trend_pool": [
    {"标的": "北方华创", "代码": "002371", "板块": "半导体", "角色": "主趋势股", "操作": "持有"}
  ],
  "anchor_stocks": [
    {"标的": "大唐发电", "代码": "601991", "状态": "反包涨停", "灯": "green"}
  ],
  "sectors": [
    {"板块": "机器人", "类型": "主线候选", "状态": "🔥"}
  ],
  "excluded": ["蒙娜丽莎", "澜起科技", "德明利"]
}
```

**步骤 2：gen 脚本新增 `parse_appendix_a()` — 解析"附录A：次日盘前速查"**
- 解析"连板板块→操作映射"表 → lianban_pool
- 解析"趋势板块→操作映射"表 → trend_pool
- 解析"不碰"行 → excluded
- 解析"观察"行 → 补充到 pools

**步骤 3：gen 脚本角色变更 — T1/T2 字段不再从 frontmatter 写入**
```python
# gen_dashboard_data.py build_dashboard_data()
# 修改前：fm_val("涨停家数")  # T4 frontmatter 作为主源
# 修改后：保留现有 liveData 中的值，frontmatter 仅做收盘后校验覆盖
if fm.get("涨停家数"):
    data["market"]["涨停家数_人工校验"] = fm_val("涨停家数")
    # 不再覆盖 data["market"]["涨停家数"]（该值由 T1 breadth 实时填入）
```

**步骤 4：复盘笔记模板更新 — 移除 T1/T2 字段**
```yaml
# 修改前（30+ 字段）
涨停家数: 72
跌停家数: 44
炸板率: 41.30%
情绪值: 32%
上证指数: 4135.39
# ... 20+ 机器可获取字段

# 修改后（~12 字段，仅 T4）
盘后持仓: 北方华创100股@572.26 + 领益智造3000股@16.82
风格分数验证: "偏连板"
熔断触发: false
当日盈亏: +0.5%
W1状态: 开放
W2状态: 开放
```

**验证：** `python3 scripts/gen_dashboard_data.py` → pools.json 标的与附录A一致（不含蒙娜丽莎） → dashboard_data.json 中 T1/T2 字段不由 frontmatter 填充

---

#### 任务 0.4：原子写入 + bridge 双写事务化

**文件：**
- 修改: `scripts/gen_dashboard_data.py` — 写入改为 `tmp + os.replace()`
- 修改: `scripts/bridge.py` — `POST /api/sync` 的 JSON+SQLite 写入改为事务性

**步骤 1：gen 原子写入**
```python
tmp = OUTPUT_FILE.with_suffix('.tmp')
with open(tmp, 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
os.replace(tmp, OUTPUT_FILE)
```

**步骤 2：bridge sync 事务化**
```python
try:
    insert_trade(...)  # SQLite 事务保护
    with open(tmp, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)
except Exception:
    db.rollback()
    raise
```

**验证：** 并发测试：`gen & bridge sync &` → 不出现文件损坏

---

#### 任务 0.5：db.py 连接复用（共享底座）

**目标：** Phase 1 多个任务（1.3 APScheduler / 1.5 P&L 合并）都涉及 db 操作。先把 db.py 改成模块级连接复用，避免并行修改冲突。

**文件：** 修改 `scripts/db.py`

**步骤：**
```python
# db.py — 模块级连接，替代每次 _exec() 创建新连接
import sqlite3
_conn = None

def get_conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH)
        _conn.row_factory = sqlite3.Row
    return _conn
```

**验证：** `python3 -c "from scripts.db import get_conn; assert get_conn() is get_conn()"` → 两次调用返回同一连接

---

#### 任务 0.6：竞价管线合并（snapshot_auction + poll_iwencai --auction）

**目标：** 两条竞价管线功能重叠。合并到 `snapshot_auction.py`，统一 iwencai 查询参数和输出格式。

**文件：**
- 修改: `scripts/snapshot_auction.py` — 合并 poll_iwencai auction_mode() 的 `_judge_auction()` 高潮保护判定规则
- 修改: `scripts/poll_iwencai.py` — 移除 `auction_mode()`（合并后废弃）
- 修改: `scripts/bridge.py` APScheduler — 9:25 job 改为调用合并后的 snapshot_auction

**步骤 1：合并 _judge_auction() 到 snapshot_auction**
```python
# snapshot_auction.py — 新增
def _judge_auction(snap):
    """高潮保护判定（从 poll_iwencai.py 迁入）"""
    emotion = float(snap.get("情绪指标", {}).get("情绪值", "0").replace("%", ""))
    if emotion >= 90: return "一级高潮保护"
    elif emotion >= 85: return "二级高潮保护"
    elif emotion >= 80: return "三级高潮保护"
    return "正常"
```

**步骤 2：统一 iwencai 查询参数**
两条管线用了不同的 iwencai 查询语句，合并后统一使用 snapshot_auction.py 的查询（已验证通过）。

**验证：** `python3 scripts/snapshot_auction.py` → auction_snapshot.json 包含高潮保护字段 → `python3 scripts/poll_iwencai.py --auction` 报错/移除

---

#### 任务 0.7：数据新鲜度标记


**文件：** 修改 `scripts/bridge.py` `store.js` `widget-base.js`

**步骤 1：bridge.py `_add_freshness()` 辅助函数** — 所有 GET API 响应附加 `_freshness` 字段（live/delayed/stale/dead）

**步骤 2：store.js merge() 保留 `_freshness`**

**步骤 3：widget-base.js updateTimestamp() 读取 `_freshness`** — 过期组件灰显

**验证：** `curl /api/pnl` → 含 `_freshness` → 前端过期显示灰显

---

### Phase 1：自动化（P1，预计 1-2 周）

> 核心目标：把 T1/T2 能覆盖的字段全部自动化，消除人工填写。

#### 任务 1.1：T2 情绪数据自动采集（iwencai 每 2min 轮询）

**目标：** 涨停收益/连板收益/炸板收益/封板率/炸板率/晋级率/最高板/连板风险值/赚钱效应 — 9 个字段全部从 iwencai 自动获取，不再依赖复盘笔记。

**文件：**
- 新建: `scripts/collectors/iwencai_poll.py` — iwencai 定时轮询模块
- 修改: `scripts/bridge.py` — APScheduler 注册 2min iwencai job

**步骤 1：iwencai 轮询函数**
```python
# collectors/iwencai_poll.py
def poll_iwencai_sentiment():
    """每2分钟查询一次 iwencai 情绪数据，写入内存缓存"""
    from ym_stock_data.sources.iwencai import query
    results = {}
    # dim2 查询：涨停收益/连板收益/炸板收益/封板率/炸板率/晋级率/连板风险值/最高板
    r = query("涨停收益 连板收益 炸板收益 封板率 炸板率 晋级率 最高板 连板风险值", limit=10)
    # dim4 查询：赚钱效应
    r2 = query("赚钱效应 全市场成交额", limit=10)
    # ... 解析并返回标准化 dict
    return results
```


**步骤 2：非交易时段守卫**
```python
# collectors/iwencai_poll.py
from datetime import datetime, time

def is_trading_time():
    now = datetime.now()
    if now.weekday() >= 5: return False
    t = now.time()
    return (time(9, 25) <= t <= time(11, 30)) or (time(13, 0) <= t <= time(15, 2))

def poll_iwencai_sentiment():
    if not is_trading_time():
        return
    # ... 正常查询逻辑
```
**步骤 3：APScheduler 注册**
```python
scheduler.add_job(poll_iwencai_sentiment, 'interval', minutes=2)
```

**验证：** 启动 bridge → 2min 后内存缓存有 T2 情绪数据 → W05 W08 显示值不再为空 → 断开 iwencai → 降级到 T3 计算/T4 复盘笔记

---

#### 任务 1.2：5 节点情绪矩阵 30min 自动快照

**目标：** 替代稳米手工填表 1+表 2。每 30 分钟自动 snapshot 当前涨跌家数/情绪值/涨停收益等 → `sentiment_auto.json`。

**文件：**
- 新建: `scripts/collectors/sentiment_snapshot.py` — 30min 快照
- 修改: `scripts/bridge.py` — APScheduler 注册

**步骤 1：快照函数**
```python
def take_sentiment_snapshot():
    node_names = {900: '早盘', 1030: '午盘前', 1130: '午盘', 1300: '下午', 1400: '尾盘', 1500: '收盘'}
    # 取当前最近的节点名
    snap = {
        'time': datetime.now().isoformat(),
        'node': current_node,
        '情绪值': live_cache['sentiment']['情绪值'],
        '上证涨幅': live_cache['index']['上证指数涨幅'],
        '涨停家数': live_cache['breadth']['涨停'],
        '跌停家数': live_cache['breadth']['跌停'],
        '涨停收益': live_cache['iwencai']['涨停收益'],
        '炸板率': live_cache['iwencai']['炸板率'],
        '晋级率': live_cache['iwencai']['晋级率'],
        '最高板': live_cache['iwencai']['最高板'],
        '赚钱效应': live_cache['iwencai']['赚钱效应'],
    }
    # append 到 sentiment_auto.json
    # 保留最近 90 天记录（约 1000 条），每季度归档一次
    snapshots = load_snapshots()[-1260:]  # 90天×14条/天
    snapshots.append(snap)
    save_snapshots(snapshots)
```

**步骤 3：APScheduler 注册**
```python
scheduler.add_job(take_sentiment_snapshot, 'cron', minute='0,30')
```

**验证：** 盘中 → sentiment_auto.json 每 30min 新增一条 → W05 情绪节点展示自动快照数据 → 稳米不再需要手工填写表 1+表 2

---

#### 任务 1.3：APScheduler 统一入口（替代 --watch + launchd）

**目标：** 一个 `python3 scripts/bridge.py 8088` 启动全部。

**文件：**
- 新建: `scripts/collectors/__init__.py`
- 新建: `scripts/collectors/quotes.py` — 从 poll_live.py 提取 QuoteCollector 类（行情/指数/板块/宽度/15min，~400行）
- 修改: `scripts/bridge.py` — 集成 APScheduler + 内存缓存

**步骤 1：从 poll_live.py 提取采集逻辑到 collectors/**
```python
# collectors/quotes.py
class QuoteCollector:
    def fetch_quotes(self, codes): ...     # ~200行
    def fetch_index(self): ...             # ~100行
    def fetch_sectors(self): ...           # ~150行
    def fetch_breadth(self): ...           # ~150行
    def fetch_15min_bars(self): ...        # ~120行
```

**步骤 2：bridge.py 调度注册**
```python
from apscheduler.schedulers.background import BackgroundScheduler
scheduler = BackgroundScheduler()
scheduler.add_job(collect_quotes, 'interval', seconds=5)
scheduler.add_job(collect_sectors, 'interval', seconds=30)
scheduler.add_job(collect_breadth, 'interval', seconds=30)
scheduler.add_job(log_pnl_snapshot, 'interval', seconds=300)
scheduler.add_job(poll_iwencai_sentiment, 'interval', minutes=2)
scheduler.add_job(take_sentiment_snapshot, 'cron', minute='0,30')
scheduler.add_job(snapshot_auction, 'cron', hour=9, minute=25)
scheduler.add_job(gen_baseline, 'cron', hour=8, minute=30)
scheduler.start()
```

**步骤 3：集成 YM-data-pipeline `fetch()` 替代内联 PyTDX**
```python
# collectors/quotes.py — 改用管道标准化接口
from ym_stock_data.fetch import fetch as pipeline_fetch

def fetch_quotes(codes):
    return pipeline_fetch("quotes", codes=codes)
def fetch_index():
    return pipeline_fetch("index")
# ... 所有采集函数统一走 pipeline
```

**步骤 4：废弃项**
- 废弃 `poll_live.py --watch`（保留脚本文件为历史参考）
- 废弃 `launchd com.yimu.auction-snapshot`
- 废弃 `poll_iwencai.py --auction` 的竞价部分（合并到 snapshot_auction）

**验证：** `python3 scripts/bridge.py 8088` 一个命令 → 5s 后内存缓存有数据 → 9:25 自动竞价 → 8:30 自动基线

**验证补充：** 连续运行 10 分钟 → `grep "PyTDX|breadth" /tmp/bridge.log` → 检查 4.18s breadth 采集是否在下一个 5s 轮次排队 → 无请求堆积 → 确认 APScheduler 7 job 并发无冲突

---

#### 任务 1.4：板块主力净流入接入（替代东财 push2）

**目标：** 东方财富 push2 境外被封，W10 板块显示空数据。改用 `sector_inflow`（同花顺行业，实测 3.03s 返回 50 行业净流入）。

**文件：**
- 修改: `scripts/collectors/quotes.py` — 新增 `fetch_sector_inflow()`
- 修改: `scripts/bridge.py` — APScheduler 注册（每 5min）

**步骤 1：采集函数**
```python
def fetch_sector_inflow():
    from ym_stock_data.fetch import fetch
    return fetch("sector_inflow", top_n=20)
```

**步骤 2：W10 读取新字段**
**步骤 1.5：store.js merge() 注册 sector_inflow 路径（如尚未注册）**
```javascript
// store.js merge() — 确认 liveData.sector_inflow → d.sector_inflow 路径存在
if (liveData.sector_inflow) { d.sector_inflow = liveData.sector_inflow; }
```
**步骤 1.6：news（财联社电报）接入 W20 LLM 研判** — 采集的实时新闻作为 DeepSeek prompt 的附加上下文，提升研判质量。
```javascript
// sector-heat.js render()
var inflow = data.sector_inflow || {};
// 匹配板块名 → 显示 net_inflow_yi
```

**验证：** W10 板块卡片显示主力净流入数据（不再为空） → 境外 IP 可用（同花顺源）

---

#### 任务 1.5：合并 P&L 计算 + 修复 NAV bug（与 1.3 并行）

**文件：**
- 新建: `scripts/pnl_calc.py`
- 修改: `scripts/import_xlsx_pnl.py` `scripts/backfill_history.py` `scripts/backfill_intraday.py`
- 修改: `scripts/db.py` — 连接复用

**步骤 1：提取公共逻辑 + 修复 NAV**
```python
# pnl_calc.py
def parse_yimu_xlsx(path): ...
def build_position_timeline(trades): ...
def calc_pnl_for_date(date, positions, quotes): ...
def calc_nav_chain(snapshots):  # 统一连乘，修复 backfill_intraday 的 nav=1.0
```

**步骤 2：三脚本改为薄壳（500+ → 200 行）**
**步骤 3：db.py 连接复用（顺便改）**

**验证：** 输出与重构前一致 → NAV 不再全是 1.0

---

#### 任务 1.6：前端 API 化 + SSE 推送（可并行）

**文件：**
- 修改: `store.js` — adapter 改为调用 API + SSE
- 修改: `scripts/bridge.py` — 新增 SSE endpoint

**步骤 1：store.js adapter API 化**
```javascript
adapter: {
    fetchBase: function() {
        if (location.protocol === 'file:') return Promise.resolve(EMBEDDED_DATA);
        return fetch('/api/baseline').then(r => r.json());
    },
    fetchLive: function() {
        return fetch('/api/live/quotes').then(r => r.json());
    }
}
```

**步骤 2：SSE endpoint + 前端 EventSource（降级到 fetch 轮询）**

**验证：** http://localhost:8088 正常 → file:// 正常（降级） → Network 面板显示 SSE stream

---


#### Phase 1 冒烟测试（手动点检清单）

**目标：** Phase 1 所有任务完成后，确认 22 个 Widget 全部正常渲染。

**步骤：**
1. 启动 bridge → 打开浏览器 → 逐个检查 22 Widget
2. 重点检查：W10 板块净流入非空 / W05 情绪值自动更新 / W06 竞价快照
3. 任意组件出现 "—" → 打开 Console → 查 DataStore 日志 → 定位缺失 dataPath

**验证：** 22 Widget 全部通过 → 进入 Phase 2

---
### Phase 2：优化（P2，预计 2-4 周）


#### 任务 2.1：SSE 替代行情轮询

**目标：** 前端不再每 5s fetch 轮询 dashboard_live.json。改用 SSE 推送，消除 thundering herd。

**文件：**
- 修改: `scripts/bridge.py` — 新增 GET /api/live/stream SSE endpoint
- 修改: `store.js` — 新增 SSEClient，fallback 到 fetch 轮询

**步骤 1：bridge.py SSE endpoint**
```python
elif parsed.path == '/api/live/stream':
    self.send_response(200)
    self.send_header('Content-Type', 'text/event-stream')
    self.send_header('Cache-Control', 'no-cache')
    self.send_header('Connection', 'keep-alive')
    self.end_headers()
    # 注册到 server.live_clients
    self.server.live_clients.append(self)
    while True:
        time.sleep(5)
        # server.live_cache 由 APScheduler 更新，这里只管推送
        if self.server.live_cache:
            data = json.dumps(self.server.live_cache, ensure_ascii=False)
            self.wfile.write(f"data: {data}\n\n".encode())
            self.wfile.flush()
```

**步骤 2：前端 EventSource + 降级**
```javascript
// store.js
function connectSSE() {
    var es = new EventSource('/api/live/stream');
    es.onmessage = function(e) {
        var live = JSON.parse(e.data);
        liveData = live;
        merge();
        notifyAll();
    };
    es.onerror = function() {
        // 降级到 5s fetch 轮询
        startPollingFallback();
    };
}
```

**验证：** 浏览器 Network 面板显示 text/event-stream → 无多余 fetch 轮询请求 → 断开网络 → 自动降级到轮询

---

#### 任务 2.2：数据源降级链显式配置

**目标：** 将当前 try/except 隐式降级改为 YAML 显式配置，降级事件可追踪。

**文件：**
- 新建: `config/sources.yaml`
- 修改: `scripts/collectors/quotes.py` — 读取配置执行降级

**步骤：**
```yaml
# config/sources.yaml
quotes:
  primary:
    name: pytdx
    module: collectors.pytdx
    timeout: 3s
  fallback:
    - name: easyquotation
      module: collectors.easyquotation
      timeout: 5s

sectors:
  primary:
    name: pytdx_880xxx
    module: collectors.pytdx
  fallback:
    - name: baseline_json
      module: collectors.baseline_fallback

breadth:
  primary:
    name: pytdx
    module: collectors.pytdx
  fallback:
    - name: baseline_fallback

auction:
  primary:
    name: iwencai
    module: collectors.iwencai
  max_staleness: 1h

iwencai_sentiment:
  primary:
    name: iwencai
    module: collectors.iwencai
  max_staleness: 10min
  fallback:
    - name: baseline_fallback
```

**验证：** 停掉 PyTDX → bridge 自动切 easyquotation → 日志输出降级事件 → 前端显示数据源降级标记

---

#### 任务 2.3：前端过期数据可视化

**目标：** 每个组件根据 `_freshness` 字段显示数据状态（绿点/黄点动画/红点）。

**文件：**
- 修改: `css/theme.css` — 新增 `.freshness-dot` 样式
- 修改: `widget-base.js` — updateTimestamp() 加新鲜度 UI

**步骤：**
```css
/* theme.css */
.freshness-dot {
    display: inline-block; width: 6px; height: 6px;
    border-radius: 50%; margin-right: 4px;
}
.freshness-dot--live { background: var(--down); }
.freshness-dot--delayed { background: var(--warn); animation: pulse 2s infinite; }
.freshness-dot--stale { background: var(--danger); }
.timestamp--stale { color: var(--text-disabled); }
.timestamp--stale::after { content: " 历史数据"; font-size: var(--fs-micro); }

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}
```

**验证：** 看板实时组件显示绿点 → 断 poll_live 30s → 变黄点 → 5min → 变红点

---

#### 任务 2.4：北向资金 W04 接入 + ths_hot W21 集成

**目标：** 新增实时北向资金展示；W21 涨停梯队集成同花顺热榜题材归因。

**文件：**
- 修改: `widgets/market-overview.js` — W04 新增北向资金行（累计净买入+趋势+分钟图）
- 修改: `widgets/zt-echelon.js` — W21 读取 `data.hot_list.reason_stats`（已在 live 数据中）

**步骤 1：W04 北向资金行**
```javascript
// market-overview.js render()
var nb = data.northbound || {};
if (nb.hgt_yi != null) {
    var nbCls = nb.trend === '净流入' ? 'up' : 'down';
    html += '<div class="market-row">' +
        '<span>北向资金</span>' +
        '<span class="' + nbCls + '">' + nb.hgt_yi + '亿</span>' +
        '</div>';
}
```

**步骤 2：W21 题材归因**
```javascript
// zt-echelon.js — 已有 hot_list 读取路径，确认 reason_stats 正确渲染
var reasonStats = data.hot_list?.reason_stats || {};
// 按频次排序展示题材标签
```

**验证：** W04 显示北向资金实时累计 → W21 涨停列表有题材标签

---

### Phase 3：加固（P3，持续）

#### 任务 3.1：pytest 测试框架

**文件：**
- 新建: `tests/test_gen_baseline.py` — gen 脚本解析测试（用 fixture 笔记验证输出）
- 新建: `tests/test_pnl_calc.py` — P&L 计算测试（NAV 链 / 回撤 / 日收益率）
- 新建: `tests/test_api.py` — bridge API 测试（/api/pnl / /api/live / /api/sync）
- 新建: `tests/fixtures/sample_review_note.md` — 测试用复盘笔记

**步骤 1：test_gen_baseline**
```python
def test_parse_frontmatter():
    fm = parse_frontmatter("tests/fixtures/sample_review_note.md")
    assert fm["date"] == "2026-05-18"
    assert fm["盘后持仓"] is not None

def test_appendix_a_parsing():
    pools = parse_appendix_a("tests/fixtures/sample_review_note.md")
    assert len(pools["lianban_pool"]) > 0
    assert "蒙娜丽莎" in pools["excluded"]
```

**步骤 2：test_pnl_calc**
```python
def test_nav_chain():
    snaps = [{"pnl_pct": 1.0}, {"pnl_pct": -0.5}, {"pnl_pct": 2.0}]
    navs = calc_nav_chain(snaps, base_nav=1.0)
    assert navs == [1.0, 1.01, 0.995, 1.015]  # 连乘验证
```

**验证：** `pytest tests/` → 全部通过

---

#### 任务 3.2：SSOT 溯源 100% 覆盖

**文件：** 修改 `store.js` — getSSOT() 补充剩余 40+ dataPath

**步骤：**
```javascript
getSSOT: function(path) {
    var map = {
        // T1
        'live_index.*':      { source: 'PyTDX → collectors/quotes.py → 内存缓存', freq: '5s', owner: 'bridge APScheduler' },
        'live_quotes.*':     { source: 'PyTDX → collectors/quotes.py → 内存缓存', freq: '5s', owner: 'bridge APScheduler' },
        'live_sectors.*':    { source: 'PyTDX 880xxx → collectors/quotes.py', freq: '30s', owner: 'bridge APScheduler' },
        'live_breadth.*':    { source: 'PyTDX 全市场扫描 → collectors/quotes.py', freq: '30s', owner: 'bridge APScheduler' },
        // T2
        'sentiment.情绪值':   { source: 'T3实时计算(主) / T2 iwencai(校验) / T4 复盘笔记(覆盖)', freq: '5s/2min/每日', owner: 'store.js + collectors/iwencai_poll.py' },
        'sentiment.涨停收益':  { source: 'iwencai 2min轮询 → 内存缓存', freq: '2min', owner: 'collectors/iwencai_poll.py' },
        'sentiment.晋级率':    { source: 'iwencai 2min轮询 → 内存缓存', freq: '2min', owner: 'collectors/iwencai_poll.py' },
        'northbound.*':       { source: '同花顺 hsgtApi → collectors/quotes.py', freq: '60s', owner: 'bridge APScheduler' },
        'sector_inflow.*':    { source: '同花顺行业 → collectors/quotes.py', freq: '5min', owner: 'bridge APScheduler' },
        'hot_list.*':         { source: '同花顺热点 → collectors/quotes.py', freq: '5min', owner: 'bridge APScheduler' },
        // T3
        'sentiment.情绪区间':  { source: 'T3计算: 情绪值阈值判定', freq: '实时', owner: 'store.js merge()' },
        'sentiment.赚钱效应':  { source: 'T3计算: 涨停收益阈值', freq: '实时', owner: 'store.js merge()' },
        // T4
        'style.*':            { source: 'style_detect.py → baseline.json', freq: '每日盘前', owner: '稳米 + gen_baseline.py' },
        'lianban_pool.*':     { source: '复盘笔记附录A → pools.json', freq: '每日盘前', owner: '稳米 + gen_baseline.py' },
        'trend_pool.*':       { source: '复盘笔记附录A → pools.json', freq: '每日盘前', owner: '稳米 + gen_baseline.py' },
        'positions.*':        { source: 'W16手工/W15记流水 → pnl.db + localStorage', freq: '随录', owner: '弈沐哥' },
        // ... 覆盖全部 50+ dataPath
    };
    return map[path] || { source: '— (未映射，需补充)', freq: '—', owner: '—' };
}
```

**验证：** `DataStore.getSSOT('sentiment.情绪值')` 返回完整三源信息 → 所有路径不再返回 "—"

---

#### 任务 3.3：迁移验证自动化

**目标：** 并行验证期（Phase 1）内每天自动对比 SQLite + pools.json + baseline.json + auction_snapshot 的一致性。不只比 NAV。

**文件：** 新建 `scripts/diff_check.py`

**步骤：**
```python
# scripts/diff_check.py — 四项检查
def diff_all():
    issues = []
    # 1. NAV 对比：SQLite daily_summary.nav vs baseline.json pnl.总资产（差异>1%告警）
    # 2. pools 对比：pools.json 标的列表 vs 当天附录A（检查 excluded 列表无遗漏）
    # 3. 情绪值对比：iwencai 轮询缓存 vs baseline.json sentiment.情绪值（偏差<5%）
    # 4. 竞价快照时效：auction_snapshot.json fetched 日期必须是今天
    for label, ok in checks:
        if not ok:
            issues.append(f"[ALERT] {label}")
    if issues:
        print("\n".join(issues))
```

**验证：** `python3 scripts/diff_check.py` → 无 ALERT 输出 → 四项检查全部通过
```

**验证：** `python3 scripts/diff_check.py` → 无 ALERT 输出 → 数据一致

---

## 五、风险矩阵

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| poll_live 拆分引入行情采集 bug | 中 | 高 | 双轨运行 2 周，每天 diff 新旧数据 |
| iwencai 每 2min 轮询耗尽 API 配额 | 低 | 中 | 5000次/15min，2min间隔够用 3.5天连续；非交易时段暂停 |
| APScheduler 阻塞 HTTP 服务 | 低 | 中 | BackgroundScheduler 独立线程 |
| SSE 浏览器不兼容 | 低 | 低 | 自动降级到 fetch 轮询 |
| 复盘笔记格式变更致 gen 解析失败 | 中 | 中 | Pydantic schema 验证 + 告警 |
| bridge.py 膨胀成第二个上帝脚本 | 中 | 高 | 硬拆 collectors/ + bridge.py，上限 1000 行 |
| 并行验证期无限延长 | 中 | 中 | 2 周截止，每天自动 diff SQLite vs JSON |
| 情绪值 T3 计算在极端行情下偏差大 | 低 | 低 | T2 iwencai 校验 + T4 人工可覆盖 |

---

## 六、禁止事项

1. **不引入 FastAPI/Flask** — http.server 251 行够用
2. **不引入 Celery/Redis** — 单用户场景不需要
3. **不引入 DuckDB/InfluxDB** — 结构化走 SQLite，文档型留 JSON
4. **不删除 file:// 降级路径** — 离线模式必须保留
5. **不一次性全迁 SQLite** — 分批复用，并行验证 2 周
6. **不改组件渲染逻辑** — 22 Widget 接口不变。adapter 改造后每个组件手动点检
7. **bridge.py ≤ 1000 行** — 采集逻辑拆到 `collectors/`（~400 行），bridge 只保留 API+SSE+调度（~600 行）
8. **文档型数据不迁 SQLite** — 情绪节点/决策树/LLM 研判保留 JSON
9. **T1/T2 能覆盖的字段不从复盘笔记首次写入** — gen 脚本角色变更为校验者
