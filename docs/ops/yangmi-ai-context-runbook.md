# 洋米读取仪表盘 AI Context 规范

> 适用对象：Claude Code / 洋米在盯盘、复盘追问、代码排障时读取 live-dashboard 事实包。
> 目标：先拿仪表盘统一事实，再决定是否需要外查；不从 UI 截图猜数据。

## 入口

生产 8088：

```bash
curl -s http://127.0.0.1:8088/api/ai/context | python3 -m json.tool
```

本地只读预览 18088：

```bash
curl -s http://127.0.0.1:18088/api/ai/context | python3 -m json.tool
```

只读要求：

- 只允许 `GET /api/ai/context`、`GET /api/health`、`GET /api/account/state`、`GET /api/live/quotes`、`GET /api/pnl/summary`。
- 不允许为了验证去调用 `/api/sync` 或任何 POST。
- 不允许写 `data/*`、不允许手动补交易记录。

## 回答顺序

洋米回答盯盘问题时，先按这个顺序读：

1. 先读 `/Users/yimu/Documents/YM_Capital/ai-rule-system/AGENT_QUICKSTART.md`，确认 Rule 2.0 四层边界和不得下单/不得 confirm 的红线。
2. 再读 `/Users/yimu/Documents/YM_Capital/ai-rule-system/compiled/rules.v1.json`，确认当前执行规则机器包可用。
3. 再读 `/Users/yimu/Documents/YM_Capital/ai-rule-system/RULE_GATE.md` 和 `docs/trade-ticket-workflow.md`，确认当前规则门与票据写入边界。
4. 再读 `/api/ai/context` 的 `schema_version` 和 `generated_at`：确认拿到的是当前契约和新鲜事实包。
5. `freshness`：确认行情、账户、情绪、基线是否 live/delayed/stale/dead。
6. `situation.trade_entry_allowed` 和 `situation.trade_entry_reason`：先判断能不能生成或推进 ticket。
7. `risks`：所有阻断和关键风险先报出来。
8. `human_required`：这里列出的事项必须让主人确认或复核。
9. `tickets`：看 pending/executable/blocked/completed 以及具体票据。
10. `positions`、`candidates`、`alerts`：补充持仓、候选和提示。

冰点 W1 黄灯专项口径：

- `rule_state.windows.w1.manual_review_allowed=true` 只表示极化主线强回踩进入人工复核。
- 仍以 `rule_state.windows.w1.buy_allowed` 判断是否可推进 W1 买入；黄灯不能等同于允许买入。
- `/api/ai/context.alerts` 若出现 `WIN-ICE-POLAR-MAINLINE-001`，必须同步读 `human_required`，不能生成 executable ticket。

## 常见问题怎么答

问“现在能不能操作？”

- 先看 `situation.trade_entry_allowed`。
- 如果是 `false`，回答阻断原因，并列出 `risks` 和 `human_required`。
- 如果是 `true`，仍要确认 `freshness.quotes.status` 不是 stale/dead/missing，再看 `rule_state.windows.*.buy_allowed` 和 `tickets.executable`。

问“现在最需要我看什么？”

- 优先读 `human_required`。
- 其次读 `next_actions`。
- 如果有 `TICKET_CONFLICT_REVIEW`、`DATA_REVIEW_REQUIRED`、`TRADE_BLOCKED`，先处理这些，不要直接给买卖建议。

问“票据有没有要执行的？”

- 看 `tickets.executable` 和 `tickets.items`。
- 盘中任务队列以 `/api/ai/context.tickets` 为主。
- 需要直接查票据列表时必须传交易日：`GET /api/trade/tickets?date=YYYY-MM-DD`。裸 `/api/trade/tickets` 只默认当天，不代表历史全量。
- `executable`、`audit_degraded`、`partially_filled`、`manual_review`、`confirmed`、`draft` 都需要人工确认。
- 有 `blocked` 或 `TICKET_QUERY_ERROR` 时，不能假定“没有票据”。
- 废票不要改 Markdown，也不要裸写 SQL；用 `POST /api/trade/tickets/{ticket_id}/close` 写入 `closed/cancelled/closed_with_conflict`、`close_reason` 和 `review_note`。`executable` / `blocked` 废票会污染 `/api/ai/context.tickets`，必须闭环。

问“数据能不能信？”

- 看 `freshness` 和 `situation.health.critical_reasons`。
- `quotes` 为 stale/dead/missing，或 `account` 为 error/incomplete 时，必须明确说数据不可直接用于交易动作。
- `iwencai` stale 不是交易入口阻断，但只能作为降级提示，不能当实时情绪。

## 何时外查

可以外查：

- 用户问具体个股、板块、新闻、盘口细节，而 `candidates`/`positions` 没覆盖。
- `freshness` 显示某个源 stale/dead，需要用同花顺、问财或其他数据源交叉验证。
- 用户明确要求查最新行情/公告/新闻。

外查后也要回到本事实包复核：

- 外查不能绕过 `trade_entry_allowed=false`。
- 外查不能替代 `human_required`。
- 外查结论如果和仪表盘冲突，先报冲突，不直接行动。
- 外查不能授权下单、调用券商接口或直接 confirm 成交。

## 最小 JSON 读取示例

```bash
python3 - <<'PY'
import json, urllib.request

ctx = json.load(urllib.request.urlopen("http://127.0.0.1:8088/api/ai/context", timeout=5))
print("generated_at:", ctx.get("generated_at"))
print("trade_allowed:", (ctx.get("situation") or {}).get("trade_entry_allowed"))
print("risks:", [r.get("code") for r in ctx.get("risks", [])])
print("human_required:", [h.get("code") for h in ctx.get("human_required", [])])
print("tickets:", ctx.get("tickets", {}))
PY
```

## 输出口径

洋米对主人说话时建议用这个结构：

```text
我先读了 /api/ai/context。
当前：trade_entry_allowed=<true/false>，行情=<status>，账户=<status>。
阻断/风险：...
需要你确认：...
下一步建议：...
```

如果接口 500、超时或无响应：

- 先报“AI context 不可用”。
- 再查 `/api/health`。
- 不要改数据，不要补 POST，不要假装已经读到仪表盘事实。
