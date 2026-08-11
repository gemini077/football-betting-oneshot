# Phase 2B.5 Final Coverage

Generated at `2026-08-11T07:44:32Z` from the existing P0/P1 demand audit and shared Football Data Home.

This is the final Phase 2B data-layer closure report. It does not create a Challenger, change the Champion, or validate any feature for model use.

Demand denominator: `152`. Strict ready `19`; verified bridge `1`; ready plus bridge `20` (`13.157895%`).

The fixed 80% gate requires `122` demand weight. Passed: `False`. This metric does not make a closure decision.
Shared Data Home verification: historical `1554` records with digest `710b0fdc8046d69aa86411b748d9c1966c45fabd0ac83678f58719b1f3bbfb5e`; snapshots `160` with digest `3fcd494b0cbe20f65f6f8407f471ca2d8e034010789b6ebec85d0e4becd9a8a6`.

## Track A — project identity

The current identity-missing set contains `72` fixtures. Auto-resolved `0`, review required `0`, conflict `0`, still unresolved `72`.

Blocker counts below are side-level evidence counts; one side may have more than one blocker.

| Blocker | Side count |
| --- | ---: |
| `canonical_source_candidate_missing` | 109 |
| `provider_team_id_missing` | 108 |
| `reviewed_alias_missing` | 109 |
| `translated_english_name_missing` | 97 |

No new project-provider mapping is promoted without a unique reviewed ID/alias/context chain. Detailed candidate graphs remain outside Git under `${FOOTBALL_DATA_HOME}/identity/`.

## Source closure

- Report generated at `2026-08-11T07:44:32Z`; frozen source evidence observed at `2026-08-11T07:36:41Z`; live check executed: `False`.
- OpenFootball UEFA prior season: `AVAILABLE`; current 2026/27: `NOT_VERIFIED` (not a season-unavailable claim).
- K League official/public: `SOURCE_MISSING`; demand remains in the denominator.
- football-data.org: `DEFER`; no authenticated capture was executed.
- API-Football: `NOT_EXECUTED_NO_KEY`; requests `0`; real ingestion `False`.

## Phase 2B closure decision

Closed: `True`; closed with backlog: `True`; complete: `True`.
Global model data ready: `False`; eligible subset evaluation required: `True`.
Coverage backlog: `{"by_competition": {"identity_missing": {"brazil-serie-a": 12, "finland-veikkausliiga": 18, "norway-eliteserien": 23, "portugal-primeira-liga": 8, "usa-mls": 11}, "source_missing": {"south-korea-k-league-1": 27, "uefa-champions-league": 16, "uefa-europa-league": 17}}, "identity_missing": 72, "source_missing": 60, "total_not_ready": 132}`.
Closure is an explicit governance decision, not a proof that coverage cannot ever improve.

## Final status

- Historical result store is unchanged and remains immutable.
- No raw source or bulk result rows were added in this closure.
- `validated_for_model=true` count remains `0`.
- Phase 2B is complete; remaining gaps are a frozen coverage backlog for later governance review, not a new Phase 2B phase.
