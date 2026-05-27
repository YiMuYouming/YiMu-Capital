# 弈沐仪表盘 22组件 全量数据溯源审计

> 2026-05-20 | 洋米 | 用途：验证同域数据是否同源，SSOT 一致性

---

## 数据域 SSOT 总览

| 数据域 | SSOT（唯一源头） | 频率 | 消费组件 |
|--------|-----------------|------|---------|
| 指数行情 | PyTDX → CACHE["live_index"] → d.live_index | 5s | W04 W08 W09 W11 |
| 个股实时价 | PyTDX → CACHE["live_quotes"] → d.live_quotes | 5s | W06 W08 W09 W10 W12 W13 W14 W15 W21 W22 PnL |
| 涨跌分布 | PyTDX → CACHE["breadth"] → d.live_breadth | 30s | W04 |
| 北向资金 | 同花顺hsgtApi → CACHE["northbound"] → d.northbound | 60s | W04 |
| 板块实时 | PyTDX → CACHE["live_sectors"] → d.live_sectors | 30s | W10 |
| 15min量价 | PyTDX → CACHE["上证/深证/创业15min"] | 60s | W11 |
| 情绪指标 | iwencai 10min → CACHE["iwencai"] → d.iwencai | 10min | W04 W08 W21 |
| 竞价快照 | iwencai OpenAPI → auction_snapshot.json | 9:28日次 | W06 W07 |
| 情绪节点 | sentiment_snapshot → sentiment_auto.json | 30min | W05 |
| 风格检测 | style_detect.py → gen → d.style | 每日gen | W02 W03 |
| 连板池 | 复盘笔记附录A → gen → d.lianban_pool | 每日gen | W08 W09 W10 W12 W21 |
| 趋势池 | 复盘笔记附录A → gen → d.trend_pool | 每日gen | W08 W09 W10 W13 |
| 板块清单 | 复盘笔记附录A → gen → d.sectors | 每日gen | W10 |
| 持仓 | gen(盘前)+W15同步(盘中) → d.positions | 每日+实时 | W14 W15 W22 PnL |
| 风控基线 | gen(_compute_risk_from_pnl) → d.risk | 每日gen | W03 W08 W14 |
| PnL曲线 | bridge log_pnl_snapshot → pnl.db → /api/pnl | 5min/日结 | W22 |
| LLM研判 | /api/llm → llm_insights.json | 15min/手动 | W04 W05 W08 W20 |
| 热榜梯队 | 同花顺 → CACHE["hot_list"] → d.hot_list | 5min | W21 |
| 手工录入 | W16 manualData → localStorage + d.pnl | 随录 | W03 W15 W17 W22 |
| 锚定股 | 复盘笔记数据附录 → gen → d.decision.锚定股状态 | 每日gen | W06 W18 |

---

## 逐组件明细

### W01 时段时间线

| 显示数据 | 来源 | 时效 |
|---------|------|------|
| 当前时段标签 | JS Date | 实时 |
| 剩余时间/倒计时 | JS Date | 30s自刷新 |
| 全天进度% | JS Date | 30s |
| 是否为周末 | d.meta.weekday | 每日gen |

**结论：纯前端计算，不依赖外部数据管线。**

---

### W02 风格检测卡

| 显示数据 | store路径 | 数据源 | 时效 |
|---------|----------|--------|------|
| 总分(55) | d.style.总分 | style_detect.py → gen | 每日 |
| 风格(混合偏连板) | d.style.风格 | style_detect.py | 每日 |
| 置信度(52%) | d.style.置信度 | style_detect.py | 每日 |
| 连板占比(57%) | d.style.连板占比 | style_detect.py | 每日 |
| 趋势占比(43%) | d.style.趋势占比 | style_detect.py | 每日 |
| dim1量能(10/25) | d.style.dim1_量能 | style_detect.py iwencai | 每日 |
| dim2连板生态(21/35) | d.style.dim2_连板生态 | style_detect.py iwencai | 每日 |
| dim3趋势(13/25) | d.style.dim3_趋势 | style_detect.py iwencai | 每日 |
| dim4情绪广度(11/15) | d.style.dim4_情绪广度 | style_detect.py iwencai | 每日 |
| 一进二晋级率 | d.style.一进二晋级率 | 复盘笔记frontmatter | 每日 |
| 二进三晋级率 | d.style.二进三晋级率 | 同上 | 每日 |
| 三进四晋级率 | d.style.三进四晋级率 | 同上 | 每日 |
| 持续天数 | d.style.持续天数 | .style_regime_state.json | 每日 |
| 预警 | d.style.预警 | style_detect.py | 每日 |
| 实际执行 | d.style.实际执行 | gen compute_style_execution | 每日 |
| 总仓位上限 | d.style.总仓位上限 | gen _compute_total_cap | 每日 |

**结论：全部来自style_detect.py → gen，单源一致。但晋级率空值频率高（笔记填"—"时依赖回退）。**

---

### W03 三层仓位计

| 显示数据 | store路径 | 数据源 | 时效 |
|---------|----------|--------|------|
| 总仓位上限 | d.style.总仓位上限 | gen | 每日 |
| 连板占比 | d.style.连板占比 | gen | 每日 |
| 趋势占比 | d.style.趋势占比 | gen | 每日 |
| 熔断触发 | d.risk.熔断触发 | gen | 每日 |
| 连亏天数 | d.risk.连亏天数 | gen(_compute_risk_from_pnl) | 每日 |
| 已持仓市值 | 实时计算: d.positions × 实时价 | W15同步+liveQ | 实时 |
| 总资产 | DataStore.manualData['总资产'] | W16手工/W15同步 | 随录 |
| 可用资金 | DataStore.manualData['可用资金'] | W16手工/W15同步 | 随录 |
| 实际执行 | d.style.实际执行 | gen | 每日 |

**结论：风格+风控走gen(每日)，金额走manualData(实时)。正常。**

---

### W04 市场全景

| 显示数据 | store路径 | 数据源 | 时效 |
|---------|----------|--------|------|
| 上证/深证/创业指数 | d.live_index | PyTDX 5s | **实时** |
| 成交额 | d.live_index['成交额'] | PyTDX 5s | **实时** |
| 涨跌比 | d.live_index['上涨/下跌家数'] | PyTDX 5s | **实时** |
| 振幅 | d.live_index['上证指数振幅'] | PyTDX 5s | **实时** |
| 涨跌停 | d.live_breadth['涨停/跌停'] | PyTDX 30s | **实时** |
| 涨跌分布色条 | d.live_breadth | PyTDX 30s | **实时** |
| 情绪值 | 涨跌家数比(前端算) | PyTDX 5s | **实时** |
| 涨停收益 | d.iwencai['昨日涨停收益'] | iwencai 10min | **准实时** |
| 连板收益 | d.iwencai['连板收益'] | iwencai 10min | **准实时** |
| 炸板收益 | d.iwencai['炸板收益'] | iwencai 10min | **准实时** |
| 北向资金 | d.northbound | 同花顺 60s | **实时** |
| 昨日收盘基线 | d.yesterday_baseline | gen | 每日 |
| LLM卡槽 | llm_insights.json | /api/llm | 15min |

**SSOT检查：✅ 全部实时或准实时源，无baseline回退（6c1a418修复后）。**

---

### W05 情绪节点对比

| 显示数据 | 来源 | 时效 |
|---------|------|------|
| 8节点×7指标矩阵 | sentiment_auto.json | 30min快照 |
| 各节点: 上证/情绪值/涨跌比/涨跌停/涨停收益/连板收益/炸板收益 | sentiment_snapshot.py | 30min |
| LLM卡槽 | llm_insights.json | 15min |

**sentiment_snapshot字段来源：**
- 情绪值: PyTDX涨跌家数比(实时算)
- 涨停/连板/炸板收益: CACHE iwencai → baseline兜底
- 涨停家数/跌停家数: CACHE iwencai → baseline兜底
- 封板率/炸板率/晋级率/最高板: CACHE iwencai → baseline兜底

**SSOT检查：✅ 与W04同源(iwencai)。a7becc9修复后已加baseline alt-key兜底。**

---

### W06 竞价5维面板

| 显示数据 | 来源 | 时效 |
|---------|------|------|
| 综合信号灯 | auction_snapshot.json | 9:28日次 |
| 指数竞价(3只) | snapshot_auction.py iwencai OpenAPI | 9:28日次 |
| 涨跌家数(竞价) | snapshot_auction.py iwencai OpenAPI | 9:28日次 |
| 情绪指标(9:25定格) | snapshot_auction.py → iwencai+baseline | 9:28日次 |
| 高标竞价 | snapshot_auction.py iwencai OpenAPI | 9:28日次 |
| 自选池竞价 | snapshot_auction.py: d.lianban_pool+d.trend_pool+d.锚定股 → iwencai指定代码查询 | 9:28日次 |
| 板块竞价 | snapshot_auction.py: d.sectors → iwencai | 9:28日次 |

**SSOT检查：✅ 独立文件auction_snapshot.json，自选池从dashboard_data.json取代码（与W08/W09/W10同源）。**

---

### W07 高潮保护

| 显示数据 | store路径 | 数据源 | 时效 |
|---------|----------|--------|------|
| 竞价情绪值 | d.sentiment.竞价情绪值 | gen/auction | 每日/日次 |
| 保护级别 | 前端判定(≥90/85/80) | JS | 实时计算 |

**结论：简单组件，依赖sentiment.竞价情绪值。**

---

### W08 W1早盘确认

| 显示数据 | store路径 | 数据源 | 时效 |
|---------|----------|--------|------|
| **三件套灯1: 情绪** | d.sentiment['情绪值'] | store.js Step4(涨跌家数比) | **5s实时** |
| **三件套灯2: 涨停收益** | d.iwencai['昨日涨停收益']→d.sentiment兜底 | iwencai 10min | 准实时 |
| **三件套灯3: 标的高开** | liveQ['涨幅']+openQ快照 | PyTDX 5s | **实时** |
| 涨停家数 | d.iwencai→M兜底 | iwencai 10min | 准实时 |
| 最高板 | d.iwencai→S兜底 | iwencai 10min | 准实时 |
| 一进二/二进三/三进四 | d.iwencai→S兜底 | iwencai 10min | 准实时 |
| 赚钱效应 | d.iwencai→S兜底 | iwencai 10min | 准实时 |
| W1连板标的列表 | d.lianban_pool (窗口=W1或空) | gen(每日) | 每日 |
| 各标的实时涨幅/量比 | liveQ | PyTDX 5s | **实时** |
| 龙头存活判定 | liveQ涨幅≥9.5% | PyTDX 5s | **实时** |
| 板块合力 | liveQ 同板块>3%计数 | PyTDX 5s | **实时** |
| 趋势W1 | d.trend_pool + liveQ | gen+PyTDX | 每日+实时 |
| AI盯盘 | llm_insights.json | /api/llm | 15min |

**SSOT检查：⚠️ 晋级率优先级 iwencai(实时) > S(每日gen)。涨停家数/最高板同理。与W04/W05均从iwencai取，一致。W1标的池从gen取(每日)，与W10/W12同源。**

---

### W09 W2实时观察

| 显示数据 | 来源 | 时效 |
|---------|------|------|
| 趋势W2条件 | d.trend_pool + liveQ | gen+PyTDX 5s |
| 连板W2条件 | d.lianban_pool + liveQ | gen+PyTDX 5s |
| 60mMA10回踩/缩量/未大跌 | liveQ + 前端判定 | PyTDX 5s实时 |

**结论：简单组件，与W08/W10/W12/W13同源。**

---

### W10 板块热力

| 显示数据 | store路径 | 数据源 | 时效 |
|---------|----------|--------|------|
| 板块列表+类型 | d.sectors | gen(复盘笔记) | 每日 |
| 板块实时涨跌 | d.live_sectors | PyTDX 30s | **实时** |
| 板块距MA5 | d.live_sectors['距MA5'] | PyTDX 30s | **实时** |
| 板块个股+涨幅 | d.lianban_pool+d.trend_pool+liveQ | gen+PyTDX | 每日+实时 |
| 行业净流入TOP5 | d.sector_inflow | ym_data_pipeline 5min | **实时** |
| LLM卡槽 | llm_insights.json | /api/llm | 15min |

**SSOT检查：⚠️ 板块列表来自sectors(每日gen)，实时涨跌来自live_sectors(PyTDX)。两者板块名可能不一致（别名问题），导致"距MA5"偶尔不显示。**

---

### W11 15min量价

| 显示数据 | 来源 | 时效 |
|---------|------|------|
| 上证/深证/创业15min量比柱 | d['上证/深证/创业15min'] | PyTDX 60s |
| 最新时段标尺卡 | d.live_index | PyTDX 5s |
| 全日累计成交额 | d.live_index | PyTDX 5s |

**结论：全部PyTDX，实时。**

---

### W12 连板自选池

| 显示数据 | 来源 | 时效 |
|---------|------|------|
| 标的/板块/角色/操作 | d.lianban_pool | gen(每日) |
| 涨幅/最新价/量比/换手 | liveQ | PyTDX 5s |
| MA10(60m)/MA5 | liveQ | PyTDX 5s |

**结论：池子每日gen，行情实时PyTDX。✅**

---

### W13 趋势自选池

| 同上，仅数据源改为 d.trend_pool | 结论：与W12对称。✅ |

---

### W14 账户风控

| 显示数据 | 来源 | 时效 |
|---------|------|------|
| 实时盈亏(大字) | activePos × liveQ - totalCost | **实时**(5s) |
| 持仓市值/可用资金/仓位 | liveQ + manualData | 实时+随录 |
| 单日熔断 | d.risk.单日熔断线(-3%) + 实时盈亏判定 | 每日+实时 |
| 连亏天数 | d.risk.连亏天数 | gen(_compute_risk_from_pnl) |
| 周回撤 | d.risk.周累计回撤 | gen(_compute_risk_from_pnl) |
| 月回撤 | d.risk.月累计回撤 | gen(_compute_risk_from_pnl) |

**SSOT检查：⚠️ activePos过滤与W15独立（各自写过滤逻辑，但都检查"清+删"）。应统一过滤逻辑。持仓数据源同W15(d.positions+manualData._positions merge)。**

---

### W15 持仓+操作+清仓

| 显示数据 | 来源 | 时效 |
|---------|------|------|
| 持仓列表(标的/市值/盈亏) | basePos + manualData._positions merge × liveQ | gen+W15同步+PyTDX |
| 总资产/可用资金 | manualData | W16/W15同步 |
| 今日操作 | manualData['_今日操作'] | W15录入 |
| 清仓跟踪(7日内) | cleared positions × liveQ | gen+PyTDX |

**结论：SSOT为manualData._positions(盘中实时)，gen baseline兜底。✅**

---

### W16 报数面板

| 显示数据 | 来源 | 时效 |
|---------|------|------|
| 15个手动字段 | DataStore.manualData | 随录 |
| 自动计算: 总资产 | 持仓市值+可用资金 | 实时计算 |

**结论：纯手工录入，写入manualData → localStorage持久化。**

---

### W17 今日操作

| 显示数据 | 来源 | 时效 |
|---------|------|------|
| 操作列表 | manualData['_今日操作'] | W15录入 |

**结论：W15子视图，同源。✅**

---

### W18 锚定股状态

| 显示数据 | 来源 | 时效 |
|---------|------|------|
| 锚定股列表+灯+状态 | d.decision.锚定股状态 | gen(每日) |
| 各股实时涨幅 | liveQ | PyTDX 5s |

**结论：✅**

---

### W19 午盘复核

| 显示数据 | 来源 | 时效 |
|---------|------|------|
| V反场景/状态 | d.decision.盘中.V反检测 | gen(每日) |
| 双冰检测(前日/今日情绪) | d.decision.盘中.双冰检测 + d.sentiment | gen(每日) |

**结论：✅**

---

### W20 AI盯盘(W20网格摘要 + llm-chat浮动框)

| 显示数据 | 来源 | 时效 |
|---------|------|------|
| 最新研判摘要 | llm_insights.json | 60s轮询 |
| 信号统计 | llm_insights.json signals | 60s |
| 浮动聊天框 | /api/llm(manual) + /api/llm/history | 实时交互 |
| 自动研判 | bridge APScheduler 840s | 15min |
| 全盘数据快照 | bridge _build_full_snapshot() | 研判时构建 |

**_build_full_snapshot()读取：CACHE(live_index/live_quotes/iwencai/hot_list) + dashboard_data.json(全部)。SSOT与页面组件一致。✅**

---

### W21 涨停梯队

| 显示数据 | 来源 | 时效 |
|---------|------|------|
| 涨停列表(名称/涨幅/换手/成交额) | d.hot_list | 同花顺 5min |
| 题材归因(reason tags) | d.hot_list.reason_stats | 同花顺 5min |
| 连板性质(首板/2连板/3连板) | d.iwencai['连板股列表'] → zt_history localStorage | 实时+缓存 |
| 日期切换(最近5天) | zt_history | localStorage累积 |
| LLM卡槽 | llm_insights.json | 15min |

**SSOT检查：✅ 热榜走hot_list(同花顺)，连板判定走iwencai+本地缓存。**

---

### W22 账户收益曲线

| 显示数据 | 来源 | 时效 |
|---------|------|------|
| 今日PnL曲线 | /api/pnl?range=today (intraday_snapshots) | 5min |
| 周/月/季/年/累计TWR | /api/pnl?range=all (daily_summary) | 日结 |
| 基准指数对比 | daily_summary sh_pct/sz_pct/cy_pct | 日结 |
| KPI卡:当前资产/总资产 | d.pnl+manualData | 随录 |
| 今日浮动盈亏 | liveQ × d.positions 实时算 | PyTDX 5s |
| 历史最大回撤 | daily_summary TWR连乘+峰谷差 | 日结 |
| 抽屉损益明细 | daily_summary computePeriod | 日结 |

**PnL数据源：**
- intraday_snapshots: bridge log_pnl_snapshot()每5min写 → 读positions+liveQ+pnl_history计算
- daily_summary: gen基线收盘后写(15:10)
- 持仓: d.positions(gen+W15同步)
- 可用资金: d.pnl(W15同步→_preserve_pnl保留)

**SSOT检查：⚠️ W22独立读d.positions+d.pnl，计算逻辑与W14/W15独立。但数据源一致。PnL计算已验证正确(f6267fb修复基准,bb5dc04修复持仓过滤)。**

---

## SSOT 交叉验证结论

### ✅ 一致的域（同域不同组件取同源）

| 域 | 消费组件 | 一致性 |
|----|---------|--------|
| 指数行情(live_index) | W04 W08 W09 W11 | ✅ 同源 PyTDX |
| 个股实时(live_quotes) | W08 W09 W10 W12 W13 W14 W15 W21 W22 | ✅ 同源 PyTDX |
| 情绪指标(iwencai) | W04 W08 W21 | ✅ 同源 CACHE["iwencai"] |
| 连板池 | W08 W09 W10 W12 W21 | ✅ 同源 d.lianban_pool(gen) |
| 趋势池 | W08 W09 W10 W13 | ✅ 同源 d.trend_pool(gen) |
| 持仓 | W14 W15 W22 | ✅ 同源 d.positions(gen+W15同步) |
| 风控 | W03 W08 W14 | ✅ 同源 d.risk(gen) |
| LLM研判 | W04 W05 W08 W20 | ✅ 同源 llm_insights.json |

### ⚠️ 需要注意的

| 问题 | 影响 | 建议 |
|------|------|------|
| W05 sentiment_snapshot 有 baseline 兜底 | 下午节点可能显示昨日数据 | 可接受，收盘后无实时意义 |
| W10 板块名别名不一致 | 实时涨跌(live_sectors)和SSOT板块(sectors)偶尔对不上 | 已有ALIAS映射表，持续补充 |
| W14/W15 持仓过滤各自实现 | 两处都有 '清'+'删' 过滤，代码重复 | 非bug，但维护成本高 |
| W22 PnL 使用 _preserve_pnl 防覆盖 | gen每天一次守护防止覆盖 | 已稳定，无需改 |
