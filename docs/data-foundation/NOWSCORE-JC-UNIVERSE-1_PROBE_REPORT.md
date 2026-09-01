# NOWSCORE-JC-UNIVERSE-1 — Nowscore public JC universe

Status: `READY_FOR_ACCEPTANCE`

Decision gate: `PASS`

STOP state: do not merge and do not start Challenger Promotion Review.

## Evidence

- Target business date: `2026-09-01` (Asia/Shanghai).
- GitHub runner: [run 33466072890](https://github.com/gemini077/football-betting-oneshot/actions/runs/33466072890), executed from PR #141 head `c662d27c047dd0d6e6638b7c3c563fd6d22ff8f1`.
- Exact Nowscore probe JSON: `docs/data-foundation/NOWSCORE-JC-UNIVERSE-1_PROBE_RUN_33466072890.json`.
- Exact JSON SHA-256: `7162B858F11F5C8117C78504AD10A13991D69038E0186D4987C2CAB0B1C71536`.
- Public UI: [Nowscore current schedule](https://live.nowscore.com/schedule.aspx?f=ft1).
- Backing data: `https://live.nowscore.com/data/ft1.js`.
- GitHub page response: HTTP `200`, `41,570` bytes, SHA-256 `9da54e4788c6ea52db56b4f1db1a71e143e54aab192be7124a8508d2e1f70b03`.
- GitHub backing-data response: HTTP `200`, `182,128` bytes, SHA-256 `57348ffa33e4474c551c6d7e8bbda53705f053d0fc686098b7aa33085d7cf58e`.
- `fetched_at`: `2026-09-01T11:25:10+08:00`.

## Contract and gate result

The public page exposes the `SetLevel(3)` JC filter. Its page code sets the
row index to `32` for that filter and displays a match only when the backing
row satisfies the exact numeric predicate `A[j][32] == 1`. The implementation
accepts only that predicate; league, team names, kickoff similarity, odds,
and other row flags are not used to guess JC membership. No credential,
account, API key, or secret is required.

The runner observed:

| Check | Result |
|---|---:|
| Raw backing rows | 356 |
| Target-date rows | 152 |
| Explicit JC-flagged rows | 12 |
| Accepted current JC fixtures | 12 |
| Duplicate Nowscore IDs | 0 |
| Ambiguous Nowscore IDs | 0 |
| Page/data HTTP access | 200 / 200 |
| Decision gate | PASS |

For bounded future dates, the same implementation selects the public `sc1` …
`sc7` page/data surface by deterministic Asia/Shanghai date offset. The local
`sc1` route test returned five explicit JC rows for `2026-09-02`; no provider
fallback is used when a Nowscore JC surface fails.

## Exact current fixture set

The source did not provide a match number in the accepted schedule rows, so
`match_number` is explicitly `null` with
`match_number_source=not_present_in_schedule_row`. Every row has a deterministic
Nowscore match ID, source date `09-01`, `source_date_format=month_day`,
`business_date=2026-09-01`, and the date-provenance object persisted in the
exact JSON evidence file.

| Nowscore ID | Home | Away | Kickoff (+08:00) | Match number | JC evidence |
|---:|---|---|---|---|---|
| 2913701 | Gnistan Helsinki | TPS Turku | 2026-09-01 00:00 | null | `SetLevel(3)`, `A[j][32] == 1` |
| 2913703 | Inter Turku | KuPs | 2026-09-01 00:00 | null | `SetLevel(3)`, `A[j][32] == 1` |
| 2993771 | Lecce | AS Roma | 2026-09-01 00:30 | null | `SetLevel(3)`, `A[j][32] == 1` |
| 2912252 | Djurgardens | Mjallby AIF | 2026-09-01 01:00 | null | `SetLevel(3)`, `A[j][32] == 1` |
| 2912258 | IK Sirius FK | Malmo FF | 2026-09-01 01:00 | null | `SetLevel(3)`, `A[j][32] == 1` |
| 3013667 | Osasuna | Getafe | 2026-09-01 01:30 | null | `SetLevel(3)`, `A[j][32] == 1` |
| 2993766 | Atalanta | Bologna | 2026-09-01 02:45 | null | `SetLevel(3)`, `A[j][32] == 1` |
| 2997701 | Dijon | Saint Etienne | 2026-09-01 02:45 | null | `SetLevel(3)`, `A[j][32] == 1` |
| 3003860 | Aston Villa | Arsenal | 2026-09-01 03:00 | null | `SetLevel(3)`, `A[j][32] == 1` |
| 3023461 | Benfica | Estoril | 2026-09-01 03:15 | null | `SetLevel(3)`, `A[j][32] == 1` |
| 3023462 | Sporting Braga | Vitoria Guimaraes | 2026-09-01 03:15 | null | `SetLevel(3)`, `A[j][32] == 1` |
| 3013665 | FC Barcelona | Rayo Vallecano | 2026-09-01 03:30 | null | `SetLevel(3)`, `A[j][32] == 1` |

All 12 accepted records persist:

- `jc_membership=VERIFIED`;
- `jc_membership_source=nowscore_public_jc`;
- the source page URL, backing-data URL, `fetched_at`, Nowscore ID, team IDs,
  home/away names, kickoff, and date provenance;
- the exact evidence object with `row_index=32`, `raw_value=1`, and the
  backing-array index.

## Existing schedule comparison and source convergence

The same runner parsed the existing `bf1` surface for the target date: status
`OK`, `102` target-date rows, duplicate count `0`, and
`intersection_ids=[]` against the 12 explicit JC IDs. This is a surface
difference, not a JC-membership inference: the current JC universe is sourced
from the explicit public JC filter, while the existing `bf1` path remains
available for its established evidence consumers. Existing Nowscore schedule
behavior remains covered by the focused regression suite.

The production schedule intake now follows:

`Nowscore public JC → canonical schedule / identity → existing Nowscore market and analysis evidence → BASE`

Sporttery and 500 are no longer current-universe schedule dependencies. Their
optional official-market/corroboration and independent 500 deep evidence paths
remain available. Their failure cannot replace a verified Nowscore JC payload
with an empty current universe.

No Champion, model, identity threshold, frozen prediction, prospective ledger,
or 90-minute settlement rule was changed. No production or frozen history was
rewritten.

## Open-source check and validation

The bounded open-source landscape check is recorded in
`docs/data-foundation/OPEN_SOURCE_DISCOVERY.md`. No third-party Nowscore
scraper or new provider dependency was adopted; the implementation uses the
public page/data contract directly.

Focused validation for this milestone:

- `90 passed, 6 warnings` across the Nowscore parser, JC universe, probe,
  schedule workspace, prediction universe, BASE jobs, fetch, and match
  workspace tests;
- `48 passed` across the existing BASE runner, Nowscore identity fallback,
  and provider-identity/core-selector regression tests;
- after the runner-only probe bug fix, `8 passed` in the direct JC/probe test
  set;
- `py_compile` passed for all changed Python modules;
- `git diff --check` passed;
- local read-only integration produced `12` current (`ft1`) and `5` bounded
  future (`sc1`) verified JC rows, with `17` deterministic bindings and zero
  ambiguous or missing bindings.
