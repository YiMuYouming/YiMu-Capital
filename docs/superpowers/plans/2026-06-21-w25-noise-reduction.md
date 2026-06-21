# W25 Noise Reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make W25's first screen show only the core decision, human-readable reason, direct action buttons, and the few data issues that matter immediately.

**Architecture:** Keep `/api/ai/context` unchanged. Add a presentation-only layer in `evidence-summary.js` that derives concise action labels, grouped queue items, data freshness summary, and top evidence from the existing command snapshot. Update `widgets/evidence-board.js` and `css/theme.css` to render the first screen as a command surface, with widget IDs as secondary route hints.

**Tech Stack:** Plain JavaScript widgets, existing `EvidenceSummary`, existing CSS, Python unittest with Node-based widget rendering.

---

### Task 1: Summary Model For Human-Readable First Screen

**Files:**
- Modify: `evidence-summary.js`
- Test: `tests/test_frontend_rule_state.py`

- [x] **Step 1: Write failing summary tests**

Add tests to `W25CommandSummaryTest` asserting:
- `summary.command.primary_actions` uses labels like `打开风控门禁`, not bare `W14`.
- `summary.command.primary_actions` includes `target` routes for clicking.
- `summary.display_queue` is grouped to at most 3 visible items for W25 while raw `summary.action_queue` remains available.
- `summary.freshness_summary` includes `tradable_count`, `review_count`, and only the urgent rows for first-screen rendering.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_frontend_rule_state.W25CommandSummaryTest -v
```

Expected: the new tests fail because the summary fields do not exist yet.

- [x] **Step 2: Implement the presentation summary**

In `evidence-summary.js`, add small helpers that derive:
- `primary_actions`: first two direct actions, each with `label`, `target`, `caption`.
- `display_queue`: grouped queue items capped at 3 for W25 first screen.
- `freshness_summary`: count of tradable rows and urgent non-tradable rows.
- `top_evidence`: up to 3 evidence items that directly explain the current command.
- normalized `risks` / `alerts`: `ai_context` risks and ticket alerts remain visible, with ticket conflict targets routed to W24 even when the raw target is a stock code.

Run the same W25 summary test command and expect it to pass.

### Task 2: Render W25 As A Command Surface

**Files:**
- Modify: `widgets/evidence-board.js`
- Modify: `css/theme.css`
- Test: `tests/test_frontend_rule_state.py`

- [x] **Step 1: Write failing render tests**

Add tests to `W25CommandRenderTest` asserting:
- W25 renders business action labels such as `打开风控门禁` and `核对账户持仓`.
- Widget IDs remain visible only as secondary hints, such as `风控门禁 · W14`.
- F1 renders a compact summary like `可交易` and `需复核`, not every normal data source as an equally loud row.
- A1 renders no more than 3 actionable cards.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_frontend_rule_state.W25CommandRenderTest -v
```

Expected: the new tests fail because W25 still renders the dense queue and freshness table.

- [x] **Step 2: Implement the new W25 markup and styles**

Update `widgets/evidence-board.js` to render:
- S0 command headline and reason.
- Primary action buttons for direct component focus.
- A1 grouped tasks.
- F1 compact data trust summary with urgent issues only.
- E1 top evidence capped to three items.

Update `css/theme.css` to make compact cards readable without truncating key status text.
In cockpit mode, hide the W25 gate row so G1-G5 does not take over the first screen; the same blockers remain available through S0, A1, direct action buttons, and W14.

Run the W25 render tests and expect them to pass.

### Task 3: Verification And Review

**Files:**
- No new production files beyond Task 1 and Task 2.

- [x] **Step 1: Run targeted tests**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_frontend_rule_state.W25CommandSummaryTest tests.test_frontend_rule_state.W25CommandRenderTest tests.test_frontend_rule_state.EvidenceBoardWidgetTest tests.test_frontend_rule_state.WidgetPanelUxTest tests.test_evidence_summary -v
```

- [x] **Step 2: Run static checks**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q scripts tests
git diff --check
```

- [x] **Step 3: Browser-check W25**

Open `http://127.0.0.1:18088/`, inspect W25 in desktop and narrow viewport, and verify:
- no runtime error text;
- S0, A1, F1, E1 are visible;
- action buttons are clickable and carry `data-evidence-target`;
- key F1 text is not truncated into unreadable fragments.

- [x] **Step 4: Subagent review**

Ask a subagent to review the final diff for information hierarchy, routing correctness, and risk of hiding blockers.

- [ ] **Step 5: Commit**

```bash
git add evidence-summary.js widgets/evidence-board.js css/theme.css tests/test_frontend_rule_state.py docs/superpowers/plans/2026-06-21-w25-noise-reduction.md
git commit -m "Reduce W25 command cockpit noise"
```
