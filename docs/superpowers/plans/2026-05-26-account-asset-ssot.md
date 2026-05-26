# Account Asset SSOT Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one authoritative intraday account state from a locked anchor, append-only executed trades, and live valuation.

**Architecture:** Add an account reducer that seeds one SQLite anchor with a trade-ID cutoff and replays only events appended after that anchor. API summary and PnL snapshot creation consume reducer output, while legacy JSON positions remain a non-authoritative display mirror during migration.

**Tech Stack:** Python 3 standard library, SQLite, `unittest`, vanilla JavaScript widgets.

---

### Task 1: Account reducer contract

**Files:**
- Create: `scripts/account_ssot.py`
- Create: `tests/test_account_ssot.py`

- [ ] Write failing unit tests for buy/sell replay, recovery-anchor filtering, append-ID ordering, quote-only valuation changes, and missing/stale-quote degradation.
- [ ] Run `python3 -m unittest tests.test_account_ssot -v`; expect import or assertion failures before implementation.
- [ ] Implement `trade_cash_effect()`, `reduce_account_state()` and price completeness handling.
- [ ] Run `python3 -m unittest tests.test_account_ssot -v`; expect the reducer tests to pass.

### Task 2: Persistent daily anchor

**Files:**
- Modify: `scripts/db.py`
- Modify: `scripts/account_ssot.py`
- Modify: `tests/test_account_ssot.py`

- [ ] Add a failing test showing that a recovery anchor excludes existing transaction IDs but still accepts a later backfilled trade with an earlier display time.
- [ ] Add `account_baselines` schema, `trade_id_cutoff`, and read/insert helpers.
- [ ] Implement `ensure_today_anchor()` from repaired dashboard cash, current positions, and day-start asset metadata.
- [ ] Run the account tests and confirm a second read reuses the locked anchor.

### Task 3: Backend API and snapshot ownership

**Files:**
- Modify: `scripts/bridge.py`
- Modify: `scripts/collectors/quotes.py`
- Modify: `tests/test_account_ssot.py`
- Modify: `tests/test_incident_guards.py`

- [ ] Add failing tests for rejecting `/api/sync` asset overrides and for state output superseding snapshot totals.
- [ ] Add `/api/account/state`; make `/api/pnl/summary` merge only chart metadata from SQLite snapshots and asset fields from SSOT.
- [ ] Expose full-day ledger records from `/api/account/state` for W15 audit display.
- [ ] Reject `payload.pnl` in `/api/sync`; remove imperative cash changes from its trade insertion path.
- [ ] Make `log_pnl_snapshot()` write values returned by SSOT and skip incomplete valuations.
- [ ] Bind the HTTP singleton port before scheduler/bootstrap work so failed duplicate startups cannot write data.
- [ ] Run all Python tests and compile checks.

### Task 4: Frontend command boundary

**Files:**
- Modify: `widgets/positions.js`
- Modify: `widgets/input-panel.js`
- Modify: `index.html`

- [ ] Remove browser-side available-cash calculation from W15 trade submission.
- [ ] Remove editing/deleting executed trade actions and direct holding quantity editing from W15 during ledger migration.
- [ ] Remove W16 direct asset fields and `/api/sync` PnL submission; retain market/sentiment manual inputs.
- [ ] Make W15 render daily operations from the server ledger and use live SSOT for W22 today's headline return.
- [ ] Run `node --check` for changed JavaScript and inspect W15/W22 in the browser.

### Task 5: Deployment and operational handoff

**Files:**
- Modify: `docs/audit/2026-05-26_incident_report.md`

- [ ] Back up `data/pnl.db` before service restart.
- [ ] Restart bridge and query `/api/account/state`, `/api/pnl/summary`, and `/api/pnl?range=today&index=sh`.
- [ ] Confirm the new recovery anchor exists once and that new duplicate trade sync does not alter cash twice.
- [ ] Give 洋米 the remaining next-day baseline, close settlement, alerts, and replay rehearsal checklist.
