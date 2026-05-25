# ymwm (弈沐看盘) — 开工检查 Skill 设计文档

> 版本: v1 | 日期: 2026-05-21 | 状态: 草案

## 一、概述

**定位**: 弈沐资本数据看板开盘前的全链路体检工具。
Skill 注册为 Tier 3（纯按需），不自动加载。按需触发，自动识别当前交易阶段，跑对应检查项，小病自治、大病汇报。

**触发方式**: 用户在任何会话中说出触发词 `/ymwm` 或 `ymwm 弈沐看盘`。

**核心原则**:
1. 按需触发，不自动定时，不抢节奏
2. 根据当前时间自动识别阶段，跑不同检查集
3. 小问题自动修复（启动bridge、补报价代码、删脏数据），大问题只报告
4. 输出三色报告：✅正常 ⚠️告警 ❌需处理

## 二、四个交易阶段

| 阶段 | 时间段 | 检查范围 | 说明 |
|------|--------|---------|------|
| 盘前 | 任意日 00:00-9:24 | 基础项 | 检查 bridge/gen/笔记一致性，数据源未开盘不检 |
| 竞价 | 9:25-9:29 | 基础项+竞价 | 竞价快照+报价覆盖率已可用 |
| 盘中 | 9:30-15:00 | 全检 | 所有检查项全开 |
| 盘后 | 15:00+ | 收盘项 | 全检+日线确认 |

判断逻辑（Python，精确到分钟）：

```python
def get_phase():
    now = datetime.now()
    if now.weekday() >= 5:
        return 'weekend'  # 周末只跑基础
    t = now.hour * 60 + now.minute
    if t < 9 * 60 + 25:
        return 'premarket'    # 盘前
    elif t < 9 * 60 + 30:
        return 'auction'      # 竞价
    elif t < 15 * 60:
        return 'intraday'     # 盘中
    else:
        return 'postmarket'   # 盘后
```

## 三、检查项矩阵

### 3.1 bridge 存活（#1）
| 属性 | 值 |
|------|-----|
| 数据源 | `pgrep -f bridge.py` + `curl localhost:8088/api/pnl/summary` |
| 判断 | 进程存在且 HTTP 200 |
| 自动修 | 进程不存在 → `cd live-dashboard && python3 scripts/bridge.py 8088 &` → sleep 3 → curl 检测，最多 3 次重试，超时报告失败 |
| 适用阶段 | 全部 |

### 3.2 gen 时效性（#2）
| 属性 | 值 |
|------|-----|
| 数据源 | dashboard_data.json meta + 最新复盘笔记 mtime |
| 判断 | 最新笔记日期 == 今日？gen 时间 > 笔记最后修改时间？ |
| 自动修 | 未跑或过期且处于盘前 → `cd live-dashboard && PYTHONPATH=. python3 scripts/gen_dashboard_data.py` + 重启bridge |
| 注意 | 盘前直接跑；盘中（≥9:30）如需跑 gen → 提示用户确认后再执行。检测依据：dashboard_data.json meta.date 是否为今日 |
| 适用阶段 | 全部 |

### 3.3 报价覆盖率（#3）
| 属性 | 值 |
|------|-----|
| 数据源 | `/api/live/quotes` live_quotes key 列表 + dashboard_data.json 持仓/池代码 |
| 判断 | 所有持仓股 + 连板池 + 趋势池 + 锚定股代码是否都在 live_quotes 中 |
| 自动修 | 缺失代码 → 追加到 bridge 启动的 codes 列表 → 重启 bridge |
| 适用阶段 | 竞价、盘中、盘后 |

### 3.4 PnL 数据健康（#4）
| 属性 | 值 |
|------|-----|
| 数据源 | pnl.db intraday_snapshots + daily_summary |
| 判断 | 检查 pnl_pct 是否有 >10（异常值）；daily_summary 中 deposit 是否统一为 200000；是否有 NAV=1.0 占位行 |
| 自动修 | 异常快照 → DELETE；deposit=0 → UPDATE；占位行 → DELETE |
| 适用阶段 | 全部 |

### 3.5 持仓一致性（#5）
| 属性 | 值 |
|------|-----|
| 数据源 | 复盘笔记附录A（持仓明细）+ dashboard_data.json positions + live_quotes |
| 判断 | 三源交叉对比，标出差集（笔记有 vs 仪表盘有 vs 报价有） |
| 自动修 | **不修，仅报告**。涉及你的实际交易决策 |
| 适用阶段 | 全部 |

### 3.6 自选池一致性（#6）
| 属性 | 值 |
|------|-----|
| 数据源 | 复盘笔记附录A（连板自选池 + 趋势自选池）+ dashboard_data.json（lianban_pool + trend_pool） |
| 判断 | 对比 附录A 和 dashboard_data.json，标出差异（新增/缺失/窗口值变更） |
| 自动修 | **不修，仅报告**。涉及选股判断 |
| 适用阶段 | 全部 |

### 3.7 数据新鲜度（#7）
| 属性 | 值 |
|------|-----|
| 数据源 | `/api/live/quotes` 中 iwencai 字段 |
| 判断 | 情绪值/涨停收益/炸板率/连板收益 是否有值、非"—"；更新时间距现在 < 30 分钟 |
| 自动修 | **不修，仅报告**。数据源异常需人工排查 |
| 适用阶段 | 盘中、盘后。盘前跳过 |

### 3.8 组件健康（#8）
| 属性 | 值 |
|------|-----|
| 数据源 | `/api/debug/snapshot` 或逐 API 获取各组件 dataPaths |
| 判断 | 22 组件各自订阅的关键字段不为 null/—/空 |
| 自动修 | **不修，仅报告**。每组件异常需差异化处理 |
| 适用阶段 | 竞价、盘中、盘后 |

### 3.9 阶段专用检查

**竞价阶段附加**:
| 检查 | 说明 |
|------|------|
| 竞价快照时效 | `auction_snapshot.json.mtime` 是否为今日 9:25+ |
| 竞价情绪值 | `sentiment.竞价情绪值` 非空 |

**盘后阶段附加**:
| 检查 | 说明 |
|------|------|
| 收盘确认 | `daily_summary` 中今日日期存在（15:10 后写入） |
| portal 同步 | 提示 "需同步门户？" |

### 3.10 周末/节假日

周末跳过所有数据源检查，只跑 bridge 存活。

## 四、输出格式

```
━━━ 弈沐看盘 · 盘中检查 ━━━ 2026-05-21 10:30 ━━━━

✅ bridge      正常运行 (PID 12934)
✅ gen         最新笔记 5/21 → gen 已同步
✅ 报价        21/21 只全覆盖，无缺失
⚠️ PnL         0 异常快照，15 天收盘数据 ✓
✅ 持仓        笔记 vs 仪表盘 vs 报价 一致
⚠️ 自选池      柏诚(601133) 在笔记正文但有，附录A漏了
✅ 数据新鲜    情绪 29% / 涨停收益 -0.23% / 炸板率 22.78%
⚠️ W08         窗口过滤已修，6 只显示（盯+W1观察）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
8/8 通过 | 2 告警 | 0 需处理
```

颜色标记：
- ✅ = var(--down) 绿色 (正常)
- ⚠️ = var(--warn) 黄色 (告警)
- ❌ = var(--danger) 红色 (需处理)

### 3.11 报告持久化

每次检查结果同时写入 `data/ymwm_report.json`（覆盖写），供你后续回顾。格式与 stdout 报告一致，增加 `timestamp` 和 `phase` 字段。

## 五、Skill 注册与文件结构

### 注册方式

SKILL.md frontmatter 格式：

```yaml
---
name: ymwm
description: "弈沐看盘开工检查。按需触发（/ymwm 或 ymwm 弈沐看盘），全链路体检，小病自治大病汇报"
trigger: "ymwm"
preamble: T3
---
```

触发词在 CLAUDE.md 中注册为 Tier 3（纯按需，仅在明确触发时加载）。

### 文件结构

```
~/.claude/skills/ymwm/SKILL.md          # 技能入口（注册 + preamble）
~/.claude/skills/ymwm/ymwm_check.py     # 主调度器（阶段判断 + 执行管道）
~/.claude/skills/ymwm/checks/
    ├── 01_bridge.sh                 # bridge 存活
    ├── 02_gen_timeliness.py         # gen 时效性
    ├── 03_quote_coverage.py         # 报价覆盖率
    ├── 04_pnl_health.py             # PnL 完整性
    ├── 05_position_consistency.py   # 持仓一致性
    ├── 06_pool_consistency.py       # 自选池一致性
    ├── 07_data_freshness.py         # 情绪新鲜度
    ├── 08_widget_health.py          # 组件关键字段
    └── 09_phase_extras.py           # 阶段专用检查（竞价/盘后）
```

## 六、技术细节

### bridge 端口约定
- 默认端口：8088
- 检查方式：`curl -s -o /dev/null -w '%{http_code}' http://localhost:8088/api/pnl/summary`
- 返回 200 为正常

### gen 脚本调用
```bash
cd ~/Documents/YM_Capital/live-dashboard && PYTHONPATH=. python3 scripts/gen_dashboard_data.py
```

### 报价代码注入
修改 `data/cache_dump.json` 或直接通过 bridge API 热更新（后续可加 `/api/refresh/codes` 端点）

当前方案：修改 `dashboard_data.json` → 重启 bridge

### PnL 清理
```sql
-- 删除异常快照
DELETE FROM intraday_snapshots WHERE abs(pnl_pct) > 10;
-- 清洗占位行
DELETE FROM daily_summary WHERE nav = 1.0 AND pnl_pct = 0.0;
-- 统一入金
UPDATE daily_summary SET deposit = 200000 WHERE deposit = 0 OR deposit IS NULL;
```

## 七、自修复原则

| 修复类型 | 示例 | 执行方式 |
|---------|------|---------|
| 纯操作 | 启动 bridge | 直接执行 |
| 数据修正 | 删脏快照 | SQL 直接执行 |
| 自动重启 | 报价代码变更 | 先备份再重启 |
| 只报告 | 持仓不一致 | 输出差异对比表 |

**安全红线**：
- 不改复盘笔记
- 不改你的持仓数据（持仓状态/数量/成本）
- 不改 pnl_history.json（仅清理 pnl.db 中的脏快照）
- 修改 dashboard_data.json 前先 cp .bak

## 八、未覆盖场景（后续优化）

1. **H8 复盘→仪表盘 LLM 审核闭环**：检查 AI 研判是否已在 llm_insights.json 中
2. **龙虎榜/北向数据**：当前仅在 ym-data-pipeline 中，仪表盘未直接消费
3. **launchd 兜底状态检查**：竞价触发器/定时任务是否配置正常
4. **数据源限流检测**：iwencai OpenAPI 额度是否耗尽
