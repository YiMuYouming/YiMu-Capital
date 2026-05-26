# W04/W05 颜色与数据源修复

> 日期: 2026-05-26 | 优先级: P1 | 指派: 稳米

## 背景

今日 SSOT 改造后，数据管线已稳定。但 W04（市场全景）和 W05（情绪节点对比）存在颜色不一致、数据源优先级错乱的问题。弈沐哥反馈：上证的涨跌颜色不对、情绪值有的有颜色有的没有、涨停/连板/炸板收益颜色不统一。

## 问题一：W05 颜色规则乱码

**位置**: `widgets/sentiment-dash.js:74-79`

当前规则不是简单的「涨红跌绿」，而是用了复杂阈值：

```javascript
// 炸板收益: num<0 → red, num>1 → green, 0~1 → NO COLOR
if (key === '炸板收益') return num < 0 ? 'up' : num > 1 ? 'down' : '';

// 涨停收益/连板收益: num≥2 → red, num<0 → green, 0~2 → NO COLOR
if (key === '涨停收益' || key === '连板收益') return num >= 2 ? 'up' : num >= 0 ? '' : 'down';

// 情绪值: 40~60 → red, <20 → green, 20~40和60+ → NO COLOR
if (key === '情绪值') return num >= 40 && num <= 60 ? 'up' : num < 20 ? 'down' : '';
```

**修复**: 统一为涨红跌绿，去掉阈值门槛：
```
num > 0 → 'up' (红色)
num < 0 → 'down' (绿色)
num == 0 → '' (无颜色)
```

## 问题二：W05 无 DataStore 订阅

**位置**: `widget-registry.js` — W05 的 `dataPaths: []` 是空的。

W05 自己 fetch `data/sentiment_auto.json`，完全绕过了 DataStore。这意味着：
- 实时报价更新时 W05 不刷新
- 手动刷新按钮点不动 W05
- 和其他组件的数据时间戳不一致

**修复**: 至少加上订阅：
```
dataPaths: ['sentiment_nodes', 'live_index', 'iwencai.涨停家数', 'iwencai.跌停家数', 'iwencai.昨日涨停收益']
```

## 问题三：涨停/连板/炸板收益值不变

W04 和 W05 都读 `iwencai.昨日涨停收益` / `iwencai.连板收益` / `iwencai.炸板收益`。

当前 iwencai 只返回一个值（不是分时间节点的），所以全天所有时间段的表格显示的是一样的数。

**修复**: W05 表格已经按时间节点（竞价/早盘/午盘/尾盘/收盘）分列了，但目前每个节点都读同一个 iwencai 值。需要确认：
1. `sentiment_auto.json` 是否有分节点的 data（如果没有，需要桥接在 sentiment_snapshot 采集时记录）
2. 如果短期内改不了采集端，至少 W04 只显示当前值，不在表格里重复

## 问题四：上证颜色——已有 live_index，可能没刷新到位

W04 的指数颜色逻辑本身是对的：`chg.charAt(0) === '+' ? 'up' : 'down'`。今天上证 -0.17% 应该显示 green。

弈沐哥反馈"全是红的"——可能是 DataStore 合并时 baseline 的旧值（+0.96%）盖掉了 live_index（-0.17%）。需检查 `store.js` 的 merge 逻辑中 `market` 域的优先级：确保 `live_index` 不被 baseline market 覆盖。

## 修复清单

| # | 文件 | 改动 |
|---|------|------|
| 1 | `widgets/sentiment-dash.js` | 颜色规则统一为 `num>0?'up':num<0?'down':''` |
| 2 | `widget-registry.js` | W05 dataPaths 补上订阅 |
| 3 | `widgets/sentiment-dash.js` | render 改用 DataStore.merged 数据，不再独立 fetch |
| 4 | `store.js` merge() | 检查 market 域：live_index 优先于 baseline market |
| 5 | `widgets/market-overview.js` | zu/zb 收益如果 iwencai 数据不存在，降级显示 `—` 而不是 0 |

## 验证方法

1. 确认上证指数颜色：涨=红、跌=绿、平=无色
2. 确认情绪值颜色统一：>0 红、<0 绿
3. 确认涨停/连板/炸板收益颜色统一：同上
4. 确认 W05 能通过 DataStore 刷新
