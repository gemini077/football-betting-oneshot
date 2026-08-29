# HC-AUTO-1 implementation plan

## Scope

Build a league-agnostic historical coverage foundation around the existing
`football-data.co.uk` and `OpenFootball` adapters, manifests, reviewed
identity evidence, and authoritative historical DuckDB. The current Champion,
frozen predictions, historical ledger, and Sweden/DC research implementation
remain unchanged.

The existing `tasks/plan.md` and `tasks/todo.md` belong to an older Phase 2A
workstream and are intentionally left untouched.

## Ordered work

1. Add a versioned coverage contract and data-driven competition catalog; load
   source manifests and authoritative history without duplicating records.
2. Add an exact-only identity resolver and an automatic gate returning
   `SUPPORTED`, `DEGRADED`, or `UNSUPPORTED` with auditable reason codes.
3. Integrate the gate at Prediction Universe → BASE job ledger intake. Coverage
   metadata must never remove a job or change Champion input selection.
4. Run a read-only audit against the current mixed daily fixture snapshots and
   the existing real provider identity sample. Store only HC-AUTO-1 evidence;
   do not rebuild or mutate the historical store.
5. Update the minimum governance pointer, run focused and full tests, review the
   diff for production/frozen-data safety, commit on `codex/hc-auto-1`, and
   leave GitHub PR evidence. End at `READY_FOR_ACCEPTANCE`.

## Explicit non-goals

- No Sweden-specific or Dixon–Coles computation or tuning.
- No country-specific adapters, new paid providers, xG, lineup, injury,
  player-model, PA-3, Champion promotion, or frontend redesign.
- No fuzzy identity matching, invented history, frozen prediction rewrite, or
  indiscriminate global historical backfill.

## Verification gates

- Contract tests cover manifest/source aggregation, identity coverage, history
  depth, freshness, and restriction metadata.
- Gate tests cover all three statuses and every required reason-code family.
- Batch audit proves an unsupported fixture does not block supported/degraded
  fixtures.
- Existing BASE job tests and Champion isolation tests remain green.
- Historical DuckDB count/digest and frozen prediction digests are unchanged.
- `python -m pytest` passes before the branch is marked
  `READY_FOR_ACCEPTANCE`.
