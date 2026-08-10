# Phase 2B.3 P0/P1 team strength coverage

Generated at `2026-08-11T00:00:00Z` from the recovered project-demand fixtures. This is a retrospective data-layer audit; it does not create predictions or benchmark records.

Demand weight: `152`; strict ready `13`; verified bridge `1`; strict rate `0.08552631578947369`; ready+bridge rate `0.09210526315789473`.

Source rows are not demand rows. Only eligible normalized results strictly before each target kickoff are used.

| Competition | Demand | Strict ready | Verified bridge | Stale | Identity missing | Source missing | Scope partial |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| portugal-primeira-liga | 9 | 0 | 1 | 0 | 8 | 0 | 0 |
| norway-eliteserien | 31 | 7 | 0 | 0 | 24 | 0 | 0 |
| finland-veikkausliiga | 23 | 0 | 0 | 0 | 23 | 0 | 0 |
| brazil-serie-a | 18 | 6 | 0 | 0 | 12 | 0 | 0 |
| usa-mls | 11 | 0 | 0 | 0 | 11 | 0 | 0 |
| uefa-europa-league | 17 | 0 | 0 | 0 | 0 | 17 | 0 |
| uefa-champions-league | 16 | 0 | 0 | 0 | 0 | 16 | 0 |
| south-korea-k-league-1 | 27 | 0 | 0 | 0 | 0 | 27 | 0 |

## Identity population

AUTO_VERIFIED `152`; REVIEW_REQUIRED `24`; UNRESOLVED `9`; CONFLICT `16`.

AUTO_VERIFIED here means a shadow candidate backed by repeated cross-source fixture context. Deterministic candidate IDs may be generated for previously unseen clubs, but the production team registry is not mutated automatically; evidence remains in `p0_p1_identity_candidates.json`.

Eligible normalized records available after this capture's deduplication: `1348`; newly persisted immutable records: `0`. Cross-source duplicate collapse: `481`; conflicts: `2`.

## Scope rule

Domestic league demand uses league history as its explicitly observed scope. UEFA demand requires league, domestic-cup and continental history for COMPLETE all-competition recent form; UEFA-only history is therefore PARTIAL.

## K League

`K_LEAGUE_SOURCE_GAP=True`. No compliant free historical result source was adopted in this phase; the 27-match demand weight remains in the denominator.

## Source boundaries

OpenFootball is used as pinned offline Football.TXT historical research data; Football-Data.co.uk is used as captured historical result CSV only. Neither source supplies xG, lineup, injury, or authoritative global identity data here.

No new feature is validated for the Champion.
