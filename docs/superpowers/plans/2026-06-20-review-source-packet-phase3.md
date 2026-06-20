# Dashboard 3.0 Phase 3 Review Source Packet Plan

> Status: completed on 2026-06-20. This replaces the broader "review packet" idea with a narrower source packet that feeds WorkBuddy daily-review without replacing it.

## Goal

Generate a close-day `review_source_packet.json` from live-dashboard facts so Wenmi can use it during WorkBuddy `daily-review` stages A and B. The packet is an input evidence bundle, not the final review record.

## SSOT Boundaries

| Domain | SSOT | Phase 3 Role |
|---|---|---|
| Account, PnL, positions, trades | live-dashboard SQLite + account SSOT APIs | Read and summarize into source packet |
| Intraday agent facts | `/api/ai/context` | Include freshness, risks, tickets, human-required actions |
| Market fill data | WorkBuddy `auto-review-fill` + iwencai/ym pipeline | Continue to fill market and watchlist tables |
| Daily review, lessons, next-day plan | Vault review note | Final human/AI review SSOT |
| Dashboard next-day baseline | Vault review note -> `gen_dashboard_data.py` | Unchanged |

Hard rule: `review_source_packet.json` must never become the source for W12/W13 next-day pools. W12/W13 still parse the Vault review note data appendix after Wenmi finishes the review.

## Data Flow

```text
close_day.py --apply
  -> pull cloud data and verify local integrity
  -> generate ticket review summary
  -> generate review_source_packet.json
  -> archive live-dashboard specialized data package
  -> Wenmi daily-review reads packet in Stage A
  -> Wenmi writes Vault review note by output protocol
  -> gen_dashboard_data.py reads Vault review note for next-day dashboard baseline
```

## Proposed Packet Location

Local project:

```text
/Users/yimu/Documents/YM_Capital/live-dashboard/data/review_packets/YYYY-MM-DD/review_source_packet.json
```

Cloud runtime:

```text
/home/agentuser/YiMu-Capital/data/review_packets/YYYY-MM-DD/review_source_packet.json
```

`data/*` remains out of git. The packet is covered by close-day data backup, not code commits.

## Packet Contract

Required top-level keys:

- `schema_version`: `review_source_packet.v1`
- `date`
- `generated_at`
- `source_status`: freshness and missing-source summary
- `ai_context`: compact copy of `/api/ai/context`
- `account`: total asset, PnL, position pct, valuation completeness
- `positions`: current positions, T+1/sellable state, floating PnL
- `trades`: same-day trades and ticket links where available
- `tickets`: ticket counts, unresolved conflicts, completed/blocked items
- `pnl`: daily, week, month summary if available
- `review_hints`: candidate facts Wenmi can cite, never final conclusions
- `manual_required`: fields that still need Yimu confirmation, such as pan-feel, operation reasons, and Tonghuashun-only values

If any upstream is stale/dead/untrusted, the packet must preserve that status and add a `manual_required` item. It must not convert stale data into clean review facts.

## WorkBuddy Integration

`daily-review` Stage A should first look for today's `review_source_packet.json`. If present:

- use it for account, PnL, positions, ticket loop, trade facts, health/freshness, and known blockers;
- report packet freshness and missing fields in the Stage A data completeness output;
- still use `auto-review-fill` / iwencai for market, limit-up, watchlist, sector, and style inputs not covered by dashboard;
- never overwrite Yimu-provided facts or confirmed review text.

If the packet is missing, Wenmi continues the old daily-review path and marks "Dashboard source packet missing" as a data gap, not a blocker.

## Implementation Tasks

1. Done: Add `scripts/ops/generate_review_source_packet.py`.
2. Done: Add unit tests for packet contract, stale fail-closed behavior, and no DB/file mutation except the target output path.
3. Done: Wire `scripts/ops/close_day.py --apply` to generate the packet after cloud data pull, local integrity check, and ticket review summary, before the specialized data package backup.
4. Done: Update WorkBuddy `daily-review` and `auto-review-fill` instructions to consume the packet.
5. Done: Run a read-only subagent audit for SSOT boundaries, data safety, and Wenmi workflow clarity.

## Acceptance

- Dry-run prints the packet path and missing-source summary without writing.
- Apply writes exactly one dated packet under `data/review_packets/YYYY-MM-DD/`.
- Packet generation does not call POST endpoints and does not create account anchors.
- Wenmi skill states that Vault review note remains the final daily review SSOT.
- Existing dashboard tests still pass.

## Completion Evidence

- Commit: `e59fc3b Add review source packet generation`
- Branch: `codex/dashboard-3-phase1`
- Verification:
  - `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_review_source_packet tests.test_ops_scripts tests.test_health_api.AIContextApiTest -v`
  - `PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q scripts tests && git diff --check`
  - `python3 scripts/ops/close_day.py --dry-run --date 2026-06-20`
- Subagent audit: no blockers, no medium-risk issues.

## V3 Boundary

Dashboard 3.0 closes at Phase 3. Phase 4 sidecar-agent watch service is deferred to the next version and should not be treated as a remaining V3 task.
