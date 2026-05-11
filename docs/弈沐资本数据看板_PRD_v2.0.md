# 弈沐资本数据看板 PRD v2.0

> **文档类型**：产品需求文档（PRD）—— 项目唯一 SSOT
> **版本**：v2.0
> **日期**：2026-05-10
> **作者**：洋米（Claude Code）
> **评审方**：弈沐哥 / 洋米（Claude Code）/ 黑米（Cursor）/ 稳米（WorkBuddy）/ 紫米（Hermes）
> **状态**：正式施工蓝图 —— 四方评审已通过，可进入实施

---

## 目录

1. [产品概述](#1-产品概述)
2. [用户与场景](#2-用户与场景)
3. [功能需求——组件目录](#3-功能需求组件目录)
4. [数据架构](#4-数据架构)
5. [UI/UX 规范](#5-uiux-规范)
6. [技术架构](#6-技术架构)
7. [实施计划](#7-实施计划)
8. [验收标准](#8-验收标准)
9. [附录](#9-附录)
10. [开工前检查清单](#10-开工前检查清单)

---

## 1. 产品概述

### 1.1 产品定位

弈沐资本数据看板是一套**模块化、可自由拼装的交易决策指挥台**。它将弈沐资本交易系统 v3.0 的规则体系、数据管线、决策流程外化为可视化组件，每个组件对应交易系统的一个独立决策维度或数据视图。

### 1.2 核心价值

| 痛点（当前） | 解决方案（本产品） |
|------------|-----------------|
| 单一 HTML 文件 1081 行，模块耦合 | 16 个独立 Widget，松耦合，可单独开发/测试/替换 |
| 布局固定，不同时段看同一套 | 自由拖拽缩放，4 套预设一键切换（盘前/W1/W2/复盘） |
| 数据逻辑混在渲染代码里 | DataStore 统一管理，组件只订阅自己需要的数据路径 |
| 无法按需组合（连板日不需要趋势池） | 右键菜单添加/删除组件，看什么加什么 |
| 数据来源不透明 | 每个数字可追溯到 SSOT（复盘笔记/iwencai/手工录入） |

### 1.3 设计原则

1. **交易模式外化**：每个组件名直接对应交易系统概念（竞价5维、W1/W2、三层仓位），看板即模型
2. **数据溯源**：任何数字都能回答"从哪来、多久更新、谁负责"
3. **决策优先**：决策类组件（回答问题）排在数据类组件（展示数据）之前
4. **零构建**：双击 HTML 即开，CDN 引入 GridStack.js@12.x，不依赖 Node.js/npm
5. **渐进可用**：即使后端数据源全部不可用，EMBEDDED_DATA 兜底，看板不白屏
6. **信息优先级——5 秒规则**：用户打开看板 5 秒内，必须能判断今日交易信号好坏。组件排列按决策链而非类型分组：风格检测 → 风控 → 仓位 → 大盘 → 情绪（[紫米评审 §1.2](#紫米评审摘要)，已采纳）

---

## 2. 用户与场景

### 2.1 用户画像

**唯一用户**：弈沐哥（杨弈沐），弈沐资本唯一交易决策者。

特征：
- A 股短线 + 趋势混合交易
- 每日流程：盘前准备(8:30-9:15) → 竞价(9:25) → W1早盘(9:30-10:00) → 盘中观察(10:00-14:00) → W2尾盘(14:00-14:45) → 收盘复盘
- 数据输入方式：复盘笔记（稳米生成）、iwencai API 轮询（自动）、同花顺 APP 手工录入（15 字段）
- 技术环境：Mac 本地，Chrome 浏览器，双击 HTML 打开
- 常见分屏场景：同花顺（左半屏 ~960px）+ 看板（右半屏 ~960px）

### 2.2 使用场景

| 场景 | 时段 | 核心需求 | 推荐预设 |
|------|------|---------|---------|
| 盘前准备 | 8:30-9:15 | 5秒内看到今日风格分数 + 总仓位上限 + 风控状态 | `pre-market` |
| 竞价判断 | 9:25 | 竞价5维面板 + 高潮保护 | `pre-market`（滚动到竞价区） |
| W1 追涨 | 9:30-10:00 | 连板池 + W1早盘确认 + 情绪KPI | `w1-chase` |
| 盘中观察 | 10:00-13:00 | 板块热力 + 上证15min量价 + 市场全景 | `w1-chase`（自由调整） |
| W2 低吸 | 14:00-14:45 | 趋势池 + W2低吸+午盘复核 + 板块热力 | `w2-dip` |
| 收盘复盘 | 15:00后 | 全部数据回顾 + 报数面板录入 | `closing-review` |

### 2.3 用户故事

- **US1**：盘前 8:30 打开看板 → 5 秒内看到风格分数(左上角) + 总仓位上限 + 风控状态 → 心里有数今天做什么
- **US2**：9:25 竞价结束 → 竞价5维全绿（4/5 方向确认）→ 按 `w1-chase` 预设一键切换到 W1 布局 → 连板池就位
- **US3**：盘中觉得板块热力太小 → 拖拽右下角放大到 12×6 → 8 板块一览无余
- **US4**：14:00 转 W2 → 切 `w2-dip` 预设 → 趋势池 + W2条件+午盘复核就位 → 连板池自动隐藏
- **US5**：收盘复盘 → 切 `closing-review` → 报数面板展开 → 填 15 字段 → 刷新 → 数据存入 localStorage

---

## 3. 功能需求——组件目录

每个组件独立开发、独立数据订阅、独立刷新周期。共 16 个组件，分为 4 类。

### 3.1 组件总览

| ID | 组件名 | 类型 | 标签 | 默认尺寸(w×h) | 刷新层级 | 优先级 |
|----|--------|------|------|--------------|---------|--------|
| W01 | 时段时间线 | 工具 | `timeline` | 12×0.5 | 60s | P0 |
| W02 | 风格检测卡 | 决策 | `style-detect` | 4×4 | manual | P0 |
| W03 | 三层仓位计 | 决策 | `position-calc` | 4×4 | realtime | P0 |
| W04 | 市场全景 | 数据 | `market-overview` | 6×3 | 30s | P0 |
| W05 | 情绪仪表盘 | 数据 | `sentiment-dash` | 6×4 | manual | P0 |
| W06 | 竞价5维面板 | 决策 | `auction-5d` | 8×5 | 9:25一次 | P1 |
| W07 | 高潮保护 | 决策 | `climax-guard` | 3×2 | 9:25一次 | P1 |
| W08 | W1早盘确认 | 决策 | `w1-check` | 4×3 | 9:30-10:00 | P1 |
| W09 | W2低吸+午盘复核 | 决策 | `w2-check` | 4×5 | 10:00-14:45 | P1 |
| W10 | 板块热力图 | 数据 | `sector-heat` | 6×5 | 60s | P1 |
| W11 | 上证15min量价 | 数据 | `volume-bars` | 8×3 | 5min | P1 |
| W12 | 连板自选池 | 数据 | `lianban-pool` | 12×4 | 15s | P1 |
| W13 | 趋势自选池 | 数据 | `trend-pool` | 12×4 | 15s | P1 |
| W14 | 账户风控 | 风控 | `risk-panel` | 4×4 | realtime | P0 |
| W15 | 持仓明细 | 风控 | `positions` | 4×3 | realtime | P0 |
| W16 | 报数面板 | 工具 | `input-panel` | 12×2 | manual | P1 |

> **v2.0 变更**：W01 尺寸 12×1→12×0.5（5秒规则）；W09 尺寸 4×4→4×5 并扩展午盘复核；刷新频率全面下调（5s→30s 等，见 [§4.2](#42-datastore-设计)）；W14/W15 保持独立不合并不采纳。

### 3.2 组件详细规格

---

#### W01 · 时段时间线

**回答的问题**：现在是什么时段？距离下个窗口还有多久？

**数据来源**：系统时间 `new Date()`（纯前端，无外部依赖）

**显示内容**：
- 6 段分段标签条：竞价(9:05-9:30) / W1追涨(9:30-10:00) / 观察期(10:00-13:00) / 午盘复核(13:00-14:00) / W2低吸(14:00-14:45) / 闭窗(14:45-15:00)
- 当前段蓝色填充 + 进度百分比
- 已完成段淡出（opacity 0.35）
- 未来段灰色
- 周末/节假日显示"休市"
- **紧凑模式**：高度仅 0.5 行（约 20px），释放顶部黄金位置给决策组件（[紫米 5秒规则]）

**SSOT 溯源**：时段定义 → `trading-core.md` W1/W2 术语定义表

**交互**：无交互，纯展示

---

#### W02 · 风格检测卡

**回答的问题**：今天做什么模式？连板还是趋势？分数多少？

**数据来源**：

| 字段 | 数据路径 | 来源 | 更新 |
|------|---------|------|------|
| 风格总分 | `style.总分` | `style_detect.py --json` → `dashboard_data.json` | 每日复盘后1次 |
| 风格判定 | `style.风格` | 同上 | 同上 |
| 连板占比 | `style.连板占比` | 同上 | 同上 |
| 趋势占比 | `style.趋势占比` | 同上 | 同上 |
| Dim1 量能 | `style.dim1_量能` | 同上 | 同上 |
| Dim2 连板生态 | `style.dim2_连板生态` | 同上 | 同上 |
| Dim3 趋势 | `style.dim3_趋势` | 同上 | 同上 |
| 实际执行原因 | `style.实际执行.原因` | 同上 | 同上 |

**SSOT 溯源**：三维度打分卡 → `references/量能风格切换.md`；插值表 → `trading-core.md` §第二层

**显示内容**：
- 大号分数 + 风格标签（连板=红 / 趋势=绿 / 混合=蓝）
- 三维度迷你柱状图（量能30% / 连板40% / 趋势30%）
- 分配比例条（连板占比 vs 趋势占比，渐变色条）
- 如有硬卡/异常，红色标注原因

**交互**：无交互，盘前查看

**信息优先级**：P0 最高——盘前预设中置于左上角第一眼位置（[5秒规则]）

---

#### W03 · 三层仓位计

**回答的问题**：今天总共能买多少？连板和趋势各分多少？

**数据来源**：

| 字段 | 数据路径 | 来源 | 更新 |
|------|---------|------|------|
| 总仓位上限 | `style.总仓位上限` | 三层决策第一层检查结果 | 实时 |
| 连板占比 | `style.连板占比` | 风格检测→插值表 | 每日1次 |
| 趋势占比 | `style.趋势占比` | 同上 | 每日1次 |
| 连板实际 | `style.实际执行.连板实际` | 硬卡/熔断后覆盖 | 实时 |
| 趋势实际 | `style.实际执行.趋势实际` | 同上 | 实时 |
| 首笔上限 | `style.实际执行.首笔上限` | 同上 | 实时 |
| 熔断触发 | `risk.熔断触发` | 账户风控(W14 数据域) | 实时 |
| 连亏天数 | `risk.连亏天数` | 账户风控(W14 数据域) | 实时 |

> **v2.0 补充**：新增 `risk.熔断触发` 和 `risk.连亏天数` 两个数据订阅路径。W03 的仓位计算依赖风控域数据（熔断→仓位归零，连亏≥2天→空仓），必须在 dataPaths 中显式声明。（[洋米 Blocker #3] + [黑米 Important #5]）

**SSOT 溯源**：
- 第一层总仓位上限 → `trading-core.md` §第一层（优先级1-6检查表）
- 第二层分配比例 → `trading-core.md` §第二层（分数→插值表）
- 第三层窗口执行 → `trading-core.md` §第三层（W1/W2各自闭仓条件）
- 连板硬卡释放 → `trading-core.md` §第一层"连板硬卡空仓时资金释放"
- 高潮保护降仓 → `trading-core.md` §竞价高潮保护

**显示内容**：
- 三层递进可视化：第一层(总仓位%) → 第二层(连板%|趋势%) → 第三层(W1/W2)
- 实际可用资金数字（总资金 × 总仓位 × 占比）
- 被否决的层显示灰色 + 原因
- 风控熔断/连亏时全红警告

**交互**：无交互

---

#### W04 · 市场全景

**回答的问题**：大盘现在怎么样？

**数据来源**：

| 字段 | 数据路径 | 来源 | 刷新 |
|------|---------|------|------|
| 上证指数 | `live_index.上证指数` | iwencai → `dashboard_live.json` | 30s |
| 上证涨幅 | `live_index.上证涨幅` | 同上 | 30s |
| 深证指数 | `live_index.深证指数` | 同上 | 30s |
| 深证涨幅 | `live_index.深证涨幅` | 同上 | 30s |
| 创业指数 | `live_index.创业指数` | 同上 | 30s |
| 创业涨幅 | `live_index.创业涨幅` | 同上 | 30s |
| 成交额 | `live_index.成交额` | 同上 | 30s |
| 成交额差 | `live_index.成交额差` | 同上 | 30s |
| 涨跌比 | `market.涨跌比` | `dashboard_data.json` | 5min |
| 涨停家数 | `market.涨停家数` | 同上 | 5min |
| 跌停家数 | `market.跌停家数` | 同上 | 5min |

> **v2.0 变更**：刷新频率从 5s 下调为 30s（[稳米 Important #4]：iwencai 免费 API 无 SLA，5s 轮询大概率触发限流）

**SSOT 溯源**：三大指数 → iwencai 实时行情接口（Q1 大盘查询）

**显示内容**：
- 三指数卡片（上证/深证/创业），大号价格 + 涨跌幅（红涨绿跌）
- 成交额 + 较上时段变化
- 涨跌比 + 涨跌停家数
- 小号昨日收盘基线：灰色标注"昨日收盘"，数据来自 DataStore.initialBase 快照（[稳米 Important #8]）

**交互**：无交互，纯数据展示

---

#### W05 · 情绪仪表盘

**回答的问题**：市场情绪怎么样？短线能不能做？

**数据来源**：

| # | 字段 | 数据路径 | 来源 | 刷新 |
|---|------|---------|------|------|
| 1 | 情绪值 | `sentiment.情绪值` | 复盘笔记 / 手工录入覆盖 | manual |
| 2 | 情绪区间 | `sentiment.情绪区间` | 自动判定 | manual |
| 3 | 上涨家数 | `sentiment.上涨家数` | 手工录入（同花顺APP） | manual |
| 4 | 下跌家数 | `sentiment.下跌家数` | 手工录入（同花顺APP） | manual |
| 5 | 涨停收益 | `sentiment.昨日涨停收益` | 同花顺APP → 手工录入 | manual |
| 6 | 连板收益 | `sentiment.连板收益` | 同花顺APP → 手工录入 | manual |
| 7 | 炸板收益 | `sentiment.昨日炸板收益` | 同花顺APP → 手工录入 | manual |
| 8 | 连板风险值 | `sentiment.连板风险值` | 同花顺APP → 手工录入 | manual |
| 9 | 晋级率 | `sentiment.晋级率` | 同花顺APP → 手工录入 | manual |
| 10 | 封板率 | `market.封板率` | 同花顺APP → 手工录入 | manual |
| 11 | 赚钱效应 | `sentiment.赚钱效应` | 4指标联合判定（好/一般/差） | manual |
| 12 | 最高板 | `sentiment.最高板` | 手工录入 | manual |
| 13 | 连板梯队 | `sentiment.连板梯队` | 手工录入 | manual |

**SSOT 溯源**：
- 1+4 核心指标定义 → `references/情绪指标数据定义.md` §核心指标
- 辅助指标定义 → `references/情绪指标数据定义.md` §辅助指标
- 赚钱效应 4 指标联合判定 → `live-dashboard.html` mergeData() L1037-1039 规则
- 情绪区间阈值 → `trading-core.md` 情绪高潮保护表

**显示内容**：
- 13 张 KPI 卡片网格布局
- 每张卡片：标签(10px 大写) + 值(22px Bold) + 判定文字(彩色)
- **情绪值卡片着色规则（v2.0 修正）**：
  - 冰点(<20%) → `--warn` 橙色（非红色！与高潮区分）
  - 低迷(20-40%) → `--warn` 橙色
  - 主升(40-60%) → `--info` 蓝色
  - 强势(60-80%) → `--info` 蓝色
  - 高潮(>80%) → `--danger` 红色
  - （[洋米+黑米 Important]：冰点和高潮都用红色会造成语义混淆——极低和极高含义相反但颜色相同）
- 涨跌类卡片：▲▼ 方向箭头 + 红涨绿跌
- 底部弹窗条：冰点预警(<20%) / 高潮警报(>80%) / 情绪急降(降幅≥20pp)

**交互**：无交互，纯数据展示。数据由报数面板(W16)或复盘笔记驱动。

---

#### W06 · 竞价5维面板

**回答的问题**：竞价怎么说？今天方向在哪？

**数据来源**：

| 维度 | 子字段 | 数据路径 | 来源 | 刷新 |
|------|--------|---------|------|------|
| 大盘指数 | 上证/深证/创业竞价涨幅+涨跌家数 | `decision.竞价.大盘指数[]` | 复盘笔记预案 + 盘中确认 | 9:25 |
| 市场情绪 | 竞价情绪值/强势家数/涨停收益/量比 | `decision.竞价.市场情绪[]` | 复盘笔记预案 + 盘中确认 | 9:25 |
| 高标竞价 | 各高度板竞价涨幅 | `decision.竞价.高标竞价[]` | 同花顺APP观察 | 9:25 |
| 方向锚定 | 各板块竞价信号 | `decision.竞价.方向锚定[]` | 预案+竞价确认 | 9:25 |
| 锚定股竞价 | 各锚定股竞价涨幅 | `decision.竞价.锚定股竞价[]` | 同花顺APP观察 | 9:25 |

> **v2.0 字段统一**：竞价情绪值统一使用路径 `sentiment.竞价情绪值`。W06（市场情绪维度）和 W07（高潮保护）读取同一个数据路径，避免两组件显示不一致。（[洋米+黑米 Important]）

**其他字段**：竞价结论、高潮保护状态、动作建议

**SSOT 溯源**：
- 竞价结论判定 → `trading-core.md` §竞价高潮保护（分级保护表：80-85%降半仓/85-90%全关W1/≥90%全关）
- 方向确认规则 → `trading-core.md` 铁律#2"方向确认不到3条不做"

**显示内容**：
- 顶部：竞价结论（大号 28px 彩色字）+ 高潮保护状态 + 动作建议
- 5 列网格：大盘指数(3行) | 市场情绪(4行) | 高标竞价(N行) | 方向锚定(N行) | 锚定股竞价(N行)
- 每行前有状态灯：🔵通过 / 🔴警报 / 🟠待定
- 竞价涨跌幅按方向着色（红涨绿跌）

**交互**：无交互，纯决策辅助

---

#### W07 · 高潮保护

**回答的问题**：要不要降仓？

**数据来源**：

| 字段 | 数据路径 | 来源 | 刷新 |
|------|---------|------|------|
| 竞价情绪值 | `sentiment.竞价情绪值` | 同花顺APP | 9:25 |
| 保护级别 | 自动判定 | 80-85%/85-90%/≥90% | 9:25 |
| W1状态 | 降半仓/全关/正常 | 判定结果 | 9:25 |
| W2状态 | 降半仓/全关/正常 | 判定结果 | 9:25 |

> **v2.0 字段统一**：竞价情绪值路径与 W06 统一为 `sentiment.竞价情绪值`（[洋米+黑米 Important]）

**SSOT 溯源**：竞价高潮保护分级表 → `trading-core.md` §竞价高潮保护

**显示内容**：
- 大号情绪值 + 保护级别标签
- W1/W2 各自状态灯
- 低于阈值时显示"✅ 未触发"（绿色）
- 触发时显示红色警告 + 具体降仓指令

**交互**：无交互

---

#### W08 · W1早盘确认

**回答的问题**：W1 能不能追？

**数据来源**：

| 字段 | 数据路径 | 来源 | 刷新 |
|------|---------|------|------|
| W1出手条件 | `decision.早盘.W1出手条件` | 复盘笔记预案 | 9:30 |
| 方向确认 | `decision.早盘.方向确认[]` | 盘中确认 | 9:30-10:00 |
| 当前状态 | `decision.早盘.当前状态` | 判定 | 实时 |

**SSOT 溯源**：
- W1 追涨条件 → `rules/追涨选标_W1.md`（硬性3条+加分条件）
- W1 窗口时间 → `trading-core.md` W1/W2 术语定义
- 连板硬卡条件 → `Core-连板.md` §L2.4（晋级率<30%硬卡等）

**显示内容**：
- 4 项方向确认检查清单（每项 pass/pending/fail 状态灯）
- W1 出手条件文字（蓝色底色）
- 全部 pass → 绿色边框 + "✅ W1可追"
- 任何 fail → 红色边框 + "❌ W1关闭" + 原因

**交互**：无交互

---

#### W09 · W2低吸+午盘复核

**回答的问题**：W2 能不能吸？买哪个？午盘有没有 V 反或双冰信号？

> **v2.0 变更**：组件从"W2低吸条件"扩展为"W2低吸+午盘复核"，增加双冰场景检测和 13:00 复核结果展示区。不新增独立组件，保持总数 16 个。（[洋米 Important]：午盘复核是 trading-core.md 中 10:00-13:00 三小时观察期的核心决策环节，原 V反逻辑单独藏在 W09 中不够）

**数据来源**：

| 字段 | 数据路径 | 来源 | 刷新 |
|------|---------|------|------|
| W2出手条件 | `decision.盘中.W2出手条件[]` | 复盘笔记预案 | 10:00-14:45 |
| W2出手时机 | `decision.盘中.W2出手时机` | 盘中判断 | 实时 |
| 当前状态 | `decision.盘中.当前状态` | 判定 | 实时 |
| V反检测 | `decision.盘中.V反检测` | V反判定 | 13:00复核 |
| 双冰检测 | `decision.盘中.双冰检测` | 前日冰点+今日冰点判定 | 13:00复核 |
| 午盘复核结论 | `decision.盘中.午盘复核结论` | 综合判定 | 13:00 |

**SSOT 溯源**：
- W2 低吸条件 → `rules/W2_低吸操作.md`（企稳三阶段判断）
- V反检测逻辑 → `trading-core.md` §午盘复核：V型反弹检测
- 双冰场景 → `trading-core.md` §午盘复核（前日情绪<20% + 今日午盘情绪<20%）
- 趋势买入时机 → `Core-趋势.md` §T4（回踩5日线/10日线/突破确认）

**显示内容**：
- **W2 低吸区**（上半部）：
  - 4 项 W2 条件检查清单（大盘方向/板块状态/个股回踩/企稳确认）
  - W2 出手时机文字（蓝色底色）
- **午盘复核区**（下半部，新增）：
  - V反检测：场景描述 + 当前状态 + 复核结果（紫色底色 `--special-bg`）
  - 双冰检测：前日情绪值 + 今日午盘情绪值 + 判定结果
  - 午盘复核总结：一行结论文字
- 全部 pass → 绿色边框 + "✅ W2可吸"
- 企稳 pending → 橙色边框 + "⏳ 等待企稳"

**交互**：无交互

---

#### W10 · 板块热力图

**回答的问题**：哪个板块强？有没有退潮信号？

**数据来源**：

| 字段 | 数据路径 | 来源 | 刷新 |
|------|---------|------|------|
| 板块静态数据 | `sectors[]`（类型/涨停数/梯队/龙头/温度标/温度/状态） | 复盘笔记 → `dashboard_data.json` | 每日 |
| 板块实时数据 | `live_sectors{}`（涨跌幅/主力净流入/5日线/今日涨停数） | iwencai → `dashboard_live.json` | 60s |

> **v2.0 变更**：实时刷新频率从 30s 下调为 60s（板块数据变动慢，高频轮询性价比低）

**SSOT 溯源**：
- 板块类型判定 → `references/主线判断框架.md` §合力分级（主线/强支线/候选/分歧/脉冲/退潮）
- 合力三维度 → `references/主线判断框架.md` §一（趋势强度/赚钱效应/资金持续）
- 滚动3天数据 → `板块涨停日志.md`

**显示内容**：
- 8 板块竖排卡片，每张左侧 4px 色条（按类型着色）
- 每张卡片：板块名 + 类型标签 + 梯队 + 龙头 + 4 列实时数据（涨跌幅/主力/5日线/今日涨停数）
- 实时数据 60s 自动刷新
- 退潮板块置灰

**交互**：无交互

---

#### W11 · 上证15min量价

**回答的问题**：上证量价关系怎么样？放量还是缩量？

**数据来源**：

| 字段 | 数据路径 | 来源 | 刷新 |
|------|---------|------|------|
| 15min K线 | `上证15min[]`（t/chg/vol/volRatio） | iwencai / 同花顺 | 5min |

**SSOT 溯源**：上证15min 数据 → iwencai Q1 大盘查询（分时量价）

**显示内容**：
- 16 根柱状图，水平基准线（量比=1.0x）
- 放量(量比>1)：柱体向下延伸，实心填充
- 缩量(量比<1)：柱体向上延伸，半透明填充
- 涨=红色，跌=绿色（红涨绿跌）
- 悬停显示：时间 + 涨跌幅 + 量比
- X 轴时间标签

> **设计偏好标注**：柱体方向（量大→向下、量小→向上）与 A 股常见量价图习惯相反（通常量大柱高/长）。此为弈沐哥个人偏好设计，非笔误。（[紫米+黑米 Nice-to-have]）

**交互**：悬停 tooltip

---

#### W12 · 连板自选池

**回答的问题**：连板标的池子里有什么？哪个能追？

**数据来源**：

| 字段 | 数据路径 | 来源 | 刷新 |
|------|---------|------|------|
| 静态数据 | `lianban_pool[]`（标的/代码/板块/方向/角色/操作/窗口/收盘价/MA5/触发价/止损/选入理由/备注） | 复盘笔记预案 | 每日 |
| 实时报价 | `live_quotes{}`（最新价/涨幅/量比/换手） | iwencai → `dashboard_live.json` | 15s |

**SSOT 溯源**：
- 连板池角色定义 → `rules/自选池管理.md`（龙头/高度板/中军/跟风）
- 连板选标规则 → `rules/追涨选标_W1.md`
- 流动性硬筛 → `rules/流动性硬筛.md`

**显示内容**：
- 全宽表格：标的(代码) | 板块 | 角色 | 操作 | 涨幅 | 最新价 | 量比 | 换手 | MA5 | 备注
- 交替行背景色（奇偶行）
- 表头 sticky
- 涨幅列红涨绿跌 + 方向箭头
- 角色/操作标签彩色
- 行悬停左侧蓝色色条

**交互**：悬停备注列显示完整 tooltip

---

#### W13 · 趋势自选池

**回答的问题**：趋势标的池子里有什么？哪个回踩到位了？

**数据来源**：

| 字段 | 数据路径 | 来源 | 刷新 |
|------|---------|------|------|
| 静态数据 | `trend_pool[]`（标的/代码/板块/方向/角色/操作/买点/收盘价/MA5/MA20/止损/量比/换手/看什么/选入理由/备注） | 复盘笔记预案 | 每日 |
| 实时报价 | `live_quotes{}`（最新价/涨幅/量比/换手） | iwencai → `dashboard_live.json` | 15s |

**SSOT 溯源**：
- 趋势池角色定义 → `rules/自选池管理.md`
- 趋势选标规则 → `rules/低吸选标_W2.md` + `Core-趋势.md` §T3 个股选择
- 回踩买入时机 → `Core-趋势.md` §T4（回踩5日线+缩量/回踩10日线+支撑有效）

**显示内容**：同 W12 结构，角色/操作标签按趋势侧配色（绿色系）

**交互**：同 W12

---

#### W14 · 账户风控

**回答的问题**：风险有没有超标？要不要停手？

> **v2.0 注**：W14 与 W15 保持独立组件，不合并不采纳（[黑米 Nice-to-have #9] → 已评估：复盘场景下分开看更灵活，复盘时可能只展开持仓不看风控）

**数据来源**：

| 字段 | 数据路径 | 来源 | 刷新 |
|------|---------|------|------|
| 当日盈亏 | `risk.当日盈亏` + `risk.当日盈亏金额` | 账户计算 | realtime |
| 周累计回撤 | `risk.周累计回撤` | 账户计算 | realtime |
| 月累计回撤 | `risk.月累计回撤` | 账户计算 | realtime |
| 连亏天数 | `risk.连亏天数` | 交易记录 | realtime |
| 单日熔断线 | `risk.单日熔断线` + `risk.熔断触发` | 风控规则 | realtime |
| 周回撤预警 | `risk.周回撤预警` + `risk.周回撤触发` | 风控规则 | realtime |

**SSOT 溯源**：
- 单日熔断线(-3%) → `trading-core.md` §第一层优先级#2
- 周回撤预警(6%) → `trading-core.md` §第一层优先级#3
- 月回撤预警(10%) → `trading-core.md` §第一层
- 连亏≥2天空仓 → `trading-core.md` §第一层优先级#4
- 账户级风控取严值 → `trading-core.md` §第三层"账户级风控取严值"

**显示内容**：
- 2×3 网格，每格：标签 + 大号值 + 迷你进度条
- 回撤指标颜色梯度：绿(<3%) → 橙(3-6%) → 红(>6%)
- 熔断/连亏触发时红色警告 + "⚠️ 已触发"
- 正常时显示"✅ 安全"

**交互**：无交互

---

#### W15 · 持仓明细

**回答的问题**：手里有什么票？盈亏多少？

**数据来源**：

| 字段 | 数据路径 | 来源 | 刷新 |
|------|---------|------|------|
| 持仓 | `positions[]`（标的/方向/成本/现价/浮盈/止损/状态） | `dashboard_data.json` | realtime |

**SSOT 溯源**：持仓数据 → 复盘笔记 `盘后持仓` frontmatter 字段

**显示内容**：
- 表格：标的 | 方向 | 成本 | 现价 | 浮盈% | 止损 | 状态
- 浮盈红涨绿跌
- 空仓时显示"当前空仓" + 清仓记录
- 清仓记录：标的 + 状态 + 成本→卖出 + 盈亏 + 原因

**交互**：无交互

---

#### W16 · 报数面板

**回答的问题**：（手工录入）同花顺 APP 数据填到这里

**数据来源**：

| # | 字段 | 输入框ID | 类型 | 存储 |
|---|------|---------|------|------|
| 1 | 情绪值(%) | `in_情绪值` | number | localStorage |
| 2 | 上涨家数 | `in_上涨` | number | localStorage |
| 3 | 下跌家数 | `in_下跌` | number | localStorage |
| 4 | 涨停收益(%) | `in_涨停收益` | text | localStorage |
| 5 | 连板收益(%) | `in_连板收益` | text | localStorage |
| 6 | 炸板收益(%) | `in_炸板收益` | text | localStorage |
| 7 | 连板风险值 | `in_风险值` | text | localStorage |
| 8 | 晋级率(%) | `in_晋级率` | text | localStorage |
| 9 | 封板率(%) | `in_封板率` | text | localStorage |
| 10 | 涨停家数 | `in_涨停家数` | number | localStorage |
| 11 | 跌停家数 | `in_跌停家数` | number | localStorage |
| 12 | 赚钱效应 | `in_赚钱效应` | select(好/一般/差) | localStorage |
| 13 | 最高板 | `in_最高板` | text | localStorage |
| 14 | 次高板 | `in_次高板` | text | localStorage |
| 15 | 连板梯队 | `in_梯队` | text | localStorage |

**localStorage key 规范（v2.0 集中声明）**：

| Key | 用途 | 定义位置 |
|-----|------|---------|
| `dash_inputs` | 报数面板 15 字段 | `store.js` STORAGE_KEYS.inputs |
| `dash_panel_open` | 报数面板折叠状态 | `store.js` STORAGE_KEYS.panelOpen |
| `dash_layout` | 画板布局 JSON | `store.js` STORAGE_KEYS.layout |

> **v2.0 补全**：增加 `dash_panel_open` key（[黑米 源码验证]：live-dashboard.html L999 确认存在，v1.0 遗漏）

**SSOT 溯源**：
- 15 字段定义 → `references/情绪指标数据定义.md`
- mergeData() 逻辑 → `live-dashboard.html` mergeData() 函数（4指标联合判定赚钱效应、涨跌家数反推情绪值）

**显示内容**：
- 折叠/展开切换
- 展开时：15 输入框 auto-fill 网格 + 刷新按钮 + 更新时间
- 折叠时：一行触发条 "📝 盘中报数（展开） | 当前时段"
- 输入框聚焦时蓝色边框 + 光环
- 刷新按钮点击后："✓ 已更新" toast 反馈

**交互**：
- 折叠/展开切换（localStorage 记住状态）
- 刷新按钮 → W16 输入事件 → `DataStore.manualData.set(path, value)` → mergeData() → 通知所有订阅组件更新
- 键盘快捷键 `P` 切换展开
- 键盘快捷键 `R` 手动刷新

> **v2.0 关键接口变更**：W16 的输入事件驱动写入 `DataStore.manualData`，而非直接操作 DOM。mergeData() 第三层从 `DataStore.manualData` 读取，不再通过 `document.getElementById('in_xxx')` 读 DOM。（[稳米 Blocker #3]）

---

## 4. 数据架构

### 4.1 数据源全景

```
┌──────────────────────────────────────────────────────────────────┐
│                        数据源（3层 + 兜底层）                       │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Layer 1: 基线数据（每日1次）                                      │
│  ┌─────────────────────┐    ┌──────────────────┐                 │
│  │ 复盘笔记 frontmatter │───→│ gen_dashboard_   │───→ dashboard_  │
│  │ (YAML, ~26字段)      │    │ data.py (稳米)    │    data.json    │
│  ├─────────────────────┤    └──────────────────┘                 │
│  │ style_detect.py     │───→ JSON 输出                            │
│  │ (三维度打分, 0-100)  │                                        │
│  ├─────────────────────┤                                         │
│  │ 板块涨停日志.md       │───→ 近3天板块数据                        │
│  └─────────────────────┘                                         │
│                                                                  │
│  Layer 2: 实时数据（轮询）                                         │
│  ┌─────────────────────┐                                         │
│  │ poll_iwencai.py     │───→ dashboard_live.json                 │
│  │ (iwencai Q1/Q2/Q4)  │    (live_index + live_sectors           │
│  │ cron/launchd 守护    │     + live_quotes)                      │
│  └─────────────────────┘                                         │
│                                                                  │
│  Layer 3: 手工数据（录入）                                         │
│  ┌─────────────────────┐                                         │
│  │ 同花顺APP → 报数面板  │───→ DataStore.manualData                │
│  │ (15字段手工录入)      │    → localStorage (dash_inputs)         │
│  └─────────────────────┘                                         │
│                                                                  │
│  Layer 0: 兜底数据                                                │
│  ┌─────────────────────┐                                         │
│  │ EMBEDDED_DATA       │───→ 所有数据源不可用时，保证看板不白屏     │
│  │ (sync_embedded.py    │                                        │
│  │  每日复盘后自动同步)   │                                        │
│  └─────────────────────┘                                         │
│                                                                  │
│  脚本目录: scripts/                                               │
│  ├── gen_dashboard_data.py   ← Layer 1 基线数据生成（稳米维护）     │
│  ├── poll_iwencai.py         ← Layer 2 实时数据轮询（稳米维护）     │
│  └── sync_embedded.py        ← EMBEDDED_DATA 每日同步（稳米维护）   │
└──────────────────────────────────────────────────────────────────┘
```

> **v2.0 关键变更**：数据管线脚本独立到 `scripts/` 目录，与前端 `live-dashboard/` 物理分离。`gen_dashboard_data.py` 和 `poll_iwencai.py` 均待稳米创建（[稳米 Blocker #1, #2]）。

### 4.2 DataStore 设计

```javascript
// store.js — 单一数据中枢

/** localStorage key 集中声明（v2.0 新增） */
const STORAGE_KEYS = {
  inputs: 'dash_inputs',        // 报数面板 15 字段
  panelOpen: 'dash_panel_open', // 报数面板折叠状态
  layout: 'dash_layout',        // 画板布局 JSON
};

const DataStore = {
  // === 数据池 ===
  baseData: null,         // dashboard_data.json（Layer 1）
  liveData: null,         // dashboard_live.json（Layer 2）
  manualData: {},         // DataStore 内部管理（Layer 3）
                          // 由 W16 输入事件写入，mergeData() 读取
  merged: null,           // mergeData() 三层合并结果
  initialBase: null,      // baseData 首次加载快照（CLOSE_DATA 昨日基线）
  fallback: EMBEDDED_DATA, // Layer 0 兜底

  // === 刷新层级（v2.0 频率下调）===
  tiers: {
    tick:    { interval: 30000,  sources: ['live_index', 'live_quotes'], label: '30秒' },
    fast:    { interval: 60000,  sources: ['live_sectors'],               label: '60秒' },
    slow:    { interval: 300000, sources: ['上证15min', 'market'],        label: '5分钟' },
    manual:  { interval: null,   sources: ['sentiment', 'decision'],      label: '手工' },
    daily:   { interval: null,   sources: ['style', 'sectors'],           label: '每日' },
  },

  // === 订阅中心 ===
  // subscribers[dataPath] = [callback1, callback2, ...]
  subscribers: {},

  // === 数据适配器（v2.0 新增，预留 Dify 接入）===
  adapter: {
    fetch(tier) {
      // 默认实现：直接 fetch JSON 文件
      // 未来替换 Dify：改为 POST /api/dify/query
      return fetch(`data/dashboard_live.json`).then(r => r.json());
    }
  },

  // === 核心方法 ===

  /** 读数据，支持点号路径 'sentiment.情绪值' */
  get(path),

  /**
   * 订阅数据路径变化，返回 unsubscribe 函数
   * @param {string|string[]} paths - 单路径或路径数组
   * @param {Function} callback - 数据变化时调用
   * @returns {Function} unsubscribe - 调用后取消订阅
   *
   * 保障：
   * - 同一 (path, callback) 对不会重复注册（去重）
   * - callback 自动 debounce 100ms（防抖）
   * - 支持批量订阅：subscribe(['a.b', 'c.d'], cb)
   */
  subscribe(paths, callback),

  /** 按层级拉取数据 */
  refresh(tier),

  /** 三层合并（复用 live-dashboard.html mergeData 逻辑）
   *  合并顺序：baseData → manualData 覆盖 → liveData 覆盖
   *  v2.0 变更：第三层从 DataStore.manualData 读取，不再读 DOM */
  merge(),

  /** 返回数据溯源信息 {source, frequency, owner} */
  getSSOT(path),

  /** 写入手工数据（由 W16 报数面板调用）
   *  v2.0 新增：替代原来的 DOM 直读 */
  manualData: {
    set(path, value),  // 写入并触发 merge()
    get(path),         // 读取
    getAll(),          // 返回全部 manualData
  },

  // === 连接状态 ===
  connectionStatus: 'polling', // 'live'|'polling'|'dead'
};
```

> **v2.0 API 签名明确**：`subscribe()` 的返回值、去重、防抖行为在此定义，稳米 Phase 1 输出此 API 文档后黑米才能开始组件开发（[稳米 Blocker #3] + [黑米 Important #3]）。

### 4.3 组件→数据绑定映射

每个组件在注册时声明它需要的数据路径，DataStore 自动管理订阅和更新：

```javascript
// 示例：情绪仪表盘的数据声明
const SentimentDash = {
  type: 'sentiment-dash',
  title: '情绪仪表盘',
  tier: 'manual',
  dataPaths: [
    'sentiment.情绪值', 'sentiment.情绪区间', 'sentiment.上涨家数',
    'sentiment.下跌家数', 'sentiment.昨日涨停收益', 'sentiment.连板收益',
    'sentiment.昨日炸板收益', 'sentiment.连板风险值', 'sentiment.晋级率',
    'market.封板率', 'sentiment.赚钱效应', 'sentiment.最高板',
    'sentiment.连板梯队',
  ],
};

// 示例：三层仓位计的数据声明（v2.0 补充 risk 订阅）
const PositionCalc = {
  type: 'position-calc',
  title: '三层仓位计',
  tier: 'realtime',
  dataPaths: [
    'style.总仓位上限', 'style.连板占比', 'style.趋势占比',
    'style.实际执行.连板实际', 'style.实际执行.趋势实际',
    'style.实际执行.首笔上限',
    'risk.熔断触发',   // v2.0 新增
    'risk.连亏天数',   // v2.0 新增
  ],
};
```

### 4.4 SSOT 溯源表（完整）

每个数字都能回答：从哪来、谁负责更新、多久更新一次、不可用时如何处理。

| # | 数字 | SSOT 源文件 | 数据获取方式 | 更新频率 | 负责人 | 兜底策略 |
|---|------|-----------|------------|---------|--------|---------|
| 1 | 风格分数(0-100) | `references/量能风格切换.md` | `style_detect.py --json` | 每日复盘后 | 稳米 | EMBEDDED_DATA |
| 2 | 连板/趋势占比 | `trading-core.md` §第二层 插值表 | 分数→查表 | 每日复盘后 | 稳米 | EMBEDDED_DATA |
| 3 | 总仓位上限 | `trading-core.md` §第一层 优先级检查 | 规则引擎判定 | 实时 | 规则引擎（自动） | EMBEDDED_DATA |
| 4 | 情绪值 | `references/情绪指标数据定义.md` #1 | 同花顺APP→手工录入 | 盘中随录 | 弈沐哥 | 涨跌家数反推 |
| 5 | 涨停收益 | `references/情绪指标数据定义.md` #2 | 同花顺APP→手工录入 | 盘中随录 | 弈沐哥 | EMBEDDED_DATA |
| 6 | 连板收益 | `references/情绪指标数据定义.md` #3 | 同花顺APP→手工录入 | 盘中随录 | 弈沐哥 | EMBEDDED_DATA |
| 7 | 连板风险值 | `references/情绪指标数据定义.md` #4 | 同花顺APP→手工录入 | 盘中随录 | 弈沐哥 | EMBEDDED_DATA |
| 8 | 炸板收益 | `references/情绪指标数据定义.md` #5 | 同花顺APP→手工录入 | 盘中随录 | 弈沐哥 | EMBEDDED_DATA |
| 9 | 赚钱效应 | `references/情绪指标数据定义.md` #6 | 4指标联合判定（mergeData规则） | 自动 | 规则引擎（自动） | EMBEDDED_DATA |
| 10 | 晋级率 | `references/情绪指标数据定义.md` #7 | 同花顺APP→手工录入 | 盘中随录 | 弈沐哥 | EMBEDDED_DATA |
| 11 | 封板率 | `references/情绪指标数据定义.md` #11 | 同花顺APP→手工录入 | 盘中随录 | 弈沐哥 | EMBEDDED_DATA |
| 12 | 上证指数+涨幅 | iwencai Q1 大盘查询 | `poll_iwencai.py` → `dashboard_live.json` | 30s | 稳米脚本 | EMBEDDED_DATA |
| 13 | 成交额 | iwencai Q1 大盘查询 | `poll_iwencai.py` → `dashboard_live.json` | 30s | 稳米脚本 | EMBEDDED_DATA |
| 14 | 板块实时数据 | `references/主线判断框架.md` §一 | `poll_iwencai.py` Q4 批量查询 | 60s | 稳米脚本 | EMBEDDED_DATA |
| 15 | 板块静态数据 | `板块涨停日志.md` + 复盘笔记 | `gen_dashboard_data.py`（scripts/，稳米维护） | 每日复盘后 | 稳米 | EMBEDDED_DATA |
| 16 | 竞价5维 | 复盘笔记预案 + 盘中确认 | 预案 frontmatter + 手工确认 | 9:25 一次性 | 弈沐哥 | EMBEDDED_DATA |
| 17 | 上证15min量价 | iwencai 分时数据 | `poll_iwencai.py` | 5min | 稳米脚本 | EMBEDDED_DATA |
| 18 | 连板/趋势池静态 | 复盘笔记预案 | `gen_dashboard_data.py`（scripts/，稳米维护） | 每日复盘后 | 稳米 | EMBEDDED_DATA |
| 19 | 实时报价 | iwencai Q4 批量查询 | `poll_iwencai.py` → `live_quotes` | 15s | 稳米脚本 | 静态收盘价 |
| 20 | 风控指标 | 账户计算 + 复盘笔记 | 复盘笔记 frontmatter | realtime | 弈沐哥 | EMBEDDED_DATA |
| 21 | 持仓数据 | 复盘笔记 `盘后持仓` | `gen_dashboard_data.py`（scripts/，稳米维护） | realtime | 稳米 | EMBEDDED_DATA |
| 22 | 竞价情绪值 | `sentiment.竞价情绪值`（W06/W07 统一路径） | 同花顺APP→手工录入 | 9:25 | 弈沐哥 | EMBEDDED_DATA |
| 23 | 次高板 | 复盘笔记 frontmatter | `gen_dashboard_data.py`（scripts/，稳米维护） | 每日复盘后 | 稳米 | EMBEDDED_DATA |
| 24 | 昨日情绪 | 复盘笔记 frontmatter | `gen_dashboard_data.py`（scripts/，稳米维护） | 每日复盘后 | 稳米 | EMBEDDED_DATA |
| 25 | 情绪变化 | 计算值（今日-昨日） | mergeData() 自动计算 | 自动 | 规则引擎（自动） | EMBEDDED_DATA |

> **v2.0 修正**：#3 负责人从"洋米"改为"规则引擎（自动）"（[稳米 Important #6]）；#1/#15/#18/#21 获取方式补充脚本名和目录；新增 #22-#25 四行（[稳米 Important #7]：溯源表遗漏字段补全）。

---

## 5. UI/UX 规范

### 5.0 信息优先级（v2.0 新增）

> **5 秒规则**：用户打开看板 5 秒内，必须能判断今日交易信号好坏。（[紫米 Blocker #2]）

组件在预设布局中的排列优先级（非类型分组，而是按决策链排序）：

| 优先级 | 组件 | 原因 |
|--------|------|------|
| P0 第一眼 | W02 风格检测卡 | "今天做什么模式"——最关键的决策起点 |
| P0 第二眼 | W14 账户风控 | "有没有风控红线"——决定能不能做 |
| P0 第三眼 | W03 三层仓位计 | "能做多少"——资金分配方案 |
| P1 参考 | W04 市场全景 | "大盘怎么样"——背景信息 |
| P1 参考 | W05 情绪仪表盘 | "市场情绪怎么样"——背景信息 |
| P2 工具 | W01 时段时间线 | "现在几点"——纯工具，放底部或最小化 |

### 5.1 色彩系统

```css
:root {
  /* === 背景三层 === */
  --bg-deep: #0a0e14;     /* 画布底层（最深） */
  --bg-base: #111820;      /* 组件内容区 */
  --bg-card: #161d28;      /* 卡片/表格行 */
  --bg-hover: #1c2533;     /* 悬停高亮 */
  --bg-input: #0d1117;     /* 输入框背景 */

  /* === 文字四层 === */
  --text-primary: #e8eaed;   /* 主文字，WCAG AA (contrast 12.5:1) */
  --text-secondary: #9aa0a6; /* 辅助文字 (contrast 5.3:1) */
  --text-disabled: #5f6368;  /* 禁用/占位 (contrast 3.4:1) */

  /* === A 股方向色（红涨绿跌） === */
  --up: #ef5350;              /* 涨红 */
  --up-deep: #e53935;         /* 深涨（K线填充） */
  --up-bg: rgba(239,83,80,0.10);        /* 涨背景 */
  --up-bg-hover: rgba(239,83,80,0.18);  /* 涨悬停（v2.0 补充） */
  --down: #66bb6a;            /* 跌绿 */
  --down-deep: #43a047;       /* 深跌 */
  --down-bg: rgba(102,187,106,0.10);     /* 跌背景 */
  --down-bg-hover: rgba(102,187,106,0.18); /* 跌悬停（v2.0 补充） */

  /* === 4 级语义色 === */
  --info: #5c9ce6;            /* 信息/正常/通过 */
  --info-bg: rgba(92,156,230,0.10);
  --warn: #ffa726;            /* 警告/关注/待定 */
  --warn-bg: rgba(255,167,38,0.10);
  --danger: #ef5350;          /* 危险/退潮/熔断 */
  --danger-bg: rgba(239,83,80,0.10);
  --special: #ab47bc;         /* 特殊/V反/例外 */
  --special-bg: rgba(171,71,188,0.10);

  /* === 紫色高亮（v2.0 新增，非紧急但重要的提醒） === */
  --accent-purple: #7c4dff;
  --accent-purple-bg: rgba(124,77,255,0.10);

  /* === 组件类型色标（标题栏左侧 3px 色条） === */
  --color-decision: #5c9ce6;  /* 决策类 — 蓝 */
  --color-data: #66bb6a;      /* 数据类 — 绿 */
  --color-risk: #ef5350;      /* 风控类 — 红 */
  --color-tool: #9aa0a6;      /* 工具类 — 灰 */

  /* === 板块6色 === */
  --sector-main: #ef5350;      /* 主线 — 红 */
  --sector-strong: #ffa726;    /* 强支线 — 橙 */
  --sector-candidate: #5c9ce6; /* 候选 — 蓝 */
  --sector-divergence: #ffa726;/* 分歧 — 橙 */
  --sector-pulse: #9aa0a6;     /* 脉冲 — 灰 */
  --sector-ebb: #5f6368;       /* 退潮 — 深灰 */

  /* === 边框 === */
  --border: #2a3140;
  --border-light: #1e2632;
  --divider: #3c4043;          /* 分割线（v2.0 补充） */

  /* === 阴影 4 级（v2.0 升级：2级→4级，色温偏蓝黑） === */
  --shadow-card: 0 1px 0px rgba(10,14,20,0.4);          /* 组件默认（单线阴影） */
  --shadow-elevated: 0 4px 12px rgba(10,14,20,0.5);     /* 悬停/选中 */
  --shadow-drag: 0 8px 24px rgba(10,14,20,0.6);          /* 拖拽中 */
  --shadow-modal: 0 0 0 1px rgba(255,255,255,0.08),      /* 弹窗 */
                  0 24px 48px rgba(10,14,20,0.7);
  --shadow-glow-info: 0 0 12px rgba(92,156,230,0.12);    /* 信息类微光 */

  /* === GridStack 覆盖 === */
  --widget-header-bg: rgba(17,24,32,0.95);
  --widget-header-height: 32px;
  --widget-radius: 8px;

  /* === 排版 === */
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  --font-mono: "JetBrains Mono", "SF Mono", "Cascadia Code", monospace;
  --fs-label: 10px;    /* 标签/列头 */
  --ls-label: 0.3px;   /* label 字间距（v2.0 新增） */
  --fs-body: 12px;     /* 正文/表格 */
  --fs-header: 13px;   /* 组件标题 */
  --fs-subtitle: 15px; /* 小标题 */
  --fs-kpi: 22px;      /* KPI 数字 */

  /* === 间距 === */
  --sp-xs: 4px; --sp-sm: 8px; --sp-md: 12px; --sp-lg: 16px; --sp-xl: 24px;

  /* === 圆角 === */
  --radius-sm: 3px; --radius-md: 6px; --radius-lg: 10px;
}
```

**硬规则（v2.0 修正）**：
- `--up` / `--down` 仅用于有方向的数字（涨跌幅、盈亏、量比变化）
- `--info` / `--warn` / `--danger` 仅用于状态判定（通过/关注/退潮）
- **情绪值着色**：冰点(<20%)→`--warn`(橙)、高潮(>80%)→`--danger`(红)。冰点和高潮含义相反，不能同色
- `--accent-purple` 独立存在，既不绑方向色也不绑语义色——用于非紧急但重要的提醒
- 不用颜色做唯一信息载体——涨跌值配 ▲▼ 箭头，状态配 🔵🔴🟠 灯
- 暗色底阴影铁律：色温 `rgba(10,14,20,x)` 偏蓝黑，避免"浮灰感"

### 5.2 排版层级

| 级别 | 大小 | 字重 | 字体 | 额外样式 | 用在哪 |
|------|------|------|------|---------|--------|
| Hero | 28px | 700 | sans | — | 竞价结论 |
| KPI | 22px | 700 | mono | `tabular-nums lining-nums` | KPI 卡片数值 |
| Subtitle | 15px | 600 | sans | — | 面板标题 |
| Header | 13px | 600 | sans | — | 组件标题栏 |
| Body | 12px | 400/600 | mono | `tabular-nums lining-nums` | 表格数据、数字 |
| Label | 10px | 500 | sans | `uppercase letter-spacing:0.3px` | 列头、标签、辅助文字 |
| Micro | 9px | 400 | sans | — | 时间戳、备注 |

> **v2.0 修正**：Label 层 `uppercase + letter-spacing`（[紫米 Important #4]）；KPI/Body 数字补 `lining-nums`（[紫米 Nice-to-have #8]）；字体栈不替换为 Google Fonts（保持零构建约束）。

### 5.3 组件通用结构

```
┌──────────────────────────────────────────────────┐
│ ▌🎯 竞价5维                 12:34:22 [−][↻][×]   │  ← 标题栏（32px）
│   ↑ 类型色标(3px)  标题  数据时间戳  折叠/刷新/删除 │
├──────────────────────────────────────────────────┤
│                                                  │
│         组件内容区（自由设计）                      │  ← body
│                                                  │
│  错误状态：组件渲染崩溃时显示                        │
│  ┌──────────────────────────────────────────┐    │
│  │ ⚠️ 组件加载失败                            │    │
│  │ 不影响其他组件运行                          │    │
│  └──────────────────────────────────────────┘    │
└──────────────────────────────────────────────────┘
```

**标题栏规范**：
- 高度 32px
- 左侧 3px 色条（决策=蓝 / 数据=绿 / 风控=红 / 工具=灰）
- 图标 + 标题（13px Bold）
- **右侧新增 `.data-timestamp`**：10px mono，`color: --text-secondary`，`tabular-nums`。超过 2 倍刷新间隔未更新时变 `--warn` 色（[紫米 Important #5] + [洋米 Important #3]）
- 右键按钮组：折叠 `−` / 刷新 `↻` / 删除 `×`
- 拖拽手柄：整个标题栏可拖拽（GridStack `handle: '.widget-header'`）
- 背景：`var(--widget-header-bg)` + `backdrop-filter: blur(8px)`

**错误状态规范（v2.0 新增）**：
- 每个 Widget 的 `render()` 方法必须 try-catch 包装
- 崩溃时 body 区显示"组件加载失败"兜底 UI，标题栏保持正常
- 错误不传播到其他组件（[洋米 Blocker #2] + [黑米 Blocker #1]）

### 5.4 交互规范

**组件操作**：

| 交互 | 触发方式 | 行为 |
|------|---------|------|
| 拖拽移动 | 按住标题栏拖拽 | GridStack 自动碰撞检测 + 自动填充空位 |
| 缩放 | 拖拽右下/右/下边缘 | 最小 2×2，最大 12×8，按格对齐 |
| 折叠/展开 | 点击标题栏 `−` 按钮 | body 隐藏/显示，标题栏保持 |
| 刷新 | 点击标题栏 `↻` 按钮 | 该组件立即拉取最新数据 |
| 删除 | 点击标题栏 `×` 按钮 | 从画板移除（可撤销 5 秒内） |
| 全屏 | 双击标题栏 | 该组件占满视口，Esc 退出 |
| 添加组件 | 画板空白处右键 → 选组件 | 新组件出现在点击位置 |
| 预设切换 | 顶栏下拉菜单 → 选预设 | 清空画板 → 加载预设布局 |
| 保存布局 | `Ctrl+S` / 自动保存 | grid.save() → localStorage |
| 快捷键 | `R` 全局刷新 / `P` 报数面板 / `1-4` 预设 | 键盘事件（输入框聚焦时不触发） |

**交互四态（v2.0 新增，Linear +2% 亮度递进法）**：

| 状态 | 规则 | 适用 |
|------|------|------|
| **default** | `rgba(255,255,255,0.02)` | 所有可交互元素（按钮、表格行、可点击卡片） |
| **hover** | `rgba(255,255,255,0.04)` +2% | 鼠标悬停 |
| **active/press** | `rgba(255,255,255,0.06)` +2% | 点击瞬间 |
| **focus** | `outline: 1px solid var(--info)` | 键盘导航（W16 输入框） |
| **disabled** | `rgba(255,255,255,0.01)` + cursor: not-allowed | 数据过时/组件不可用 |

> （[紫米 Important #3]：暗色背景下所有交互元素用亮度递进而非色相变化，视觉一致性好）

**性能规则**：
- 拖拽期间（`dragstart` → `dragstop`）暂停所有数据刷新，停止后一次性刷新
- 组件 render() callback 自动 debounce 100ms（DataStore subscribe 层）
- 批量 DOM 更新使用 DocumentFragment 避免逐次 reflow

### 5.5 响应式断点

| 断点 | 列数 | 适用场景 |
|------|------|---------|
| ≥2560px | 16 列 | 4K 大屏 |
| ≥1920px | 12 列 | 标准桌面（默认） |
| ≥1280px | 8 列 | 笔记本 |
| ≥960px | 8 列 | **分屏场景（同花顺+看板）**（v2.0 新增） |
| ≥768px | 4 列 | 平板 |
| <768px | 2 列 | 手机（紧急查看） |

> **v2.0 新增 960px 断点**：实际使用中同花顺左半屏+看板右半屏各约 960px，GridStack 降级到 8 列（[紫米 Nice-to-have #6]）

### 5.6 预设布局（4 套，v2.0 重排）

每个预设 JSON 文件包含 `version` 字段便于未来升级：

```json
{
  "version": "1.0",
  "name": "pre-market",
  "label": "盘前准备",
  "widgets": [...]
}
```

#### 盘前准备 `pre-market`（v2.0 按 5 秒规则重排）

```
┌──────────────────────────────────────────────┐
│ W01 时段时间线 (12×0.5) —— 压缩到最小            │
├──────────────┬──────────────┬────────────────┤
│ W02 风格检测  │ W14 账户风控  │ W03 三层仓位计   │
│ (4×4) ← 第一眼│ (4×4) ← 第二眼│ (4×4) ← 第三眼  │
├──────────────┴──────────────┴────────────────┤
│ W06 竞价5维面板 (12×5)                         │
├──────────────────────────────────────────────┤
│ W04 市场全景 (6×3)    │ W05 情绪仪表盘 (6×4)    │
└──────────────────────────────────────────────┘
```

> 组件优先级：风格检测(W02)左上角第一眼 → 风控(W14) → 仓位(W03) → 竞价(W06) → 大盘(W04)+情绪(W05)。W01 时段时间线压缩为 12×0.5 细条，释放顶部黄金位置。

#### W1 追涨 `w1-chase`

```
┌──────────────────────────────────────────────┐
│ W01 时段时间线 (12×0.5)                        │
├────────────┬──────────────────┬──────────────┤
│ W06 竞价5维 │ W07 高潮保护(3×2) │ W14 账户风控  │
│ (8×5)      │ W08 W1确认 (4×3)  │ (4×4)        │
├────────────┴──────────────────┴──────────────┤
│ W12 连板自选池 (12×4)                          │
├──────────────────────────────────────────────┤
│ W05 情绪仪表盘 (6×3)  │ W04 市场全景 (6×3)     │
└──────────────────────────────────────────────┘
```

#### W2 低吸 `w2-dip`

```
┌──────────────────────────────────────────────┐
│ W01 时段时间线 (12×0.5)                        │
├────────────┬──────────────────┬──────────────┤
│ W11 上证    │ W09 W2低吸+午盘   │ W14 账户风控  │
│ 15min(8×3) │ 复核 (4×5)       │ (4×4)        │
│            │ W02 风格检测(4×2) │              │
├────────────┴──────────────────┴──────────────┤
│ W13 趋势自选池 (12×4)                          │
├──────────────────────────────────────────────┤
│ W10 板块热力 (6×4)  │ W04 市场全景 (6×3)       │
└──────────────────────────────────────────────┘
```

#### 收盘复盘 `closing-review`

```
┌──────────────────────────────────────────────┐
│ W05 情绪仪表盘 (6×4)  │ W10 板块热力 (6×4)     │
├──────────────────────┴───────────────────────┤
│ W12 连板自选池 (6×4)  │ W13 趋势自选池 (6×4)   │
├──────────────────────────────────────────────┤
│ W14 账户风控 (4×4)    │ W15 持仓明细 (4×4)     │
├──────────────────────────────────────────────┤
│ W16 报数面板 (12×2)                            │
└──────────────────────────────────────────────┘
```

---

## 6. 技术架构

### 6.1 技术栈

| 层 | 技术 | 原因 |
|----|------|------|
| 布局引擎 | GridStack.js@12.x（CDN 锁定版本） | 拖拽+缩放+序列化，零依赖，框架无关 |
| 样式 | 原生 CSS（CSS 变量） | 零构建，双击即开 |
| 数据层 | 原生 JS DataStore + dataAdapter 抽象 | 订阅-发布模式，分层刷新，预留 Dify 替换点 |
| 组件模型 | ES6 Class（YiMuWidget 基类） | 简单继承，无框架依赖 |
| 持久化 | localStorage | 布局 JSON + 报数数据，本地存储 |
| 兜底数据 | 硬编码 EMBEDDED_DATA（sync_embedded.py 每日同步） | 所有外部数据源不可用时保证看板不白屏 |
| 外部依赖 | GridStack.js CDN（< 50KB gzipped） | 唯一外部依赖 |

> **v2.0 技术决策记录**：
> - GridStack.js 锁定 `@12.x` minor 版本，CDN URL 中用具体版本号而非 `latest`（[黑米+紫米]）
> - Custom Elements v1 **已评估，当前不采纳**。Shadow DOM CSS 变量穿透需手动注入，成本高于收益。YiMuWidget 基类对 16 组件规模足够。记录为未来评估方向（[紫米 Important → 洋米不采纳]）
> - `DataStore.adapter` 预留最小接口：`{ fetch(tier) }`。当前默认 iwencai 直连，后续替换 Dify 时只需换 adapter 实现（[洋米+黑米 Important]）

### 6.2 目录结构

```
10_⚡Now/01_💰弈沐资本/
│
├── scripts/                          ← 🆕 数据管线脚本（Python，稳米维护）
│   ├── gen_dashboard_data.py         ← 复盘笔记 → dashboard_data.json
│   ├── poll_iwencai.py               ← iwencai 轮询 → dashboard_live.json
│   └── sync_embedded.py              ← dashboard_data.json → embedded-data.js
│
├── live-dashboard/                   ← 🆕 纯前端工程目录
│   ├── index.html                    ← 主入口（画板壳 + GridStack 初始化 + 预设管理）
│   ├── store.js                      ← DataStore（数据中枢：fetch/merge/cache/订阅/SSOT查询）
│   ├── widget-base.js                ← YiMuWidget 基类（含 try-catch 错误隔离）
│   ├── widget-registry.js            ← 组件注册表（16组件元数据 + 动态加载）
│   ├── README.md                     ← 🆕 打开方式、依赖说明、出问题找谁
│   ├── widgets/
│   │   ├── timeline.js               ← W01 时段时间线
│   │   ├── style-detect.js           ← W02 风格检测卡
│   │   ├── position-calc.js          ← W03 三层仓位计
│   │   ├── market-overview.js        ← W04 市场全景
│   │   ├── sentiment-dash.js         ← W05 情绪仪表盘
│   │   ├── auction-5d.js             ← W06 竞价5维面板
│   │   ├── climax-guard.js           ← W07 高潮保护
│   │   ├── w1-check.js               ← W08 W1早盘确认
│   │   ├── w2-check.js               ← W09 W2低吸+午盘复核
│   │   ├── sector-heat.js            ← W10 板块热力图
│   │   ├── volume-bars.js            ← W11 上证15min量价
│   │   ├── lianban-pool.js           ← W12 连板自选池
│   │   ├── trend-pool.js             ← W13 趋势自选池
│   │   ├── risk-panel.js             ← W14 账户风控
│   │   ├── positions.js              ← W15 持仓明细
│   │   └── input-panel.js            ← W16 报数面板
│   ├── presets/
│   │   ├── pre-market.json           ← 盘前预设
│   │   ├── w1-chase.json             ← W1追涨预设
│   │   ├── w2-dip.json               ← W2低吸预设
│   │   └── closing-review.json       ← 收盘复盘预设
│   ├── css/
│   │   └── theme.css                 ← 全局主题（CSS 变量 + GridStack 覆盖 + 组件通用样式）
│   ├── data/
│   │   ├── dashboard_data.json       ← scripts/ 产出，Layer 1 基线数据
│   │   ├── dashboard_live.json       ← scripts/ 产出，Layer 2 实时数据
│   │   └── embedded-data.js          ← scripts/ 产出，Layer 0 兜底数据
│   └── assets/
│       └── logo.svg                  ← 🆕 浏览器标签页图标
│
├── live-dashboard.html               ← 旧版（保留做参考，不删除）
├── dashboard_data.json               ← 旧位置（废弃，迁移到 live-dashboard/data/）
├── trading-core.md                   ← 交易核心路由
├── Core-连板.md                       ← 连板操作手册
├── Core-趋势.md                       ← 趋势操作手册
├── 板块涨停日志.md
├── references/
│   ├── 情绪指标数据定义.md
│   ├── 量能风格切换.md
│   ├── 主线判断框架.md
│   └── ...
├── rules/
│   ├── 追涨选标_W1.md
│   ├── 低吸选标_W2.md
│   ├── W2_低吸操作.md
│   ├── 自选池管理.md
│   ├── 流动性硬筛.md
│   └── ...
└── 复盘笔记/
    └── ...
```

> **v2.0 目录变更**：新增 `scripts/`、`live-dashboard/`、`live-dashboard/assets/`、`live-dashboard/README.md`；数据文件从根目录迁移到 `live-dashboard/data/`；旧 `dashboard_data.json` 和 `live-dashboard.html` 保留不删。

### 6.3 组件生命周期

```
register → instantiate → mount → (resize/refresh repeat) → unmount

1. register: WidgetRegistry 注册组件 class 和元数据
2. instantiate: 用户右键添加 / 预设加载 → new WidgetClass(config)
3. mount: GridStack 创建 DOM 容器 → widget.render(data) → DOM 填充
          → widget.onMount(container) → 绑定事件、启动定时器
          → DataStore.subscribe(paths, widget.render)
4. refresh: 定时器触发 / 用户点击刷新 / DataStore 通知 → widget.render(newData)
5. resize: GridStack 检测尺寸变化 → widget.onResize(w, h) → 自适应渲染
6. unmount: 用户删除组件 → 取消订阅 → 清除定时器 → GridStack 移除 DOM

错误隔离（v2.0 新增）：
- widget.render() 必须 try-catch 包装
- 捕获异常时 body 区渲染兜底 UI（"组件加载失败"）
- 错误记录到 console.error + DataStore.errors[]
- 标题栏保持正常（用户仍可删除/折叠该组件）
- 拖拽期间暂停数据刷新（dragstart → dragstop），停止后一次性刷新
```

### 6.4 与现有系统的关系

| 现有文件 | 本产品中的角色 |
|---------|-------------|
| `live-dashboard.html` | **被替代**。其 CSS/HTML/JS 拆分迁移到 `theme.css` + 各 widget + `store.js`。保留不删 |
| `dashboard_data.json` | **继续使用**。生成方式从手工拼装升级为 `scripts/gen_dashboard_data.py` 自动化 |
| `dashboard_live.json` | **新建**。由 `scripts/poll_iwencai.py` 盘中轮询生成 |
| `EMBEDDED_DATA` | **迁移**到 `data/embedded-data.js`，每日复盘后 `sync_embedded.py` 自动同步 |
| `mergeData()` 函数 | **迁移**到 `store.js`，逻辑不变，第三层从 DOM 读改为从 DataStore.manualData 读 |
| `fetchAndRender()` 函数 | **重构**为 DataStore.refresh(tier)，按层级触发 |
| 报数面板 15 输入框 | **迁移**到 `widgets/input-panel.js`，逻辑不变，输入事件驱动 manualData |
| 时段时间线逻辑 | **迁移**到 `widgets/timeline.js`，逻辑不变 |
| 同花顺录入字段 | **不变**。15 字段 ID 和 localStorage key 完全保留 |
| `trading-dashboard.html` | **独立文件**（58KB，Mermaid 交易系统图），不在本产品范围。如需集成系统图到新看板，单独评估 |

---

## 7. 实施计划

**总工期**：8-10 天（黑米估算，洋米/紫米同意）
**稳米工期**：3-4 天（与黑米可并行）
**分工原则**：稳米负责数据管线 + DataStore 核心 API；黑米负责前端组件 + 画板交互

### Phase 1：基础设施（2-2.5 天）

**目标**：目录结构 + DataStore + 数据管线 + 空画板跑通 + **全链路验证门控通过**

| 任务 | 负责人 | 产出 | 验证 |
|------|--------|------|------|
| 1.1 备份 `live-dashboard.html` | 黑米 | `.bak_20260509` | 文件存在 |
| 1.2 创建目录结构 | 黑米 | `live-dashboard/` + `scripts/` + 子目录 | `ls -R` 确认 |
| 1.3 提取 `store.js`（含 mergeData 迁移 + manualData 接口 + STORAGE_KEYS + dataAdapter + initialBase） | 稳米 | DataStore 完整实现 | 控制台 `DataStore.get('sentiment.情绪值')` 返回正确值 |
| 1.4 提取 `widget-base.js`（含 try-catch 错误隔离） | 黑米 | YiMuWidget 基类 + 生命周期 | 实例化测试组件不报错，模拟 throw 验证兜底 UI |
| 1.5 创建 `index.html` | 黑米 | GridStack 12列空画板 + CDN 引入（版本锁定）| 浏览器打开，画板可看到网格背景 |
| 1.6 创建 `css/theme.css`（含阴影4级 + 紫色高亮 + 交互四态 + 补充变量 + 数据时间戳样式） | 黑米 | 完整的 CSS 变量体系 | 浏览器 DevTools 检查 `:root` 变量完整 |
| 1.7 创建 `widget-registry.js` | 黑米 | 16 组件元数据注册表 | `WidgetRegistry.list()` 返回 16 项 |
| **1.8 创建 `scripts/gen_dashboard_data.py`** | **稳米** | 复盘笔记 frontmatter → dashboard_data.json | 运行脚本 → diff 输出与预期一致 |
| **1.9 创建 `scripts/poll_iwencai.py`** | **稳米** | iwencai Q1/Q2/Q4 轮询 → dashboard_live.json | 运行脚本 → JSON 文件生成正确 |
| **1.10 输出 DataStore API 文档** | **稳米** | subscribe/manualData/adapter 接口签名明确 | 黑米确认可基于此文档开发 |
| 1.11 创建 `data/embedded-data.js` + `scripts/sync_embedded.py` | 稳米 | EMBEDDED_DATA 兜底 + 每日同步脚本 | dashboard_data.json → embedded-data.js 自动生成 |

**Phase 1 全链路验证门控（必须通过才能进 Phase 2）**：
- [ ] `DataStore.get('sentiment.情绪值')` 返回正确值
- [ ] `DataStore.merge()` 三层合并顺序验证通过（baseData → manualData → liveData）
- [ ] `DataStore.subscribe()` 返回 unsubscribe 函数，调用后取消订阅
- [ ] `DataStore.manualData.set()` 写入后 mergeData() 正确覆盖
- [ ] 模拟 widget render() throw → 兜底 UI 显示 → 其他组件正常
- [ ] `scripts/gen_dashboard_data.py` 运行成功，输出 JSON 字段与 PRD §4.4 溯源表对齐
- [ ] `scripts/poll_iwencai.py` 运行成功（至少一次成功轮询），输出 dashboard_live.json

> （[洋米 Blocker #4] + [黑米 Blocker #2]：全链路验证门控）

### Phase 2：组件迁移——数据+工具+风控类（1-1.5 天）

**目标**：迁移基础组件，验证组件模型。**W14 最先完成**（W03 依赖 W14 数据域）

| 任务 | 组件 | 负责人 | 说明 |
|------|------|--------|------|
| **2.0 W14 账户风控** | W14 | 黑米 | **最先完成**。定义 risk 数据域（熔断触发/连亏天数等），W03 依赖此域 |
| 2.1 | W01 时段时间线 | 黑米 | 纯前端，零数据依赖，紧凑模式 12×0.5 |
| 2.2 | W04 市场全景 | 黑米 | 从 live-dashboard.html 迁移 + initialBase 昨日基线 |
| 2.3 | W05 情绪仪表盘 | 黑米 | 从 live-dashboard.html 迁移 + v2.0 冰点/高潮颜色修正 |
| 2.4 | W15 持仓明细 | 黑米 | 从 live-dashboard.html 迁移 |
| 2.5 | W16 报数面板 | 黑米 | 从 live-dashboard.html 迁移 + 输入事件驱动 manualData 接口 |
| 2.6 数据验证 | — | 稳米 | 确认 dashboard_data.json 与组件渲染一致 |

**Phase 2 验证**：右键菜单添加 6 个组件 → 数据正确 → 拖拽不报错 → 报数面板录入/刷新/持久化 → **兜底测试 + localStorage 测试（前置）**

> （[洋米+黑米 Nice-to-have #11]：测试前置到 Phase 2 末尾，避免 Phase 5 堆一起）

### Phase 3：组件迁移——决策+数据类（2-3 天）

**目标**：迁移核心决策组件和剩余数据组件。W02/W03 是全新组件（非迁移）。

| 任务 | 组件 | 负责人 | 说明 |
|------|------|--------|------|
| 3.1 | W06 竞价5维 | 黑米 | 从 live-dashboard.html 迁移决策看板-竞价部分，字段路径统一 |
| 3.2 | W07 高潮保护 | 黑米 | 新组件，字段路径与 W06 统一 |
| 3.3 | W08 W1早盘确认 | 黑米 | 从 live-dashboard.html 迁移 |
| 3.4 | W09 W2低吸+午盘复核 | 黑米 | 扩展组件，增加双冰检测+午盘复核区 |
| 3.5 | W10 板块热力 | 黑米 | 从 live-dashboard.html 迁移 |
| 3.6 | W11 上证15min | 黑米 | 从 live-dashboard.html 迁移 + 偏好标注 |
| 3.7 | W12 连板自选池 | 黑米 | 从 live-dashboard.html 迁移 |
| 3.8 | W13 趋势自选池 | 黑米 | 从 live-dashboard.html 迁移 |
| 3.9 | **W02 风格检测卡（新增）** | 黑米 | 全新组件，从 style 数据渲染三维度打分可视化。**+0.5 天** |
| 3.10 | **W03 三层仓位计（新增）** | 黑米 | 全新组件，从 trading-core.md 规则渲染三层决策。依赖 W14 risk 数据域已就位。**+0.5 天** |

**Phase 3 验证**：全部 16 组件可独立添加到画板 → 所有数据字段正确渲染 → 红涨绿跌颜色正确 → 冰点/高潮颜色区分正确

> （[洋米+黑米 Important]：W02/W03 是全新组件无现成代码可复制，各 +0.5 天）

### Phase 4：画板功能 + 预设（1 天）

**目标**：交互功能完整

| 任务 | 功能 | 负责人 | 说明 |
|------|------|--------|------|
| 4.1 | 右键菜单 | 黑米 | 画板空白处右键 → 按类型分组显示 16 组件 → 点击添加 |
| 4.2 | 布局序列化 | 黑米 | `grid.save()` → localStorage → 刷新页面恢复 |
| 4.3 | 4 套预设 | 黑米 | `pre-market.json`(v2.0 重排) / `w1-chase.json` / `w2-dip.json` / `closing-review.json` |
| 4.4 | 预设切换 UI | 黑米 | 顶栏下拉菜单 + 快捷键 `1-4` |
| 4.5 | 布局导出/导入 | 黑米 | 导出 JSON 文件 / 从 JSON 文件导入 |
| 4.6 | 组件全屏 | 黑米 | 双击标题栏 → 全屏 → Esc 退出 |
| 4.7 | 删除撤销 | 黑米 | 删除后 5 秒内 toast "已删除，点击撤销" |
| 4.8 | 快捷键系统 | 黑米 | `R` 全局刷新 / `P` 报数面板 / `1-4` 预设切换 / `Ctrl+S` 保存 / `Ctrl+Z` 撤销 / `A` 组件面板 |
| 4.9 | 预设数据验证 | 稳米 | 确认 4 套预设中的数据引用与 dashboard_data.json 一致 |

**Phase 4 验证**：右键添加组件流畅 → 拖拽/缩放流畅 → 切换预设无误 → 刷新页面布局保持 → 导出/导入正确

### Phase 5：测试 + 文档（0.5-1 天）

| 任务 | 负责人 | 说明 |
|------|--------|------|
| 5.1 全组件渲染测试 | 黑米 | 16 组件同时加载，无 JS 报错 |
| 5.2 数据刷新测试 | 稳米 | 修改 `dashboard_data.json` → 对应组件正确更新 |
| 5.3 兜底测试 | 稳米 | 删除 `dashboard_data.json` + `dashboard_live.json` → 看板用 EMBEDDED_DATA 正常渲染，显示"数据可能过时"警告 |
| 5.4 localStorage 测试 | 黑米 | 布局 + 报数数据持久化正确 |
| 5.5 错误隔离测试 | 黑米 | 模拟 W05 render throw → "组件加载失败" → W04/W06 正常 |
| 5.6 浏览器兼容 | 黑米 | Chrome / Safari / Edge 测试通过 |
| 5.7 性能测试 | 黑米 | 16 组件首次渲染 < 1s，单组件更新 < 50ms，拖拽 ≥30fps |

---

## 8. 验收标准

### 8.1 功能完整性

- [ ] 16 个组件全部可独立渲染，数据正确
- [ ] 每个组件可独立添加/删除/折叠/刷新/全屏
- [ ] 所有组件可拖拽移动、缩放，布局持久化
- [ ] 4 套预设可一键切换（盘前预设按 v2.0 优先级重排）
- [ ] 右键菜单列出全部 16 个组件
- [ ] 快捷键全部生效（输入框聚焦时不触发）
- [ ] 报数面板 15 字段录入/刷新/持久化与原版一致
- [ ] 单组件 JS 崩溃不影响其他组件，显示兜底 UI

### 8.2 数据正确性

- [ ] 每个数字可追溯到 SSOT（PRD §4.4 溯源表）
- [ ] 红涨绿跌颜色 100% 正确
- [ ] 情绪值冰点(<20%)显示橙色(--warn)，高潮(>80%)显示红色(--danger)
- [ ] 状态灯（🔵🔴🟠）判定逻辑与原版一致
- [ ] 赚钱效应 4 指标联合判定逻辑不变
- [ ] 情绪值从涨跌家数反推逻辑不变
- [ ] 三层数据合并顺序正确（baseData → manualData → liveData）
- [ ] W06/W07 竞价情绪值路径统一为 `sentiment.竞价情绪值`
- [ ] W03 正确订阅 `risk.熔断触发` + `risk.连亏天数`
- [ ] DataStore.manualData 写入 → mergeData() 正确覆盖

### 8.3 视觉规范

- [ ] 色彩系统全部使用 CSS 变量，无硬编码色值
- [ ] 阴影 4 级（card/elevated/drag/modal）色温使用 `rgba(10,14,20,x)`
- [ ] 组件类型色标正确（决策=蓝 / 数据=绿 / 风控=红 / 工具=灰）
- [ ] 紫色高亮 `--accent-purple` 可用于非紧急但重要提醒
- [ ] 表格交替行背景色
- [ ] 表头 sticky
- [ ] 数字列 mono 字体 + `tabular-nums lining-nums` 对齐
- [ ] Label 层 `uppercase + letter-spacing: 0.3px`
- [ ] 涨跌值配 ▲▼ 方向箭头（非仅靠颜色）
- [ ] 交互四态（hover/active/focus/disabled）+2% 亮度递进生效
- [ ] 组件标题栏右侧显示数据时间戳，过期变色警告
- [ ] 响应式断点生效（16→12→8→8(960px)→4→2 列）

### 8.4 兜底与异常

- [ ] `dashboard_data.json` 404 → EMBEDDED_DATA 兜底 → 看板正常渲染
- [ ] `dashboard_live.json` 404 → 实时数据空白 → 静态数据正常
- [ ] localStorage 清空 → 报数面板空白 → 默认布局加载
- [ ] GridStack CDN 不可用 → 降级提示 "正在加载布局引擎..."
- [ ] 单组件 render() 崩溃 → 该组件显示"组件加载失败" → 其他组件正常
- [ ] EMBEDDED_DATA 过时时显示"数据可能过时"警告（meta.stale=true 标记）

### 8.5 非功能需求

- [ ] 首次加载 < 1s（含 EMBEDDED_DATA 渲染）
- [ ] 16 组件全部渲染 < 500ms
- [ ] 单组件内更新 < 50ms
- [ ] 拖拽帧率 ≥ 30fps
- [ ] 拖拽期间暂停数据刷新，停止后一次性刷新
- [ ] 无内存泄漏（添加/删除组件 20 次后内存不增长）
- [ ] 零 `console.error`（正常流程，崩溃场景除外）

---

## 9. 附录

### 9.1 术语对照

| 术语 | 定义 | 来源文件 |
|------|------|---------|
| W1 | 9:30-10:00，连板追涨 + 趋势突破 | `trading-core.md` §W1/W2 术语定义 |
| W2 | 14:00-14:45，纯趋势低吸，连板不做 | 同上 |
| 三层决策 | 总仓位上限 → 风格分配 → 窗口执行 | `trading-core.md` §三层决策规则 |
| 风格检测 | 三维度打分(量能30%+连板40%+趋势30%) → 0-100分 | `references/量能风格切换.md` |
| 1+4 核心指标 | 情绪值 + 涨停收益 + 连板收益 + 风险值 + 炸板收益 | `references/情绪指标数据定义.md` |
| 竞价5维 | 大盘指数 / 市场情绪 / 高标竞价 / 方向锚定 / 锚定股竞价 | `live-dashboard.html` decision.竞价 |
| V反检测 | 前日冰点→午盘修复→开放趋势W2 | `trading-core.md` §午盘复核 |
| 双冰检测 | 前日情绪<20% + 今日午盘情绪<20% → 特殊场景处理 | `trading-core.md` §午盘复核 |
| 高潮保护 | 竞价情绪≥80%分级降仓 | `trading-core.md` §竞价高潮保护 |
| 板块合力 | 三维度（趋势强度/赚钱效应/资金持续）≥2/3 连续3天 | `references/主线判断框架.md` |
| SSOT | Single Source of Truth，每个数字唯一定义位置 | `_schema/文件体系.md` |
| EMBEDDED_DATA | 硬编码兜底数据，所有外部数据源不可用时使用 | `live-dashboard.html` → `data/embedded-data.js` |
| dataAdapter | DataStore 的数据源适配接口，当前默认 iwencai 直连，可替换为 Dify | `store.js` |
| 5秒规则 | 用户打开看板 5 秒内必须能判断今日交易信号好坏 | 紫米评审 §1.2 |
| manualData | DataStore 中管理手工录入数据的模块，替代原 DOM 直读方式 | `store.js` |
| initialBase | baseData 的首次加载快照，作为各组件的"昨日收盘基线" | `store.js` |

### 9.2 关键文件索引

| 文件 | 路径 | PRD 引用 |
|------|------|---------|
| 交易核心路由 | `10_⚡Now/01_💰弈沐资本/trading-core.md` | §3.2 全部决策组件 SSOT |
| 连板手册 | `10_⚡Now/01_💰弈沐资本/Core-连板.md` | W01/W08/W12 SSOT |
| 趋势手册 | `10_⚡Now/01_💰弈沐资本/Core-趋势.md` | W01/W09/W13 SSOT |
| 情绪指标定义 | `10_⚡Now/01_💰弈沐资本/references/情绪指标数据定义.md` | W05/W16 字段 SSOT |
| 量能风格切换 | `10_⚡Now/01_💰弈沐资本/references/量能风格切换.md` | W02 SSOT |
| 主线判断框架 | `10_⚡Now/01_💰弈沐资本/references/主线判断框架.md` | W10 SSOT |
| 自选池管理 | `10_⚡Now/01_💰弈沐资本/rules/自选池管理.md` | W12/W13 角色定义 SSOT |
| 追涨选标 W1 | `10_⚡Now/01_💰弈沐资本/rules/追涨选标_W1.md` | W08 SSOT |
| 低吸选标 W2 | `10_⚡Now/01_💰弈沐资本/rules/低吸选标_W2.md` | W09 SSOT |
| W2 低吸操作 | `10_⚡Now/01_💰弈沐资本/rules/W2_低吸操作.md` | W09 SSOT |
| 流动性硬筛 | `10_⚡Now/01_💰弈沐资本/rules/流动性硬筛.md` | W12 SSOT |
| 当前仪表盘 | `10_⚡Now/01_💰弈沐资本/live-dashboard.html` | 代码迁移源 + mergeData 逻辑源 |
| 数据看板（Dataview） | `10_⚡Now/01_💰弈沐资本/references/数据看板.md` | 确认新旧不冲突 |
| 复盘笔记 | `10_⚡Now/01_💰弈沐资本/复盘笔记/W19_第19周/` | Layer 1 数据源 |
| 板块涨停日志 | `10_⚡Now/01_💰弈沐资本/板块涨停日志.md` | Layer 1 板块数据源 |
| **🆕 数据生成脚本** | `10_⚡Now/01_💰弈沐资本/scripts/gen_dashboard_data.py` | Layer 1 基线数据管线 |
| **🆕 实时轮询脚本** | `10_⚡Now/01_💰弈沐资本/scripts/poll_iwencai.py` | Layer 2 实时数据管线 |
| **🆕 兜底同步脚本** | `10_⚡Now/01_💰弈沐资本/scripts/sync_embedded.py` | Layer 0 每日同步 |

### 9.3 四方评审摘要

#### 洋米评审摘要（2026-05-10）

**评审维度**：产品完整性、交易模型外化、组件间逻辑一致性、SSOT 路径验证、实施计划风险、A 股颜色惯例、Dify 集成。

**发现 4 个 Blocker → 全部写入 v2.0 正文**：
1. 缺少单组件 JS 报错隔离 → §5.3 错误状态 + §6.3 生命周期 try-catch
2. W03 缺少 risk 订阅声明 → §3.2 W03 dataPaths 补全
3. Core-连板.md/Core-趋势.md 路径确认 → 黑米已验证：位于 Vault 根目录
4. DataStore 全链路验证门控 → §7 Phase 1 末尾门控清单

**其他关键建议**：午盘复核 → 扩展 W09（采纳）；W06/W07 字段统一（采纳）；情绪值颜色区分（采纳）；localStorage key 集中声明（采纳）；dataAdapter 预留（采纳）。

---

#### 黑米评审摘要（2026-05-10）

**评审维度**：技术选型（GridStack CDN）、组件拆分粒度、DataStore 订阅模式、CSS 变量完整性、实施顺序合理性、可维护性、性能风险。

**发现 3 个 Blocker → 全部写入 v2.0 正文**：
1. 单组件错误隔离 → §5.3 + §6.3
2. DataStore 全链路验证门控 → §7 Phase 1
3. dashboard_live.json 数据源未就位 → §7 稳米任务 1.9

**其他关键建议**：W14+W15 合并 → 不采纳（复盘场景分开更灵活）；CSS 补 3 变量（采纳）；实施顺序调整（W14 先做，采纳）；性能优化（防抖+拖拽暂停，采纳）；Custom Elements 评估 → 记录不采纳。

---

#### 稳米评审摘要（2026-05-10）

**评审维度**：数据管线可行性、SSOT 溯源完整性、mergeData() 迁移风险、gen_dashboard_data.py 改造、数据容错、实施分工、运维影响。

**发现 3 个 Blocker → 全部写入 v2.0 正文**：
1. gen_dashboard_data.py 不存在 → §4.1 + §7 Phase 1.8
2. dashboard_live.json 生成方案不存在 → §4.1 + §7 Phase 1.9
3. mergeData() DOM→DataStore.manualData 接口变更 → §4.2 manualData API + §7 Phase 1.10

**其他关键建议**：5s 刷新不现实 → 下调为 15-30s（采纳）；EMBEDDED_DATA 过时 → sync_embedded.py 每日同步（采纳）；溯源表负责人修正（采纳）；CLOSE_DATA → initialBase 快照（采纳）；复盘笔记字段未完整提取（记录，后续迭代）。

---

#### 紫米评审摘要（2026-05-09）

**评审维度**：UI/UX 设计（对照 Sentry/Kraken/Linear）、技术栈选型（6 维度）。

**发现 3 个 Blocker → 全部写入 v2.0 正文**：
1. 阴影体系仅 2 级 → 升级为 4 级 + 色温偏蓝黑（采纳 4 级，非 6 级）
2. 缺少"5 秒规则" → §5.0 信息优先级 + §5.6 盘前预设重排（采纳）
3. 缺少系统鲁棒性 KPI → 写入 §8 验收标准，不单独建 Runbook（采纳概念）

**其他关键建议**：交互四态定义（采纳）；字体 Label uppercase+letter-spacing（采纳）；数据新鲜度指示器（采纳）；紫色高亮色（采纳）；Custom Elements v1 升级 → 不采纳；Inter 字体栈替换 → 不采纳（冲突零构建原则）；960px 分屏断点（采纳）；W11 偏好标注（采纳）。

### 9.4 修订记录

| 版本 | 日期 | 变更摘要 |
|------|------|---------|
| v1.0-draft | 2026-05-09 | 初稿，待四方评审 |
| v1.0-reviewed | 2026-05-10 | 并入洋米/黑米/稳米/紫米四方评审意见（2233 行） |
| **v2.0** | **2026-05-10** | **正式施工蓝图**。四方评审通过，7 Blocker 全部写入规范，8 Important 纳入改进，目录结构补全（scripts/assets），4 套预设重排，刷新频率下调，SSOT 溯源表修正 |

---

## 10. 开工前检查清单

以下 7 个 Blocker 必须在 Phase 1 开始前确认完成，才能正式进入实施。

| # | Blocker | 描述 | 负责人 | 验证方式 | 状态 |
|---|---------|------|--------|---------|------|
| B1 | **错误隔离机制规范** | YiMuWidget render() try-catch + 兜底 UI 规格写入 PRD §5.3 §6.3 | 黑米 | PRD 文档中存在对应的规范段落 | ☐ |
| B2 | **DataStore 全链路验证门控** | Phase 1 末尾门控清单写入 PRD §7，7 项验证全部通过才能进 Phase 2 | 稳米+黑米 | Phase 1 结束时逐项打勾 | ☐ |
| B3 | **gen_dashboard_data.py 脚本创建** | 复盘笔记 frontmatter + style_detect.py + 板块日志 → dashboard_data.json | 稳米 | 运行脚本 → diff 输出与预期一致 | ☐ |
| B4 | **poll_iwencai.py 轮询脚本 + 定时任务** | iwencai Q1/Q2/Q4 轮询 → dashboard_live.json，频率大盘 30s/个股 15s/板块 60s | 稳米 | 脚本成功运行至少一次 + cron/launchd 配置确认 | ☐ |
| B5 | **DataStore API 文档交付** | subscribe/manualData.set/adapter 接口签名文档 | 稳米 | 黑米确认可基于此文档开始组件开发 | ☐ |
| B6 | **阴影体系 CSS 变量** | 4 级阴影（card/elevated/drag/modal）+ 色温 `rgba(10,14,20,x)` 写入 theme.css | 黑米 | DevTools 检查 :root 变量完整 | ☐ |
| B7 | **盘前预设布局重排** | pre-market.json 按 5 秒规则重排：W02 左上 → W14 → W03 → W06 → W04/W05，W01 压缩为 12×0.5 | 黑米 | 浏览器打开 → 盘前预设 → 5 秒内看到风格分数+风控+仓位 | ☐ |

---

> **PRD 状态**：v2.0 正式施工蓝图 —— 四方评审已完成，7 Blocker 全部归档。实施流程：完成上方检查清单 → `writing-plans` 拆任务 → `executing-plans` 分批实施。
>
> **下一步**：稳米确认 B3/B4/B5，黑米确认 B1/B6/B7，全部打勾后启动 Phase 1。
