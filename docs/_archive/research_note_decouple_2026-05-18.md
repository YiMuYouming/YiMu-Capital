# 复盘笔记解耦调研报告

**日期**: 2026-05-18  
**调研人**: 洋米  
**范围**: 周五完整笔记 (5/15) + 周一模板笔记 (5/18) + 全量管线 API

---

## 一、当前笔记中"人在贴但机器能拿"的字段清单

### 1.1 Frontmatter（26 字段）

| # | 字段 | 5/15 实际值 | 5/18 实际值 | 数据来源 | 管线覆盖 |
|---|------|-----------|-----------|---------|---------|
| 1 | 涨停家数 | 72 | 待收盘 | 同花顺/问财收盘数 | ✅ baseline.market |
| 2 | 跌停家数 | 44 | 待收盘 | 同上 | ✅ baseline.market |
| 3 | 炸板率 | 41.30% | 待收盘 | 问财 | ✅ baseline.market + iwencai |
| 4 | 封板率 | 58.70% | 待收盘 | 问财 | ✅ baseline.market + iwencai |
| 5 | 整体晋级率 | 10.91% | 待收盘 | 问财/手工算 | ✅ baseline.sentiment |
| 6 | 一进二晋级率 | 2.26%(3/133) | 待收盘 | 手工算 | ✅ baseline.sentiment (style_detect) |
| 7 | 二进三晋级率 | 18.18%(2/11) | 待收盘 | 手工算 | ✅ baseline.sentiment |
| 8 | 三进四晋级率 | 50%(2/4) | 待收盘 | 手工算 | ✅ baseline.sentiment |
| 9 | 情绪值 | 32% | 33% | 同花顺情绪指标 | ✅ baseline.sentiment |
| 10 | 上证指数 | 4135.39 | 4140.46 | 同花顺 | ✅ baseline.market |
| 11 | 上证涨幅 | -1.02% | +0.12% | 同花顺 | ✅ baseline.market |
| 12 | 市场量能 | 3万亿（-1%） | 2万亿（-7%） | 同花顺/手工算同比 | ✅ baseline.market (值) / ⚠️ 同比需计算 |
| 13 | 最高板 | 6板（蒙娜丽莎） | 6板 | 手工数板 | ✅ baseline.sentiment + iwencai |
| 14 | 次高板 | 5板（利仁科技） | 4板 | 手工数板 | ✅ baseline.sentiment |
| 15 | 连板风险值 | 0.64(高) | 0.27（低） | 问财/手工算 | ✅ baseline.sentiment + iwencai |
| 16 | 昨日涨停收益 | -0.90% | 1.14% | 问财 | ✅ baseline.sentiment + iwencai |
| 17 | 昨日连板收益 | 1.16% | 5.16% | 问财 | ✅ baseline.sentiment |
| 18 | 昨日炸板收益 | -0.70% | 0.41% | 问财 | ✅ baseline.sentiment |
| 19 | 赚钱效应 | 差 | 差 | 手工判定 | ✅ baseline.sentiment + iwencai |
| 20 | 盘后持仓 | 北华+领益 | 领益 | 手工汇总 | ⚠️ 可从 positions + live_quotes 拼 |
| 21 | 连板股 | "蒙娜丽莎6板/..." | 待收盘 | 手工筛连板 | ⚠️ iwencai 可查连板股列表 |
| 22 | 上证20日线 | "走平(4118.61)" | 待确认 | 手工看 | ⚠️ 管线未直接存，可算 |
| 23 | 趋势走强板块数 | 4 | 待确认 | 手工数 | ⚠️ 交易系统内部指标 |
| 24 | 大市值赚钱比例 | 40 | 待确认 | 手工算 | ⚠️ style_detect 内部有 |
| 25 | 昨日涨停家数3日均值 | 107 | 待收盘 | 手工算 | ✅ 可从 sentiment_auto.json 算 |
| 26 | 风格分数验证 | "偏连板" | 待收盘 | style_detect 结果 | ✅ baseline.style |

**管线覆盖率**: 22/26 (85%) 完全覆盖，4/26 (15%) 部分覆盖或可计算。  
**0 个完全无法自动化的字段**。

### 1.2 表1：大盘全景（5 节点 × 7 列 = 35 格/天）

| 列 | 数据源 | 管线覆盖 |
|----|--------|---------|
| 情绪 | 同花顺情绪指标 | ✅ T3 实时计算 + sentiment_auto.json 30min 快照 |
| 上证(%) | 同花顺 | ✅ quotes API 5s 实时 |
| 涨/跌停 | 同花顺 | ✅ breadth API 30s |
| 量能 | 同花顺/手工算 | ✅ index API 5s |
| 涨跌比 | 同花顺 | ✅ breadth API 30s |
| 总竞价涨幅 | 手工看 | ⚠️ snapshot_auction.py 有 |
| 关键异动 | 人工观察 | ❌ 必须人填 |

**管线覆盖率**: 6/7 列 (86%)

### 1.3 表2：情绪高标（13 指标 × 4 时间点 = 52 格/天）

| 指标 | 管线覆盖 |
|------|---------|
| 竞价强势家数 | ✅ snapshot_auction.py |
| 涨停收益 | ✅ iwencai 2min + sentiment_auto.json |
| 连板收益 | ✅ iwencai |
| 炸板收益 | ✅ iwencai |
| 封板率 | ✅ iwencai |
| 炸板率 | ✅ iwencai |
| 整体晋级率 | ✅ iwencai |
| 一进二/二进三/三进四晋级率 | ✅ style_detect → baseline.sentiment |
| 赚钱效应 | ✅ iwencai |
| 梯队 | ⚠️ iwencai 可查连板分布 |
| 最高板/次高板 | ✅ iwencai |
| 竞价验证结论 | ⚠️ 可规则判定，但需人确认 |

**管线覆盖率**: 11/13 指标 (85%)

### 1.4 其他表格

| 表格 | 管线覆盖 | 说明 |
|------|---------|------|
| 涨停结构 | ⚠️ 部分 | 板块名/涨停数可自动；梯队/龙头/状态需人判定 |
| 连板股列表 | ✅ | iwencai "连板股票" 可直接出列表 |
| 风格检测结果 | ✅ 100% | baseline.style dim1~4 全覆盖 |
| 账户风控 | ⚠️ 部分 | 当日盈亏需 P&L 计算，连亏天数可自动 |

---

## 二、管线数据能供给笔记什么

### 2.1 数据源对照表

| 笔记需要的字段 | 管线数据源 | 取值路径 | 格式 | 刷新频率 |
|-------------|----------|---------|------|---------|
| 涨停家数 | `/api/baseline` | `market.涨停家数` | int | 每日（复盘基线） |
| 跌停家数 | `/api/baseline` | `market.跌停家数` | int | 每日 |
| 炸板率 | `/api/baseline` 或 `/api/live/iwencai` | `market.炸板率` 或 `炸板率` | float (小数 0-1) | 每日 / 2min |
| 封板率 | 同上 | 同上 | float | 每日 / 2min |
| 晋级率（整体） | `/api/live/iwencai` | `晋级率` | float | 2min |
| 情绪值 | `/api/baseline` | `sentiment.情绪值` | int/float (0-100) | 每日 |
| 情绪区间 | `/api/baseline` | `sentiment.情绪区间` | 冰点/低迷/主升/强势/高潮 | 实时计算 |
| 上证指数 | `/api/baseline` | `market.上证指数` | float | 每日 |
| 上证涨幅 | `/api/baseline` | `market.上证涨幅` | float | 每日 |
| 市场量能 | `/api/baseline` | `market.市场量能` | string | 每日 |
| 最高板 | `/api/baseline` 或 `/api/live/iwencai` | `sentiment.最高板` 或 `最高板` | int | 每日 / 2min |
| 昨日涨停收益 | `/api/live/iwencai` | `昨日涨停收益` | float (%) | 2min |
| 赚钱效应 | `/api/live/iwencai` | `赚钱效应` | 好/一般/差 | 2min |
| 连板风险值 | `/api/live/iwencai` | `连板风险值` | float (0-1) | 2min |
| 风格检测 | `/api/baseline` | `style.*` | struct | 每日 |
| 5节点情绪时间线 | `sentiment_auto.json` | `[].node → {情绪值, 涨停收益, 封板率...}` | array | 30min |
| 自选池 | `pools.json` | `lianban_pool[] / trend_pool[]` | array | 每日 |

### 2.2 精准度评估

| 字段 | 管线值 vs 人填值 | 差异风险 |
|------|----------------|---------|
| 涨停家数/跌停家数 | 收盘最终值 vs 盘中变化值 | 低（收盘数据为准） |
| 情绪值 | T3 实时计算(涨跌比) vs 手工看同花顺 | 中（阈值边界可能偏差） |
| 晋级率 | iwencai 自动算 vs 手工数 | 低（iwencai 更准） |
| 最高板 | iwencai 取max vs 手工数 | 低 |
| 风格分数 | style_detect.py 计算 vs 人工校验 | 需校验 |

---

## 三、三个最痛点（按优先级）

### 🥇 痛点1：表1+表2 合计 87 格/天纯体力活

表1 大盘全景（35格）+ 表2 情绪高标（52格）= 87 个单元格，每个都要在交易时段手工看数据→填表。每天至少 20-25 分钟纯体力活。这些数据管线全有——iwencai 2min 轮询 + sentiment_auto.json 30min 快照已经覆盖了绝大部分。填完也没人回头看——复盘重点是节点说明文字，不是表格里的数字。

### 🥈 痛点2：Frontmatter 26 字段，85% 管线已有，但人还在贴

每周五天，每天贴同样的 26 个字段。520 次重复操作/月。大部分是"打开同花顺→看一眼数字→敲进笔记"的条件反射动作。贴错了（如北华主力方向相反）红方对抗才发现。

### 🥉 痛点3：Pipeline → 笔记的数据流是反的

当前数据流向是：**笔记（人填数据）→ gen_dashboard_data.py → dashboard_data.json → 看板**。这意味着：
- 管线数据比人填的更实时、更准确
- 但管线数据无法回写笔记
- 人填的数据是"二手数据"——看过管线后手抄

正确流向应该是：**Pipeline 自动采集 → 笔记生成时自动填充 → 人只写定性内容**。

---

## 四、实现方案对比

### 方案A：gen_dashboard_data.py 反向写笔记

笔记做成模板（含 `{{ pipeline.涨停家数 }}` 占位符），gen 脚本新增 `--fill-note` 模式：
1. 读模板 → 2. 拉管线数据 → 3. 替换占位符 → 4. 写出部分填充的笔记

| 优点 | 缺点 |
|------|------|
| 已有 gen 脚本，扩展即可 | 模板机制引入新语法 |
| 不依赖 bridge 在线 | 占位符替换容易出 bug |
| 一次性生成，离线可用 | 需要新建模板文件 |

### 方案B：笔记 HTML 生成时调 API

Portal 同步流程（`"同步门户"`）中，HTML 生成时直接 curl API 获取数据：
1. 读笔记 Markdown（人只写定性） → 2. curl baseline + iwencai → 3. 数据+文字合并渲染 HTML

| 优点 | 缺点 |
|------|------|
| 对笔记零侵入 | 需要 bridge 在线 |
| 数据和文字天然分离 | HTML 生成脚本需重写 |
| Portal 已有 HTML 管线 | 离线看笔记时数据缺失 |

### 方案C：新增 `fill_review_note.py` 独立脚本

新建独立脚本，盘后运行一次：
1. 读当天空模板 → 2. 读 dashboard_data.json + sentiment_auto.json + pools.json → 3. 填充 frontmatter 和表1/表2 → 4. 输出半成品笔记

| 优点 | 缺点 |
|------|------|
| 不碰 gen 脚本，零侵入 | 多一个脚本要维护 |
| 直接操作文件，简单粗暴 | 和 gen 共享数据逻辑 |
| 可被 Portal 同步流程复用 | 需要和 gen 的输出时间协调 |

### 建议

**方案C（独立脚本）作为第一步**，理由：
- 风险最低：不改 gen_dashboard_data.py，不改笔记格式
- 见效最快：一个单文件脚本，读 pipeline 数据文件 → 写 Markdown
- 验证后再考虑升级到方案A（模板化）或方案B（HTML 直调 API）

---

## 五、和 Portal 的关系

Portal (`~/Documents/YM_Capital/portal/`) 已有完整 HTML 生成管线：
- `review-notes/` 目录下 36 个 HTML 日报 + 多个周报/月报
- 同步流程：读 Vault .md → 转 HTML → 更新索引
- 当前 HTML 内容完全依赖 Markdown（数据嵌在 Markdown 里）

解耦后 Portal 受益最大：
- HTML 生成时可以从管线 API 拿**最新数据**，不用依赖笔记里人贴的收盘数据
- 数据表格可以自带**最新鲜度标记**
- 历史 HTML 不受影响

---

## 六、建议的下一步

1. **立即**：创建 `scripts/fill_review_note.py`，实现 frontmatter 26 字段 + 表1 + 表2 的自动填充
2. **短期**：表1/表2 改为一键生成（人只写节点说明文字）
3. **中期**：Portal 同步流程接入管线 API，HTML 数据实时化
4. **长期**：笔记模板化——笔记本身变成纯定性文档，所有数据从管线注入

**量化收益**：每天省 30-40 分钟数据搬运。按每月 20 个交易日算，月省 10-13 小时。
