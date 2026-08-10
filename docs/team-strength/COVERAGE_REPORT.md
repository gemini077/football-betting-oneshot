# Phase 2B team-strength coverage

Audit timestamp: 2026-08-10. This is a shadow data-layer health report. It is
not a model-quality or prediction-performance report.

## Current scheduled matches

| Category | Count |
| --- | ---: |
| Current core matches inspected | 3 |
| Both teams evaluable | 0 |
| Home side only | 0 |
| Away side only | 0 |
| Neither side evaluable | 3 |
| Raw team mentions without reviewed canonical identity | 6 |

The main failure is identity resolution: current schedule rows have provider
names but no reviewed canonical team IDs. There is also no match-level result
ledger from Nowscore/500, so even a resolved current team would not yet have
eligible history in this checkout.

## Window coverage

The builder supports all requested windows and reports the actual effective
sample instead of claiming the requested size:

| Window | Contract support | Current usable matches |
| --- | --- | ---: |
| `last_5` | supported | 0 of 3 current matches |
| `last_10` | supported | 0 of 3 current matches |
| `last_20` | supported | 0 of 3 current matches |
| `season_to_date` | supported | 0 of 3 current matches |

No xG, lineup, injury, Elo, or market value is required by the core result
builder. None is used as a substitute for a missing result score.

## Health semantics

`data/football_data/team_strength_health.json` records the per-match status,
identity-unresolved count, insufficient-history count, duplicate conflicts, and
source-missing count. The output is explicitly `data_layer_only` and
`validated_for_model=false`.

The data layer preserves unresolved results and possible duplicate/conflict
states. It deduplicates only a canonical match ID or a conservative fully
specified identity tuple; uncertain cross-provider matches remain marked
`possible_duplicate` and are not used for strength.
