# W25 Command Cockpit Design

## Goal

Upgrade W25 from a compact evidence board into the intraday command cockpit. In 10 seconds, the operator should know whether trading is allowed, why, what to handle next, which 1-3 widgets matter now, and which data sources are not usable for live trading decisions.

## Decision

W25 should align with `/api/ai/context` as the highest-level fact contract. The browser can still use `EvidenceSummary` as a render adapter, but command semantics must come from the same concepts that Codex, Yangmi, and later sidecar agents read: `situation`, `freshness`, `tickets`, `risks`, `alerts`, `human_required`, and `next_actions`.

This keeps the hard trading boundary visible: `trade_entry_allowed` is the real gate, and degraded data is not automatically a trading block.

## Non-Goals

- Do not execute real trades inside W25.
- Do not move W24/W15/W14 content into W25.
- Do not add a chat interface.
- Do not add new production dependencies.
- Do not send POST requests during W25 rendering or tests.

## Information Model

W25 has four top-level sections.

### S0 Current Command

S0 is the first visual element. It shows:

- command state: `可执行`, `只观察`, `阻断`, `降级可用`, or `收盘/复盘`;
- current mode or phase;
- trading gate status;
- one sentence reason;
- one next action.

The state is derived from the fact contract:

- `阻断`: `situation.trade_entry_allowed === false` or critical risk blocks live trading.
- `降级可用`: trade entry is allowed but non-critical freshness or health alerts exist.
- `可执行`: trade entry is allowed and executable tickets exist.
- `只观察`: trade entry is allowed but no executable ticket or active window action exists.
- `收盘/复盘`: mode is review/closed or quotes are close snapshot.

### A1 Action Queue

A1 turns tickets and manual review requirements into a short task queue. W25 only reminds and jumps; concrete operations stay in W24/W15/W14.

Queue priorities:

1. Critical block or data review.
2. Ticket conflict review.
3. Executable ticket review.
4. Pending ticket confirmation.
5. Core holding or active W1/W2 widget check.

Each row includes type, target widget, priority tone, reason, and jump target.

### E1 Key Evidence

E1 shows 3-5 pieces of evidence used by the command. Each item includes:

- title;
- value;
- source widget or API;
- freshness status;
- whether it is tradable evidence or only observation.

Live and delayed data may enter the command reason. Stale, dead, baseline, and manual data must be labeled as review-only unless the backend has already fail-closed the trading gate.

### F1 Freshness Strip

F1 centralizes freshness for:

- quotes;
- iwencai;
- account;
- baseline;
- tickets;
- llm.

Statuses: `live`, `delayed`, `stale`, `dead`, `baseline`, `manual`, `unknown`, `error`.

W25 must explicitly flag sources that cannot support live trading decisions.

## Data Flow

```text
/api/ai/context
        ↓
DataStore.ai_context
        ↓
EvidenceSummary.build(data, runtime)
        ↓
W25 render
        ↓
click target opens W24/W15/W14/W08/W09/W10/W20/W23
```

`/api/ai/context` remains read-only. DataStore may fetch it with GET only. If it is unavailable, W25 falls back to the current merged dashboard data and displays an explicit `事实包不可用` freshness/task item.

## Frontend Layout

W25 keeps the existing compact cockpit style, but hierarchy changes:

1. Top command hero: state, phase, reason, next action.
2. Four fixed metric cells: emotion, PnL, position, trade gate.
3. Mid row: action queue and freshness strip.
4. Bottom row: key evidence and current focus widgets.

The visual tone should be utilitarian and scan-friendly: dense, restrained, with red/amber used only for real block or review attention. Text must fit in cockpit mode and half-screen widths.

## Files

- `scripts/bridge.py`: extend `/api/ai/context` only if required for ticket/freshness fields missing from the contract.
- `store.js`: fetch and merge `/api/ai/context` into `DataStore.merged.ai_context` using GET.
- `evidence-summary.js`: normalize command, action queue, evidence, and freshness from `ai_context` first, with current data fallback.
- `widgets/evidence-board.js`: render the new S0/A1/E1/F1 layout.
- `css/theme.css`: add W25 command cockpit styles without changing unrelated widgets.
- `tests/test_health_api.py`: protect any backend contract additions.
- `tests/test_frontend_rule_state.py`: add W25 rendering and summary behavior tests.

## Acceptance

- W25 makes `能不能交易` and `为什么` visible in the first line.
- W25 shows the next action and target widget.
- W25 shows tickets and human-required items as a task queue.
- W25 shows freshness status and marks stale/dead/baseline/manual sources as not live-tradable.
- W25 and `/api/ai/context` use the same trading gate semantics.
- No POST request is added.
- Existing cockpit layout and W25 jump behavior keep working.
- Targeted Python/Node frontend tests pass, followed by compile and diff checks.
