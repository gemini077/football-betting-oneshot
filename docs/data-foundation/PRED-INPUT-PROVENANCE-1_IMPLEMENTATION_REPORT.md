# PRED-INPUT-PROVENANCE-1 Implementation Report

Date: 2026-08-31
Base: `c0a30839867eefd83d822643e54eecc15cafec7f`
Production run: `33399507542`
Delivery branch: `codex/pred-input-provenance-1`
Status: `READY_FOR_ACCEPTANCE`

## Result

The umbrella classification was caused by a general runner contract bug, not
by one team or fixture. `_nowscore_source()` and `_five_hundred_source()` used a
boolean second return value for fetch exceptions and non-usable source results.
When no recent form remained, `_assemble_context()` converted that boolean to
`INPUT_TIMESTAMP_UNVERIFIED`, even when the observed failure was a source fetch
failure. Deterministic snapshot construction and the two snapshot cutoff checks
also collapsed into the same error without retaining the failing stage.

The rule-based fix keeps the existing fail-closed eligibility gate and adds a
durable `input_provenance_diagnostic` to failed BASE jobs. Each diagnostic
records the primary stage, source, status, bounded detail, references, and all
observed source attempts. The ledger and runner summary also expose
`input_provenance_failure_stages`. A source fetch failure now remains
`SOURCE_FETCH_FAILED`; timing failures retain `INPUT_TIMESTAMP_UNVERIFIED` but
carry their exact stage.

No current or historical timestamp was inferred or rewritten. A successful
prematch freeze clears a prior diagnostic, so valid existing frozen predictions
remain on the existing Champion path.

## Durable evidence audit

The audit read only the explicit production/history paths below and counted
unique fixture IDs rather than counting every revision as a separate match.

| Evidence | Count | What it proves |
|---|---:|---|
| `data/base_prediction_jobs/*.json` ledgers inspected | 22 | The available BASE history window |
| Durable BASE `INPUT_TIMESTAMP_UNVERIFIED` jobs | 2 / 2 unique fixtures | Only `500-1363834` and `500-1363823`, both on 2026-08-31 |
| `data/match_analysis` umbrella revisions | 119 / 18 unique fixtures | Historical umbrella failures retain no causal stage |
| Production 500 deep page fetch failures in run `33399507542` | 18 pages / 3 fallback attempts | Six page types failed with `URL Error: [Errno 111] Connection refused` |

The two current jobs contain only `last_error=INPUT_TIMESTAMP_UNVERIFIED`;
their durable records have no Nowscore result, source status, source capture
timestamp, page-error list, or per-fixture runner trace. The production log
proves that the 500 deep fallback failed for the three jobs that reached that
fallback, but does not emit the fixture ID beside each six-page group. It is
therefore not valid to backfill a per-fixture historical cause from that log.

The 119 historical revisions all have
`status.reason_code=INPUT_TIMESTAMP_UNVERIFIED`, null
`timestamps.source_cutoff_at`, null recent-form capture time, empty market
capture facts, and no source references. Their declared
`recent_form_source=nowscore` is not causal proof. Those 18 fixtures remain
`UNPROVEN_FROM_DURABLE_EVIDENCE`; none is relabeled as a timestamp, fetch,
cache, or form failure.

Available recent BASE history used for the replay boundary:

| Business date | Fixtures | Frozen | Insufficient | Missed | Stored failure |
|---|---:|---:|---:|---:|---|
| `2026-08-29` | 29 | 24 | 1 | 4 | `MISSING_RECENT_FORM: 1` (cause not further proven) |
| `2026-08-30` | 25 | 23 | 0 | 2 | none |
| `2026-08-31` | 12 | 9 | 3 | 0 | `INPUT_TIMESTAMP_UNVERIFIED: 2`, `MISSING_RECENT_FORM: 1` |

The nine current frozen job-to-record pairs remain byte-stable in the
read-only verification inventory (inventory SHA-256:
`9d9159be2745d01650894c90d233689c58dc4b8a3cef677f71023695b9ab6f85`).

Current target trace:

| Fixture | Durable terminal state | Proven causal stage | Evidence boundary |
|---|---|---|---|
| `500-1363834` | `INSUFFICIENT_DATA` / umbrella | Not historically provable | Same run contains 500 deep fetch failures, but no fixture-to-page mapping and no durable Nowscore result |
| `500-1363823` | `INSUFFICIENT_DATA` / umbrella | Not historically provable | Same as above |
| `500-1427969` | `INSUFFICIENT_DATA` / `MISSING_RECENT_FORM` | Not historically provable | The stored error does not distinguish empty form from source unavailability |

## Stage classification

The durable counts below are historical proof, not guesses. The replay column
shows that the new deterministic diagnostic path can distinguish each stage
without making the evidence eligible.

| Stage | Durable proven count | Bounded replay/example | Terminal behavior |
|---|---:|---|---|
| `SOURCE_HAS_NO_USABLE_RECENT_FORM` | 0 proven (`1` stored `MISSING_RECENT_FORM` remains unproven) | Empty source with no fetch error | `MISSING_RECENT_FORM` |
| `SOURCE_FETCH_FAILED` | 18 page failures / 3 fallback attempts; target-level mapping unproven | Current two production-shaped replays; Nowscore `FETCH_ERROR`; 500 error envelope | `SOURCE_FETCH_FAILED` |
| `SOURCE_OBSERVATION_TIMESTAMP_MISSING_OR_INVALID` | 0 | Source result without parseable capture time | `INPUT_TIMESTAMP_UNVERIFIED` |
| `CACHE_PROVENANCE_INVALID` | 0 | Invalid recent-form cache provenance | `CACHE_PROVENANCE_INVALID` |
| `EXISTING_FORM_TIMESTAMP_INVALID` | 0 | Existing form snapshot at/after cutoff | `INPUT_TIMESTAMP_UNVERIFIED` |
| `OFFICIAL_MARKET_TIMESTAMP_INVALID` | 0 | Official SPF without parseable capture time | `INPUT_TIMESTAMP_UNVERIFIED` |
| `DETERMINISTIC_INPUT_SNAPSHOT_CONSTRUCTION_FAILED` | 0 | Snapshot builder exception or invalid return | `INPUT_SNAPSHOT_CONSTRUCTION_FAILED` |
| `SOURCE_CUTOFF_FAILED` | 0 | Source cutoff missing, current, or post-kickoff | `INPUT_TIMESTAMP_UNVERIFIED` |
| `MARKET_SNAPSHOT_CUTOFF_FAILED` | 0 | Market cutoff missing, current, or post-kickoff | `INPUT_TIMESTAMP_UNVERIFIED` |
| `OTHER_DETERMINISTIC_CAUSE` | 0 proven | Invalid adapter/provider ID or unclassified adapter status | `INPUT_PROVENANCE_UNVERIFIED` |
| Historical/current durable records without causal evidence | 20 unique fixture records | No backfill performed | Remain unchanged and fail closed |

## Gate decision

1. A general bug is proven in the boolean-to-umbrella error path.
2. The fix is rule-based and applies to every source/fixture through the same
   diagnostic contract.
3. Prematch evidence remains fail-closed when capture time, cutoff, cache
   provenance, or deterministic snapshot construction cannot be proven.
4. No production Champion, frozen prediction, prospective ledger, or current
   historical artifact was mutated.
5. The two current fixtures are not made eligible by this change; that is not
   the acceptance criterion.

## Verification evidence

- Baseline focused suite before implementation: `100 passed`.
- Final BASE/provenance/cache suite: `45 passed` in
  `tests/test_base_prediction_runner.py` and
  `tests/test_openfootball_recent_form_p0.py`.
- Related model/dashboard/health/automation suite: `114 passed` (`159 passed` across
  the final focused command).
- Full suite excluding the unrelated existing live-ev collector failure:
  `964 passed, 5 failed`. The five failures are existing Champion-core SHA
  expectations and an existing public-site fixture that omits
  `data/prediction_dashboard/latest.json`; neither changed file is in this
  milestone.
- Full collection remains blocked by the same pre-existing collector import:
  `tests/test_live_ev_profile.py` imports `PUBLIC_DATA_DIRS`, absent from the
  baseline `scripts/build_public_site.py`.
- Covered regressions: current two production-shaped replays classify source
  fetch failure; 500 error envelopes do not become verified timestamps; empty
  form remains distinct; missing/late source capture is rejected; invalid
  existing form/cache/official market and deterministic cutoff stages are
  retained; valid frozen reruns remain idempotent; post-kickoff evidence is not
  accepted.
- `git diff --check`: PASS.
- `python -m py_compile` for the four changed runtime modules: PASS.
- The two target replays used a temporary root and intercepted writes; the
  repository durable-file set was not changed by replay.

## Scope and stop state

Changed scope is limited to the BASE runner provenance classification, recent
form cache diagnostics, dashboard labels for the new machine errors, focused
tests, and milestone evidence. No dependency, model, Champion, identity,
provider, frozen history, or production-data rewrite is included.

This milestone stops at `READY_FOR_ACCEPTANCE`. No merge and no next milestone
are started.
