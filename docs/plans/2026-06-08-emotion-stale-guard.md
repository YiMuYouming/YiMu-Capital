# 桥情绪值 stale 保护

**状态**：待欧米实施
**创建**：2026-06-08 12:55
**创建人**：洋米

## 问题

2026-06-08 盘中，桥的 breadth/iwencai 数据停在 11:26，`rule_state` 情绪显示 59%（实际 13.6%）。过期数据被当成实时值展示，可能导致错误决策。

## 根因

`evaluate_rule_state()` 用 breadth 计算情绪值（`up/(up+down)*100`），未检查数据 freshness。

## 要求

### Backend（bridge.py）

1. 情绪值输出前检查 `_freshness.level`
   - `live` / `delayed` → 正常展示数值
   - `stale` → 展示 "stale (数据时间 HH:MM)"，禁止展示数值
   - `dead` → 展示 "不可用"

2. `rule_state` 中所有依赖过期数据的字段（emotion_pct, market_regime, caps 等），数据过期时标记为不可用，不输出误导性数值

3. 涉及位置：`bridge.py` `evaluate_rule_state()` 及情绪计算段（约 L817-L826）

### Frontend

4. 情绪组件（W05）收到 stale 标记时，灰色/虚线边框 + 显示数据时间，与正常数据视觉区分

## 验收标准

- 模拟 stale 数据 → 看板情绪不显示数值，显示 stale 标记 + 时间
- 正常 live 数据 → 照常显示
- `trade_entry_allowed` 在数据 stale 时相应降级
