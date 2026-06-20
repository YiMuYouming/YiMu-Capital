# Dashboard 3.0 Phase 3 Closeout Baseline

> Date: 2026-06-20
> Scope: close Dashboard 3.0 at Phase 3 and defer Phase 4 sidecar-agent watch service to the next version.
> Owner: 欧米

## Version Boundary

Dashboard 3.0 is closed after Phase 3.

| Phase | Status | Result |
|---|---|---|
| Phase 0 | Complete | Baseline protected by clean git workflow and pushed commits. |
| Phase 1 | Complete | Cockpit slimming and named layout work made the first screen flexible without changing data SSOT. |
| Phase 2 | Complete | `/api/ai/context` provides a read-only agent fact contract for health, freshness, risks, tickets, and human-required actions. |
| Phase 3 | Complete | `review_source_packet.json` is generated during close-day flow and consumed by WorkBuddy review skills. |
| Phase 4 | Deferred | Sidecar Agent is no longer part of V3. It becomes the next version's agent-watch theme. |

## Phase 3 Data Flow

```text
close_day.py --apply
  -> cloud SQLite consistency backup
  -> pull local pnl.db and runtime JSON
  -> local SQLite integrity check
  -> ticket review markdown
  -> data/review_packets/YYYY-MM-DD/review_source_packet.json
  -> live-dashboard specialized data backup tar.gz
  -> OSS upload
```

`close_day.py --dry-run` previews the packet path and source status without writing it.

## SSOT Rules

| Domain | Source of Truth |
|---|---|
| Account, PnL, positions, trades | live-dashboard SQLite + account SSOT APIs |
| Intraday agent facts | `/api/ai/context` |
| Review source packet | `data/review_packets/YYYY-MM-DD/review_source_packet.json` |
| Final daily review and next-day plan | Vault review note |
| W12/W13 next-day pools | Vault review note data appendix |
| Code history | Git |
| Runtime data backup | `data/backups/live-dashboard-data/*.tar.gz` + OSS |

Hard boundary: `review_source_packet.json` is an evidence input. It must not become the final review note, the next-day plan, or the W12/W13 SSOT.

## Agent Usage

### 洋米

- During intraday watch or troubleshooting, read `/api/ai/context` first.
- Do not infer tradability from stale/dead/untrusted values.
- Use ticket and rule-gate boundaries before suggesting any action.

### 稳米

- During `daily-review` Stage A, first try:
  ```bash
  /Users/yimu/Documents/YM_Capital/live-dashboard/data/review_packets/$(date +%F)/review_source_packet.json
  ```
- Use the packet for account, PnL, positions, trades, ticket loop, health/freshness, and known blockers.
- Use `auto-review-fill` / iwencai for market, limit-up, watchlist, sector, and style data.
- If packet is missing or stale, mark a data gap and continue the old review flow.
- Keep Vault review note as final SSOT.

### 欧米

- Treat Dashboard 3.0 as closed unless fixing a regression in Phase 1-3 behavior.
- Start a new spec/plan for Sidecar Agent instead of extending this V3 plan.

## Validation Evidence

Latest Phase 3 implementation commit:

```text
e59fc3b Add review source packet generation
```

Commands used for Phase 3 verification:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_review_source_packet tests.test_ops_scripts tests.test_health_api.AIContextApiTest -v
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q scripts tests && git diff --check
python3 scripts/ops/close_day.py --dry-run --date 2026-06-20
```

Subagent audit result: no blockers, no medium-risk issues.

## Next Version Seed

Next version theme: Agent watch Sidecar.

Initial scope should be:

- Read-only sidecar over `/api/ai/context`.
- No POST, no auto-trading, no account mutation.
- Periodic summaries, abnormal-state alerts, candidate ranking, and ticket drafts.
- Human-required boundary for every buy/sell/risk-limit action.
- Separate spec and implementation plan before coding.
