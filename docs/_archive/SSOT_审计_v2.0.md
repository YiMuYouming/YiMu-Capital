# 数据看板 SSOT 全量审计 v2.0

> 最后更新：2026-05-11 22:00 | 复盘笔记解析全链路验证通过

## 一、数据通路分类

### 通路 1：通达信 PyTDX — 实时（5s/30s/5min）
**命令**：`python3 scripts/poll_live.py --watch`
**覆盖**：14只个股 + 3大指数 + 6/8板块 + 15min量价

| 数据字段 | 刷新 | 消费者 | 备注 |
|---------|------|--------|------|
| 个股 最新价/涨幅/量比 | 5s | W08 W09 W12 W13 W15 | merge() 覆盖 pool items |
| 换手率 | — | — | TDX 无法解码，回退 Layer 1 基线 |
| 上证/深证/创业 指数+涨幅+成交额 | 5s | W04 W09 W11 | live_index |
| 全市场成交额 | 5s | W04 | 上证+深证（不含创业，防重复） |
| 板块涨跌幅 | 30s | W09 W10 | TDX 板块指数 88xxxx |
| 板块 主力净流入/5日线/涨停数 | — | — | TDX 无此字段，显示"—" |
| 15min量价（三指数） | 5min | W11 | 柱状图 + 较昨日量比 + 标尺卡 + 累计行 |

### 通路 2：问财 iwencai — 节点（一次性）
**命令**：`poll_iwencai.py --auction`（9:26）/ `--review`（盘后）

| 用途 | 时机 | 产出 | 数据字段 |
|------|------|------|---------|
| 竞价5维 | 9:26 | 大盘竞价+情绪+高标+锚定+方向 | decision.竞价.* |
| 竞价研判 | 9:26 | 结论/高潮保护/动作/灯号（规则引擎） | decision.竞价 |
| 热榜 | 盘后 | 人气榜 | iwencai_review.json |
| 龙虎榜 | 盘后 | 席位/买卖金额 | iwencai_review.json |
| 连板生态 | 盘后 | 晋级率/梯队 | iwencai_review.json |

### 通路 3：复盘笔记 — 每日基线（Layer 1）
**命令**：`python3 scripts/gen_dashboard_data.py`
**解析流程**：

```
复盘笔记.md
  ├─ YAML Frontmatter 解析
  │   ├─ 上证指数/上证涨幅/市场量能/涨跌比/涨停家数/跌停家数/炸板率/封板率 → market.*
  │   ├─ 情绪值/情绪区间/昨日情绪/情绪变化/赚钱效应 → sentiment.*
  │   ├─ 昨日涨停收益/昨日炸板收益/连板收益/连板风险值/晋级率 → sentiment.*
  │   ├─ 最高板/次高板/连板梯队/竞价情绪值 → sentiment.*
  │   ├─ 当日盈亏/当日盈亏金额/周累计回撤/月累计回撤/连亏天数 → risk.*
  │   ├─ 熔断触发/周回撤触发/单日熔断线/周回撤预警/月回撤预警 → risk.*
  │   └─ 当前时段/W1状态/W2状态/周五 → time_window.*
  │
  ├─ style_detect.py 子进程
  │   └─ 总分/风格/连板占比/趋势占比/dim1_量能/dim2_连板生态/dim3_趋势 → style.*
  │
  ├─ 规则引擎 compute_style_execution()
  │   ├─ 熔断 → 全部归零
  │   ├─ 连亏≥2 → 强制空仓
  │   ├─ 晋级率<30% → 连板硬卡
  │   ├─ 周五 → 趋势上限15%
  │   └─ → style.实际执行.*
  │
  ├─ ## 数据附录 解析（Markdown 表格）
  │   ├─ ### 持仓明细 → positions[]
  │   ├─ ### 连板自选池 → lianban_pool[]
  │   ├─ ### 趋势自选池 → trend_pool[]
  │   ├─ ### 板块状态 → sectors[]
  │   ├─ ### 竞价5维 → decision.竞价
  │   ├─ ### W1早盘确认 → decision.早盘
  │   ├─ ### W2盘中跟踪 → decision.盘中
  │   ├─ ### 今日操作 → decision.今日操作
  │   └─ ### 锚定股状态 → decision.锚定股状态
  │
  └─ → dashboard_data.json
```

### 通路 4：手工录入 — W16 报数面板（Layer 3）
**存储**：localStorage `dash_inputs`

| 字段 | 来源 | 消费者 |
|------|------|--------|
| 总资产 | 券商APP | W03 |
| 上涨/下跌家数 | 同花顺APP | W05 |
| 情绪值 | 同花顺APP / 涨跌反推 | W05 |
| 涨停收益/连板收益/炸板收益 | 同花顺APP | W05 |
| 晋级率 | 同花顺APP | W05 W08 |
| 封板率 | 同花顺APP | W05 |
| 涨停家数/跌停家数 | 同花顺APP | W04 W05 |
| 最高板/次高板/梯队 | 同花顺APP | W05 |
| 赚钱效应 | 同花顺APP / 自动判定 | W05 |
| 风险值 | iwencai / LLM | W05 |

### 通路 5：LLM 研判 — 洋米（阶段写入）
| 任务 | 输入 | 写入位置 | 状态 |
|------|------|---------|------|
| 竞价5维判定 | iwencai 竞价数据 | decision.竞价 | ✅ 已做 |
| W1 早盘条件判定 | live_quotes + decision.早盘 | decision.早盘 | ⏳ |
| W2 盘中条件判定 | live_quotes + live_sectors | decision.盘中 | ⏳ |
| V反/双冰检测 | sentiment | decision.盘中 | ⏳ |
| 风格校准建议 | style 波动 | style.实际执行 | ⏳ |

---

## 二、19 组件验收 Checklist

| # | 组件 | 数据通路 | 状态 | 日期 | 备注 |
|---|------|---------|------|------|------|
| W01 | 时段时间线 | 复盘笔记 + 系统时钟 | ✅ | 5/11 | — |
| W02 | 风格检测卡 | 复盘笔记 → style_detect | ✅ | 5/11 | 74分趋势行情，连板硬卡触发 |
| W03 | 三层仓位计 | 复盘笔记 + W16总资产 | ✅ | 5/11 | 趋势100%, 首笔≤10% |
| W04 | 市场全景 | PyTDX实时 + 复盘基线 | ✅ | 5/11 | 上证4225, 成交额差"—" |
| W05 | 情绪仪表盘 | 复盘笔记 + W16手工 | ✅ | 5/11 | 情绪56%主升 |
| W06 | 竞价5维 | iwencai节点 + 规则引擎 | ✅ | 5/11 | poll_iwencai --auction 自动 |
| W07 | 高潮保护 | iwencai节点(竞价情绪) | ✅ | 5/11 | 与W06同步, sentiment.竞价情绪值已打通 |
| W08 | W1早盘确认 | 复盘框架 + PyTDX实时 | ⚠️ | — | 条件判定待LLM Hook |
| W09 | W2实时观察 | 复盘框架 + PyTDX实时 | ⚠️ | — | 条件判定待LLM Hook |
| W10 | 板块热力 | 复盘结构 + PyTDX涨跌 | ⚠️ | 5/11 | 5板块涨跌幅正常, 缺主力/5日线/涨停数 |
| W11 | 15min量价图 | PyTDX 5min + 日线 | ✅ | 5/11 | 三指数+标尺卡+累计行 |
| W12 | 连板自选池 | 复盘 + PyTDX实时覆盖 | ✅ | 5/11 | 7只, 全字段完整 |
| W13 | 趋势自选池 | 复盘 + PyTDX实时覆盖 | ✅ | 5/11 | 9只, 全字段完整 |
| W14 | 账户风控 | 复盘笔记 | ✅ | 5/11 | 空仓/连亏0天/未熔断 |
| W15 | 持仓明细 | 复盘 + PyTDX + W16 | ✅ | — | 空仓 |
| W16 | 报数面板 | 手工录入 | ✅ | — | — |
| W17 | 今日操作 | 复盘 + W16手工 | ✅ | 5/11 | 待填已过滤 |
| W18 | 锚定股状态 | 复盘笔记 | ✅ | 5/11 | 4只, 全字段完整 |
| W19 | 午盘复核 | 复盘笔记 | ✅ | — | — |

---

## 三、复盘笔记解析字段对照

### Frontmatter → JSON 映射

| 复盘笔记 Frontmatter | dashboard_data.json 路径 | 类型 | 必填 |
|---------------------|--------------------------|------|------|
| 上证指数 | market.上证指数 | number | ✅ |
| 上证涨幅 | market.上证涨幅 | number | ✅ |
| 市场量能 | market.市场量能 | string | ✅ |
| 涨跌比 | market.涨跌比 | string/null | |
| 涨停家数 | market.涨停家数 | number | ✅ |
| 跌停家数 | market.跌停家数 | number | ✅ |
| 炸板率 | market.炸板率 | number | |
| 封板率 | market.封板率 | number | |
| 情绪值 | sentiment.情绪值 | number | ✅ |
| 情绪区间 | sentiment.情绪区间 | string | ✅ |
| 昨日情绪 | sentiment.昨日情绪 | number/null | |
| 情绪变化 | sentiment.情绪变化 | string/null | |
| 赚钱效应 | sentiment.赚钱效应 | string | |
| 昨日涨停收益 | sentiment.昨日涨停收益 | number | |
| 昨日炸板收益 | sentiment.昨日炸板收益 | number/null | |
| 连板收益 | sentiment.连板收益 | number/null | |
| 连板风险值 | sentiment.连板风险值 | number | |
| 晋级率 | sentiment.晋级率 | number | ✅ |
| 最高板 | sentiment.最高板 | string | |
| 次高板 | sentiment.次高板 | string | |
| 连板梯队 | sentiment.连板梯队 | string/null | |
| 竞价情绪值 | sentiment.竞价情绪值 | number | |
| 当日盈亏 | risk.当日盈亏 | number | |
| 当日盈亏金额 | risk.当日盈亏金额 | number | |
| 周累计回撤 | risk.周累计回撤 | number | |
| 月累计回撤 | risk.月累计回撤 | number | |
| 连亏天数 | risk.连亏天数 | number | ✅ |
| 熔断触发 | risk.熔断触发 | boolean | |
| 周回撤触发 | risk.周回撤触发 | boolean | |
| 当前时段 | time_window.当前时段 | string | |
| W1状态 | time_window.W1状态 | string | |
| W2状态 | time_window.W2状态 | string | |
| 周五 | time_window.周五 | boolean | |

### 数据附录表格 → JSON 映射

| 附录章节 | JSON 路径 | 格式 |
|---------|----------|------|
| ### 持仓明细 | positions[] | Markdown 表格 |
| ### 连板自选池 | lianban_pool[] | Markdown 表格 |
| ### 趋势自选池 | trend_pool[] | Markdown 表格 |
| ### 板块状态 | sectors[] | Markdown 表格 |
| ### 竞价5维 | decision.竞价 | 嵌套表格 |
| ### W1早盘确认 | decision.早盘 | 嵌套表格 |
| ### W2盘中跟踪 | decision.盘中 | 嵌套表格 |
| ### 今日操作 | decision.今日操作 | Markdown 表格 |
| ### 锚定股状态 | decision.锚定股状态 | Markdown 表格 |

---

## 四、已知缺口 & 修复记录

### 5/11 修复
| 问题 | 修复 |
|------|------|
| store.js merge() 换手坏覆盖 | live_quotes "—" 不覆盖基线 |
| W12 MA5 key 不匹配 | `5日线` → `MA5` |
| gen 正则贪婪 | `.*` → `.*?`（数据附录标题含括号） |
| gen "待填"未过滤 | clean_value 过滤 |
| 竞价/W1/W2 从模板移除 | 洋米盘中自动接管 |
| 成交额 三指数重复计数 | 上证+深证，不含创业 |
| 板块数据 30s 内消失 | 缓存复用 |
| poll_iwencai 误启动守卫 | 移除，重定位为 --auction/--review |

### 剩余缺口
| 缺口 | 优先级 | 方案 |
|------|--------|------|
| W08/W09 LLM条件判定 | 高 | 洋米 Hook |
| W10 板块主力/5日线/涨停数 | 中 | VPN或替代API |
| 开工/收工流程编排 | 高 | Skill |
| 换手率/成交额差 | 低 | 基线够用 |

---

## 五、盘中数据流时序

```
盘前 (9:00)
  └─ gen_dashboard_data.py → dashboard_data.json + sync_embedded.py

竞价结束 (9:26)
  └─ poll_iwencai.py --auction → decision.竞价

盘中 (9:30-15:00)
  ├─ poll_live.py --watch → dashboard_live.json (5s/30s/5min)
  ├─ W16 手工录入 → Layer 3
  └─ [待做] 洋米 Hook → decision 域

收盘 (15:00+)
  ├─ poll_iwencai.py --review --save
  └─ 复盘笔记撰写 → gen_dashboard_data.py → 次日基线
```
