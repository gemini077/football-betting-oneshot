# NOWSCORE-JC-SALES-PAGE-1

Status: `READY_FOR_ACCEPTANCE`

Decision: `PASS`

STOP state: `READY_FOR_ACCEPTANCE`; PR #141 remains open. Do not merge and do
not start Challenger Promotion Review.

## Exact remote evidence

- GitHub Actions runner: [33474080863](https://github.com/gemini077/football-betting-oneshot/actions/runs/33474080863)
- Head tested: `748aaf071009ed286eb59b9fcebf200d769be739`
- Direct JC replay artifact:
  `docs/data-foundation/NOWSCORE-JC-SALES-PAGE-1_PROBE_RUN_33474080863.json`
- Artifact SHA-256:
  `CF79BD08BC78370E24FD570CFE2FE5EA82C499DE794C12CB5852225D2839063A`
- Local canonical/identity/Universe/BASE replay:
  `docs/data-foundation/NOWSCORE-JC-SALES-PAGE-1_INTEGRATION_REPLAY.json`
- Integration replay SHA-256:
  `43A1FAECB8D6A379A3DB93BB4F5ACEAED74D536FE3E4000909E3A272491DD2FA`

The remote run completed successfully. Both direct sales-page responses were
HTTP 200. The public direct page is credential-free and is now the only
current-universe membership and business-date authority.

## Deterministic contract

URL template:

`https://cp.nowscore.com/buy/jingcai.aspx?typeID=101&oddstype=2&date={business_date}`

Accepted rows must come from the page's selected `SelDate`, the matching
`niDate` header date/group, and the explicit `11:00--次日11:00` sales window.
The page supplies the `周XNNN` match number, unique Nowscore match ID,
sales-row ID, kickoff, home/away, league, and `cansale`. Kickoff calendar date
is retained as a separate field and is never used to derive business date.

JC membership is persisted as:

- `jc_membership = VERIFIED`
- `jc_membership_source = nowscore_public_jc_sales`
- `business_date_source = nowscore_public_jc_sales`

No team, league, kickoff-similarity, weekday, fixed cutoff, or A32 heuristic
is used. `SetLevel(3)` / `A[j][32] == 1` is optional corroboration only.

## Paired replay

| business date | group | direct rows | accepted rows | next-calendar-day kickoff rows | duplicate IDs | ambiguous IDs | A32 corroborated | missing live row |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-08-31 | 周一001–012 | 12 | 12 | 12 | 0 | 0 | 12 | 0 |
| 2026-09-01 | 周二001–010 | 10 | 10 | 10 | 0 | 0 | 0 | 10 |

The direct Nowscore ID overlap across the paired dates is `0`, and the
accepted-ID overlap is `0`. Therefore the known 2026-08-31 12-match universe
stays on business date 2026-08-31 even though every kickoff is on
2026-09-01. The 2026-09-01 10-match universe stays on business date
2026-09-01 even though every kickoff is on 2026-09-02.

The 2026-09-01 live `ft1/scN` surfaces contain none of those ten direct-page
IDs. All ten direct rows remain accepted; no synchronization wait or A32
intersection is required.

## Integration replay

For both paired dates, the local replay produced:

- direct fetch: `success=true`, 12 and 10 rows;
- canonical schedule: `success=true`, 12 and 10 rows;
- identity binding: 12 and 10 exact bindings, ambiguous `0`, missing `0`;
- Prediction Universe: `READY`, 12 and 10 fixtures;
- BASE jobs: `READY`, 12 and 10 jobs;
- explicit Nowscore IDs preserved through the existing identity and
  Nowscore evidence handoff.

The existing `base_prediction_runner` continues to pass each persisted
`nowscoreId` to `fetch_match_markets(..., explicit_id=...)`; Champion, model,
identity thresholds, frozen history, result settlement, and prospective
history were not changed.

## Source cleanup result

The current-universe path is now:

`Nowscore JC sales page → canonical fixture / identity → existing Nowscore market/analysis evidence → BASE`

Sporttery and 500 are not current-universe blocking dependencies. Their
independent optional official-market/corroboration and recent-form/market
evidence capabilities remain available. No unrelated provider module was
deleted.

## Validation

- focused tests: `43 passed`;
- related regression tests: `95 passed, 6 warnings`;
- `py_compile`: PASS;
- `git diff --check`: PASS;
- no Champion/model, identity-threshold, frozen-history, prospective-ledger,
  or settlement mutation.
