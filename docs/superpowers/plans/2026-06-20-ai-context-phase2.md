# Dashboard 3.0 Phase 2 AI Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a read-only `/api/ai/context` endpoint so Codex, Yangmi, Wenmi, and future sidecar agents can read the same live dashboard facts without scraping the UI.

**Architecture:** Keep the existing Python bridge, SQLite, account SSOT, health gate, rule_state, and ticket APIs. Add a focused context builder in `scripts/bridge.py` that composes existing read-only facts into a stable JSON contract, then expose it through `BridgeHandler.do_GET`. Do not add any POST behavior, data writes, or new external data source.

**Tech Stack:** Python stdlib HTTP handler, existing SQLite helpers in `scripts/db.py`, account SSOT in `scripts/account_ssot.py`, Python `unittest`.

---

## Scope

Included:

- `GET /api/ai/context` returns a stable JSON fact protocol.
- Context includes mode, situation, freshness, evidence, alerts, risks, tickets, positions, candidates, next actions, and human-required actions.
- Stale/dead/untrusted data is visible and blocks action-oriented suggestions.
- Tests cover healthy, stale/dead, risk-blocked, ticket-conflict, and handler access.
- A Yangmi/Claude Code usage guide explains how to query and interpret the endpoint during watch sessions.

Excluded:

- Sidecar agent automation.
- Review packet generation.
- Any trade write endpoint changes.
- Any production POST tests.
- Any `data/*` git changes.

## File Structure

- Modify `scripts/bridge.py`
  - Add `_build_ai_context(now=None)`.
  - Add helper functions for mode, freshness, evidence, ticket summary, human-required actions, and compact candidates.
  - Add `GET /api/ai/context` in `BridgeHandler.do_GET`.

- Modify `tests/test_health_api.py`
  - Add `AIContextApiTest`.
  - Reuse existing temp DB/cache helpers.
  - Test builder and GET handler without real 8088 POST.

- Create `docs/ops/yangmi-ai-context-runbook.md`
  - Claude Code / Yangmi operating guide.
  - Commands, interpretation rules, and guardrails.

- Modify `AGENTS.md`
  - Add the new AI fact outlet to the API table and Yangmi workflow note.

## Task 1: Context Builder Core Contract

**Files:**
- Modify: `tests/test_health_api.py`
- Modify: `scripts/bridge.py`

- [x] **Step 1: Write failing tests for core contract**

Add tests in `AIContextApiTest`:

```python
def test_ai_context_has_stable_top_level_contract(self):
    ctx = bridge._build_ai_context()
    for key in ["date", "mode", "situation", "evidence", "alerts", "risks",
                "tickets", "positions", "candidates", "freshness",
                "next_actions", "human_required"]:
        self.assertIn(key, ctx)
    self.assertIn("trade_entry_allowed", ctx["situation"])
    self.assertIn("health", ctx["situation"])
    self.assertIn("connection", ctx["situation"])
    self.assertIsInstance(ctx["positions"], list)

def test_ai_context_includes_freshness_for_quotes_iwencai_account_and_baseline(self):
    ctx = bridge._build_ai_context()
    freshness = ctx["freshness"]
    for key in ["quotes", "iwencai", "account", "baseline"]:
        self.assertIn(key, freshness)
        self.assertIn("status", freshness[key])
```

- [x] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_health_api.AIContextApiTest -v
```

Expected: fails because `_build_ai_context` does not exist.

- [x] **Step 3: Implement minimal core builder**

Add `_build_ai_context(now=None)` in `scripts/bridge.py` near `_build_health()` helpers. It should:

- load health with `_build_health()`;
- load account with `load_current_account_state(CACHE.get("live_quotes", {}), create_anchor=False)`;
- load rule_state with `_build_rule_state(account_state=account_state)`;
- compute `trade_entry_allowed` through `_trade_entry_gate(health, rule_state)`;
- return stable keys even when a subsection is empty;
- never call write helpers.

If the account SSOT has no today anchor, `/api/ai/context` must report unavailable account facts and blocked trade entry. It must not create a recovery or previous-close anchor just because an AI agent read the endpoint.

- [x] **Step 4: Run tests and verify GREEN**

Run:

```bash
python3 -m unittest tests.test_health_api.AIContextApiTest -v
```

Expected: contract tests pass.

- [x] **Step 5: Subagent audit**

Dispatch a read-only subagent reviewer for Task 1. Ask it to check read-only behavior, field stability, and test coverage.

## Task 2: Risks, Tickets, Human Actions, and GET Handler

**Files:**
- Modify: `tests/test_health_api.py`
- Modify: `scripts/bridge.py`

- [x] **Step 1: Write failing tests for action safety**

Add tests that assert:

- stale/dead quotes add a risk and a human-required action before trading;
- `rule_state.blocks` are exposed in `risks`;
- open ticket conflicts are exposed in `alerts`;
- `GET /api/ai/context` returns HTTP 200 JSON.

- [x] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_health_api.AIContextApiTest -v
```

Expected: tests fail because risks/alerts/handler are incomplete.

- [x] **Step 3: Implement safety expansion**

In `scripts/bridge.py`:

- add `_ai_ticket_summary(date_str)` using `query_trade_tickets`;
- add `_ai_open_ticket_conflicts(date_str)` using read-only SQL against `ticket_conflict_log`;
- convert health critical failures and rule blocks to `risks`;
- convert open conflicts and degraded health reasons to `alerts`;
- add `human_required` entries for blocked trading, stale/dead data, ticket conflicts, and any buy/add/sell/clear ticket that is executable/pending;
- add `elif parsed.path == '/api/ai/context'` to `BridgeHandler.do_GET`.

- [x] **Step 4: Run tests and verify GREEN**

Run:

```bash
python3 -m unittest tests.test_health_api.AIContextApiTest tests.test_health_api.HealthStratificationTest -v
python3 -m compileall -q scripts tests
```

Expected: tests pass.

- [x] **Step 5: Subagent audit**

Dispatch a read-only subagent reviewer for Task 2. Ask it to check stale/dead fail-closed semantics, no POST behavior, and endpoint handler correctness.

## Task 3: Yangmi Usage Guide and Final Verification

**Files:**
- Create: `docs/ops/yangmi-ai-context-runbook.md`
- Modify: `AGENTS.md`

- [x] **Step 1: Write the runbook**

The runbook must include:

- `curl -s http://127.0.0.1:8088/api/ai/context | python3 -m json.tool`;
- how Yangmi should answer common watch questions from context first;
- when to fall back to same-session external queries;
- field meanings for `freshness`, `risks`, `alerts`, `human_required`, and `tickets`;
- guardrails: no `/api/sync` POST, no data writes, no trading action without user confirmation.

- [x] **Step 2: Update AGENTS.md**

Add `/api/ai/context` to the API table and note that Yangmi should read it first during watch sessions.

- [x] **Step 3: Verify docs and tests**

Run:

```bash
python3 -m unittest tests.test_health_api.AIContextApiTest -v
python3 -m compileall -q scripts tests
git diff --check
```

- [x] **Step 4: Final subagent audit**

Dispatch one read-only subagent reviewer for the entire Phase 2 diff.

- [x] **Step 5: Commit and push**

Stage only code, tests, and docs related to Phase 2. Do not stage `data/*`.

```bash
git add scripts/bridge.py tests/test_health_api.py docs/ops/yangmi-ai-context-runbook.md AGENTS.md docs/superpowers/plans/2026-06-20-ai-context-phase2.md
git commit -m "Add AI context endpoint for dashboard agents"
git push origin codex/dashboard-3-phase1
```
