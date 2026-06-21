# W25 Command Cockpit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade W25 into a command cockpit backed by `/api/ai/context`, showing trading gate, reason, next action, task queue, evidence, and freshness in one scan.

**Architecture:** `/api/ai/context` is the command fact source. `store.js` fetches it into `DataStore.merged.ai_context`; `evidence-summary.js` normalizes a UI snapshot from `ai_context` first and existing merged data as fallback; `widgets/evidence-board.js` renders the compact S0/A1/E1/F1 layout.

**Tech Stack:** Python `unittest`, Node-based widget render tests, plain JavaScript widgets, existing CSS in `css/theme.css`, no new dependencies.

---

## File Structure

- Modify `store.js`: add read-only `fetchAiContext()` and include `ai_context` in merged data.
- Modify `evidence-summary.js`: add helpers for command state, freshness rows, tradability labels, and ai-context-backed action queue.
- Modify `widgets/evidence-board.js`: render S0/A1/E1/F1 sections from the normalized snapshot.
- Modify `css/theme.css`: style the command cockpit with fixed, non-overflowing grid areas.
- Modify `tests/test_frontend_rule_state.py`: add behavior tests for ai-context-backed W25 command, freshness, and fallback.
- Modify `tests/test_health_api.py` only if a missing backend field is discovered during Task 1.

## Task 1: Protect The AI Context Contract

**Files:**
- Test: `tests/test_health_api.py`
- Inspect: `scripts/bridge.py`

- [ ] **Step 1: Write or confirm backend contract tests**

Add tests only if the current contract lacks any required field. Required checks:

```python
def test_ai_context_exposes_command_cockpit_inputs(self):
    ctx = bridge._build_ai_context()
    self.assertIn("trade_entry_allowed", ctx["situation"])
    self.assertIn("trade_entry_reason", ctx["situation"])
    self.assertIn("freshness", ctx)
    for key in ["quotes", "iwencai", "account", "baseline"]:
        self.assertIn(key, ctx["freshness"])
        self.assertIn("status", ctx["freshness"][key])
    self.assertIn("tickets", ctx)
    for key in ["pending", "executable", "blocked", "completed", "items"]:
        self.assertIn(key, ctx["tickets"])
    self.assertIn("next_actions", ctx)
    self.assertIn("human_required", ctx)
```

- [ ] **Step 2: Run RED or confirm existing coverage**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_health_api.AIContextApiTest -v
```

Expected: either the new test fails because a field is missing, or existing tests already prove every field and no backend change is needed.

- [ ] **Step 3: Implement minimal backend addition only if RED fails**

If a required field is missing, add it in `_build_ai_context()` or `_ai_freshness_summary()` with read-only data already available in `scripts/bridge.py`. Do not call mutation APIs or create anchors.

- [ ] **Step 4: Run GREEN**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_health_api.AIContextApiTest -v
```

Expected: all `AIContextApiTest` tests pass.

- [ ] **Step 5: Subagent review gate**

Dispatch a spec reviewer to confirm the contract supports W25 S0/A1/E1/F1 without extra backend mutation. Then dispatch a code-quality reviewer before moving to Task 2.

## Task 2: Fetch AI Context Into DataStore

**Files:**
- Modify: `store.js`
- Test: `tests/test_frontend_g2b.py` or `tests/test_frontend_rule_state.py`

- [ ] **Step 1: Write failing frontend data test**

Add a Node test that stubs `fetch('/api/ai/context')`, calls the DataStore refresh path, and asserts merged data includes `ai_context`. The test should also assert the request method is GET by relying on default fetch options.

Expected fixture:

```javascript
{
  schema_version: "ai_context.v1",
  situation: { trade_entry_allowed: false, trade_entry_reason: "quotes stale" },
  freshness: { quotes: { status: "stale" } },
  tickets: { pending: 1, executable: 0, blocked: 0, completed: 0, total: 1, items: [] },
  next_actions: [{ code: "REVIEW_BLOCK", title: "先复核阻断原因" }],
  human_required: [{ code: "DATA_REVIEW_REQUIRED", title: "复核行情数据" }]
}
```

- [ ] **Step 2: Run RED**

Run the single new test:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_frontend_g2b.W25AiContextDataStoreTest.test_refresh_fetches_ai_context_with_get_and_merges_it -v
```

Expected: fails because `ai_context` is not fetched or merged.

- [ ] **Step 3: Implement minimal DataStore GET**

Add an adapter method:

```javascript
fetchAiContext: function() {
  if (_isFileProtocol) return Promise.resolve(null);
  return fetch('/api/ai/context')
    .then(function(r) { return r.ok ? r.json() : null; })
    .catch(function() { return null; });
}
```

Call it in the existing refresh flow after live data. Merge result as `d.ai_context = aiContext` when present. If it fails, do not block the rest of the dashboard.

- [ ] **Step 4: Run GREEN**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_frontend_g2b.W25AiContextDataStoreTest.test_refresh_fetches_ai_context_with_get_and_merges_it -v
```

Expected: pass.

- [ ] **Step 5: Subagent review gate**

Spec review checks: GET only, no refresh failure hard block, `DataStore.merged.ai_context` available. Code review checks: no race-prone mutation and no unrelated DataStore refactor.

## Task 3: Normalize W25 Command Snapshot From AI Context

**Files:**
- Modify: `evidence-summary.js`
- Test: `tests/test_frontend_rule_state.py`

- [ ] **Step 1: Write failing summary tests**

Add tests that load `evidence-summary.js` directly and assert:

1. `ai_context.situation.trade_entry_allowed=false` produces `command.label === "阻断"` or equivalent blocked command, with reason from `trade_entry_reason`.
2. `trade_entry_allowed=true` plus `tickets.executable=1` produces an executable ticket next action targeting W24.
3. stale quotes produce a freshness row marked not tradable.

- [ ] **Step 2: Run RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_frontend_rule_state.W25CommandSummaryTest -v
```

Expected: fails because `EvidenceSummary.build()` does not yet consume `ai_context`.

- [ ] **Step 3: Implement minimal normalization**

In `evidence-summary.js`, add helpers with these exact responsibilities:

- `aiContext(data)`: return `data.ai_context` only when it has a `schema_version`, otherwise return `null`.
- `freshnessRows(ctx)`: return rows for quotes, iwencai, account, baseline, tickets, and llm.
- `commandFromAiContext(ctx)`: return `{ label, tone, reason, next }` from mode, trade gate, risks, and tickets.
- `queueFromAiContext(ctx)`: return W25 queue items mapped from risks, human_required, tickets, and next_actions.

Return new fields from `build()`:

```javascript
command_source: ctx ? "ai_context" : "fallback",
freshness_rows: [...],
focus_widgets: [...]
```

Keep existing fields (`situation`, `command`, `phase`, `gates`, `action_queue`, `evidence`, `alerts`, `risks`) compatible.

- [ ] **Step 4: Run GREEN**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_frontend_rule_state.W25CommandSummaryTest -v
```

Expected: pass.

- [ ] **Step 5: Subagent review gate**

Spec review checks: ai_context wins over fallback, freshness rows include tradability labels, no stale data shown as live-tradable. Code review checks: helpers are small, existing fallback behavior remains.

## Task 4: Render The S0/A1/E1/F1 Command Cockpit

**Files:**
- Modify: `widgets/evidence-board.js`
- Modify: `css/theme.css`
- Test: `tests/test_frontend_rule_state.py`

- [ ] **Step 1: Write failing W25 render tests**

Add render tests asserting W25 HTML contains:

- `盘中裁决`;
- the blocked or executable command reason;
- `优先处理`;
- `数据新鲜度`;
- freshness statuses such as `quotes stale`;
- target trace attributes for W24/W15/W14 when relevant.

- [ ] **Step 2: Run RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_frontend_rule_state.W25CommandRenderTest -v
```

Expected: fails because the current W25 does not render the F1 freshness strip or ai-context command details.

- [ ] **Step 3: Implement W25 render update**

In `widgets/evidence-board.js`, add rendering helpers:

- `_freshnessRow(row)`: returns one status row with source, status, trading usability, and detail text.
- `_focusChip(item)`: returns one clickable target widget chip.
- `_evidenceItem(item)`: returns one compact evidence row with source and freshness.

Update `render()` to output:

```html
<div class="evidence-board evidence-command-cockpit">
  <div class="evidence-dashboard-hero ...">...</div>
  <div class="evidence-command-grid">
    <section class="evidence-queue-panel">...</section>
    <section class="evidence-freshness-panel">...</section>
    <section class="evidence-source-panel">...</section>
  </div>
</div>
```

Keep `_bindEvidenceTraceLinks()` and existing jump target behavior.

- [ ] **Step 4: Add CSS**

Add compact styles under the existing W25 evidence section:

```css
.evidence-command-cockpit .evidence-command-grid{display:grid;grid-template-columns:1.1fr 1fr 1fr;gap:8px;min-height:0}
.evidence-freshness-row{display:grid;grid-template-columns:72px minmax(0,1fr) auto;gap:6px;align-items:center}
.evidence-freshness-row em{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
```

Use existing color variables and keep cockpit-mode overrides.

- [ ] **Step 5: Run GREEN**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_frontend_rule_state.W25CommandRenderTest -v
```

Expected: pass.

- [ ] **Step 6: Subagent review gate**

Spec review checks: the four sections exist and match the design. Code review checks: no text-overflow regressions, no broken click target binding, no unrelated CSS churn.

## Task 5: Full Verification And Final Review

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run targeted tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_health_api.AIContextApiTest tests.test_frontend_g2b tests.test_frontend_rule_state -v
```

Expected: pass or report exact unrelated failures separately.

- [ ] **Step 2: Run compile and diff checks**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q scripts tests
git diff --check
```

Expected: exit 0.

- [ ] **Step 3: Browser/manual check if a local service is available**

Use `18088` preview only. Do not POST to `8088`. Check W25 desktop/half-width for non-overlap, visible S0 reason, task queue, and freshness strip.

- [ ] **Step 4: Final subagent code review**

Dispatch a final reviewer over the full diff with the design and this plan. Fix Critical and Important findings before reporting completion.

- [ ] **Step 5: Report final status**

Report key changes, verification commands and results, remaining risks, and any production deployment steps needed. Do not claim completion without fresh verification output.
