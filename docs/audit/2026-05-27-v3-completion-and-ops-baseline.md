# 弈沐资本数据看板 v3.0 完成收口与运维基线

> 日期：2026-05-27  
> 状态：v3.0 升级主线已完成  
> 当前入口：新窗口开工先读本文、`README.md`、`AGENTS.md`  
> 历史过程材料：`docs/_archive/2026-05-27-v3-upgrade/`

## 一、总览

v3.0 升级主线已经跑完。Phase 1 通过聊天验收完成，Phase 2-6 已通过 Agent Board 验收：

| 阶段 | 结果 | 说明 |
| --- | --- | --- |
| Phase 1 | 完成 | W15 前端输入校验；账户 reducer 超卖 fail-closed |
| Phase 2 | accepted | 成交上下文与 W23 可信复盘 |
| Phase 3 | accepted | LLM 与 `rule_state` 可信快照 |
| Phase 4 | accepted | 健康分层与账户基准审计 |
| Phase 5 | accepted | W22/W15/W23 体验收口 |
| Phase 6 | accepted | 样式系统、文档一致性、runtime 收口 |

最终验证：

```text
python3 -m unittest discover -s tests -v  -> Ran 427 tests OK
python3 -m compileall -q scripts tests   -> OK
node --check widgets/*.js + store/base/registry -> OK
python3 scripts/check_runtime.py --health -> OK
```

## 二、现在系统已经具备的能力

- W15 成交录入会在前端和后端双层校验，非法数量、空字段、非法时间、非法价格不会进入成交流水。
- 卖出写入和账户回放都具备超卖保护；坏账本不会虚增现金。
- W23 逐笔复盘能区分已验证、未验证、上下文不可用，不伪造规则上下文。
- LLM 快照以账户 SSOT 和 `rule_state` 为核心，不再混用旧持仓基线。
- `/api/health` 已拆分关键阻断、交易入口许可和降级原因。
- W22/W15 在行情不可用、锚点阻断、收盘快照等状态下有明确展示口径。
- `scripts/check_runtime.py` 已拆分 `--preflight` 和 `--health`，运行中 8088 占用不再被当成启动前错误。
- README、AGENTS、CLAUDE、页面标题已统一到 v3.0 / 23 组件口径。

## 三、当前权威数据链

```text
account_baselines（日初锚点）
  + trade_records（成交事实）
  + fund_events（资金事件）
  + live quotes / close snapshot（估值）
  -> /api/account/state
  -> /api/pnl/summary
  -> W15 / W22 / 顶栏
```

关键规则：

- `dashboard_data.json` 是每日展示基线，不是盘中账户事实来源。
- `/api/sync` 只接收成交事件，不允许客户端覆盖现金、持仓市值或总资产。
- `rule_state` 是 W1/W2、风控组件和 AI 研判的统一机器口径。
- W15/W22 的合法零值和未知值必须区分；未知值显示不可用，不用 0 兜底。

## 四、真实数据修复记录

以下是真实数据修复，不是测试污染，不要随手回滚：

| 日期 | 标的 | 代码 | 字段 | 值 | 说明 |
| --- | --- | --- | --- | --- | --- |
| 2026-05-27 | 兴森科技 | `002436` | `day_start_price` | `37.83` | 用户确认今日开盘价，修复 W15 基准不可用 |
| 2026-05-27 | 沪电股份 | `002463` | `day_start_price` | `133.36` | 恢复当日清仓已实现盈亏 |
| 2026-05-27 | 中芯国际 | `688981` | `day_start_price` | `149.18` | 恢复当日清仓已实现盈亏 |

最新兴森科技补录备份：

```text
data/pnl.db.bak.repair-002436-20260527-205554
```

修复后只读核验：

```text
002436 _day_start_price = 37.83
002436 today_pnl = -1215.0
002436 today_pnl_pct = -2.14
```

## 五、开新窗口排查优先顺序

1. 先跑只读健康：

```bash
python3 scripts/check_runtime.py --health
curl -fsS http://localhost:8088/api/health
curl -fsS http://localhost:8088/api/account/state
```

2. 如果是启动前检查：

```bash
python3 scripts/check_runtime.py --preflight
```

3. 如果 W15 显示“基准不可用”：

```bash
curl -fsS http://localhost:8088/api/account/state
python3 scripts/repair_day_start_price.py --date YYYY-MM-DD --code CODE --price PRICE --source "..." --reason "..."
```

确认 dry-run 通过后，且价格来源已核验，再加 `--apply`。禁止用成本价猜测日初价。

4. 如果是成交写入问题：

- 不对真实 8088 做测试性 POST。
- 用测试库或单测复现。
- 优先看 `tests/test_sync_guard.py`、`tests/test_account_ssot.py`、`tests/test_frontend_g3b.py`。

## 六、文档归档状态

已归档到 `docs/_archive/2026-05-27-v3-upgrade/`：

- v3 总控 review 文档
- v3 Phase 1 派单文档
- W15/W22 专项审查任务清单
- 旧的 2026-05-27 升级验收与运维基线

当前不要再从这些归档文档续派任务。新 bug 新窗口单独开任务，按当前代码和本文为准。

