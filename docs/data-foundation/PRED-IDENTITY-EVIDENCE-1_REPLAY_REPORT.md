# PRED-IDENTITY-EVIDENCE-1 Replay Report

Date: 2026-08-31 (Asia/Shanghai)
Base: `origin/main` = `44815a52ca35903a25cd05f30d4a8256c9d93f32`
Result: `NO CODE / SAFETY GATE FAIL / STOP`

## Scope and method

This is a read-only evidence replay. No resolver, provider, alias, model,
frozen prediction, prospective ledger, production workspace, or durable
production data was changed. The only committed files in this evidence PR are
this report and the two current-state records below; there is no implementation
PR.

The replay uses:

- the 70 `OK` + `EXACT_MATCH` Nowscore fetch artifacts under
  `data/fetch_runs/*/*_nowscore_*.json`, deduplicated to 15 unique provider
  match IDs;
- the current 12-fixture matrix at
  `data/football_data/pred_nowscore_bind_1/root_cause_matrix_2026-08-31.json`;
- the existing deterministic registry at
  `data/football_data/id_auto_1/identity_registry.json`;
- the current `bf1.js` observation fetched into the temporary path
  `C:\Users\Administrator\AppData\Local\Temp\pred-identity-evidence-1\bf1.js`.

The temporary current schedule observation is 105,458 bytes, SHA-256
`711c6d05ad72f133a37f437fe04a1a8ade258f9a3ddfb3ca7e620d72a9abce74`, and
parses to 370 rows. It is not committed and is not a production write.

Candidate B was evaluated as a generic rule only:

1. same home/away orientation;
2. exact Shanghai kickoff equality;
3. one target side resolved by existing reviewed deterministic evidence, with
   the provider-side observation resolving to the same canonical team ID;
4. exact-kickoff candidates are filtered by that confirmed side and selected
   only when the provider match ID set has cardinality one.

No fuzzy threshold, manual team alias, LLM matching, or provider was changed.

## Cohort and coverage

| Measure | Result |
| --- | ---: |
| Historical accepted/verified Nowscore observations | 70 |
| Historical unique Nowscore match IDs | 15 |
| Current fixture rows | 12 |
| Combined unique fixture cohort | 27 |
| Combined raw observation rows | 82 |
| Strict historical coverage | 70/70 observations; 15/15 unique IDs |
| Strict current coverage | 8/12 |
| Strict combined unique coverage | 23/27 |
| Candidate B current coverage after strict fallback | 11/12 |
| Candidate B combined unique coverage | 26/27 |
| Candidate B additions among the four current strict gaps | 3/4 |
| Candidate B additions among the three requested targets | 2/3 |

The fourth current strict gap, `500-1362753` -> `2912252`, also resolves under
the same generic rule. It is not one of the three requested target gates and its
current product job is already frozen.

Historical accepted binding validation found zero page-identity wrong bindings
and zero material duplicate fact conflicts. Two duplicate captures for provider
ID `2912204` retain a one-minute schedule-row metadata drift in the stored
resolution object; both fetched page identities are exact at the target kickoff
and keep the same ID and orientation. This is not counted as a wrong binding.

## Candidate results for the three requested targets

| Project fixture | Expected Nowscore ID | Exact-kickoff pool | Confirmed deterministic side | Identity-filtered IDs | Candidate result |
| --- | ---: | ---: | --- | --- | --- |
| `500-1363834` Inter Turku vs KuPS | `2913703` | 27 | away -> `team:finland:kuopion-ps`; 500 reviewed crosswalk + provider exact canonical `KuPs` | `[2913703]` | `2913703` |
| `500-1363823` Gnistan vs TPS Turku | `2913701` | 27 | home -> `team:finland:gnistan`; 500 reviewed crosswalk + Nowscore stable provider ID `2429` | `[2913701]` | `2913701` |
| `500-1427969` Osasuna vs Getafe | `3013667` | 7 | none | `[]` | `NO_CONFIRMED_SIDE` |

For `500-1427969`, the current raw row does contain Nowscore provider team IDs
`94` (Osasuna) and `98` (Getafe), but neither ID is in the existing Nowscore
identity crosswalk. The registry only has the separate OpenFootball `CA
Osasuna` evidence and no deterministic Nowscore mapping for the two IDs; the
stored provider match crosswalk also has zero rows. Selecting `3013667` from
that row would therefore use the expected answer as a fixture-specific
binding, not Candidate B evidence.

All three target kickoff pools contain multiple raw provider rows. Candidate B
did not select by kickoff alone: it produced filtered cardinalities `1, 1, 0`.

## Safety Gate

| Gate | Result | Evidence |
| --- | ---: | --- |
| Historical wrong binding | 0 | 70 accepted observations / 15 unique IDs; page identity and orientation checks pass |
| Ambiguous collision | 0 | identity-filtered provider ID sets have no cardinality > 1 |
| Orientation conflict | 0 | no opposite-side confirmed identity collision observed |
| Exact-kickoff multiple candidates silently selected | PASS | raw pools are 27, 27, and 7; no kickoff-only selection was made |
| Existing accepted bindings regression | 0 | accepted artifact IDs and page identities remain invariant |
| Existing 8 EXACT_MATCH IDs regression | 0 | strict replay preserves all eight IDs |
| Three target results equal expected IDs | FAIL | only 2/3 resolve; `500-1427969` has no confirmed side |

The eight preserved strict IDs are:

`2993771`, `2912258`, `2993766`, `2997701`, `3003860`, `3023461`, `3023462`,
`3013665`.

Overall Safety Gate: `FAIL`.

## Verification

Focused baseline tests on the isolated `origin/main` worktree:

```text
python -m pytest -q tests/test_nowscore_markets.py tests/test_id_auto_1_identity_registry.py tests/test_id_auto_1_audit_artifact.py tests/test_hc_auto_1_coverage_gate.py tests/test_project_provider_identity_crosswalk.py tests/test_provider_identity_and_core_selector.py
45 passed in 1.03s
```

No implementation test was added because the gate failed before code changes.
The current branch remains on the existing `NEXT-UNIVERSE-TRUTH-1` pointer; no
next milestone is started.
