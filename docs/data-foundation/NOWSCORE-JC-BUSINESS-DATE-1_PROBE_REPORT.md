# NOWSCORE-JC-BUSINESS-DATE-1 — Nowscore JC business-date gate

Status: `READY_FOR_ACCEPTANCE / NO_CODE`

Decision gate: `NO_CODE`

STOP state: do not merge and do not start Challenger Promotion Review.

## Scope

This milestone examined only Nowscore public JC surfaces. The already-proven
membership contract is unchanged: the live Nowscore page exposes
`SetLevel(3)`, which selects the exact backing-row predicate
`A[j][32] == 1`. No league, team, kickoff, odds, or other flag was used to
guess JC membership.

## Deterministic business-date contract

The public Nowscore JC sales page is:

- [JC page for 2026-08-31](https://cp.nowscore.com/buy/jingcai.aspx?typeID=101&oddstype=2&date=2026-08-31)
- [JC page for 2026-09-01](https://cp.nowscore.com/buy/jingcai.aspx?typeID=101&oddstype=2&date=2026-09-01)

Its deterministic anchor is:

1. the selected `SelDate` value;
2. the `niDate` header whose displayed date equals that selected date;
3. the explicit sales window `11:00--次日11:00`;
4. the match number formed by the `niDate` group name plus the row number cell.

The parser filters rows to the matching `niDate` group. It does not derive a
business date from kickoff time, weekday, league, team, or a hardcoded fixture
ID. The page is public and credential-free.

## GitHub evidence

- Runner: [33470293458](https://github.com/gemini077/football-betting-oneshot/actions/runs/33470293458)
- PR: [#141](https://github.com/gemini077/football-betting-oneshot/pull/141)
- Runner head: `1f6274fbebb838f0bb074cac71fe04d75ddeb7cd`
- Exact artifact: `docs/data-foundation/NOWSCORE-JC-BUSINESS-DATE-1_PROBE_RUN_33470293458.json`
- Artifact SHA-256: `186361AFCD01D884DD1B50BF901CAC54C1DC967F0D04FA3860D6B281FC6665B9`
- Evidence `fetched_at`: `2026-09-01T12:34:33+08:00`
- Both JC pages returned HTTP `200`.
- The required `ft1` and `sc1` page/data surfaces returned HTTP `200/200` and
  both exposed the unchanged `SetLevel(3)` / `A[j][32] == 1` contract.

## Paired replay

| Business date | Public JC rows | Next-calendar-day kickoff rows | Explicit A32 accepted rows | Missing live schedule rows | Duplicate / ambiguous |
|---|---:|---:|---:|---:|---:|
| `2026-08-31` | 12 | 12 | 12 | 0 | 0 / 0 |
| `2026-09-01` | 10 | 10 | 0 | 10 | 0 / 0 |

The `2026-08-31` accepted IDs are:

`2913703, 2913701, 2993771, 2912252, 2912258, 3013667, 2993766, 2997701, 3003860, 3023461, 3023462, 3013665`.

All twelve have kickoff dates on `2026-09-01`, while the public sales-day
header is `2026-08-31` with the `11:00--次日11:00` window. The public
`2026-09-01` page has ten rows, all with kickoff dates on `2026-09-02`, and
the matching group is correctly isolated from the additional `2026-09-02`
group in the same response.

The 2026-08-31 and 2026-09-01 public-page ID sets have intersection `[]`;
the accepted ID sets also have intersection `[]`. Therefore no fixture was
placed in two business dates. Every accepted fixture carries explicit
`SetLevel(3)` / `A[j][32] == 1` evidence.

## Gate result

The deterministic sales-day contract and runner access passed. The full gate
did not pass: the public `2026-09-01` JC page was nonempty (`10` rows), but
the corresponding live `sc1` schedule/data replay contained none of those ten
Nowscore IDs, so the explicit membership intersection was `0`. The probe
records this as `current_target_rows_available=false` and
`decision_gate=NO_CODE`.

This is an observed source-surface mismatch, not permission to infer
membership from the JC page. No production business-date change is authorized
until a paired replay has a nonzero explicit A32 row count whenever the public
JC page is nonzero.

No fixed early-morning cutoff, weekday rule, kickoff subtraction, league/team
rule, or fixture-ID exception was introduced. No Sporttery/500 source code,
Champion, identity threshold, frozen history, prospective ledger, or result
settlement semantics was changed.

## Validation

- Corrected probe unit tests: `4 passed`.
- GitHub bounded probe: completed successfully; the evidence decision gate is
  `NO_CODE`.
- Exact artifact copied without transformation; the recorded SHA-256 matches.

Next action is a fresh bounded replay after the public Nowscore live schedule
exposes an explicit A32 row for the nonempty `2026-09-01` JC group. STOP at
`READY_FOR_ACCEPTANCE`.
