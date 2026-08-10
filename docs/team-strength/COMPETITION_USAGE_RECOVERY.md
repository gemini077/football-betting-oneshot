# Competition usage recovery

This artifact recovers project demand from lightweight metadata indexes. It does not read report bodies or count historical source rows as user demand.

Analysis jobs: `25`; recovered `25`; still unresolved `0`.
Deduplicated indexed demand fixtures: `223`; resolved competition fixtures `220`; unresolved competition fixtures `3`.
Historical usage before registry start: `recovered_partial`.

## Demand windows

| Window | Resolved competitions | Project fixtures |
| --- | ---: | ---: |
| last_30d | 18 | 220 |
| last_90d | 18 | 220 |
| all_indexed_recent_production_period | 18 | 220 |

## Priority

| Competition | Project demand | Priority | Source records |
| --- | ---: | --- | ---: |
| Portuguese Primeira Liga | 9 | P0 | 306 |
| Eliteserien | 31 | P1 | 362 |
| K League 1 | 27 | P1 | 0 |
| Veikkausliiga | 23 | P1 | 285 |
| Brasileirao | 18 | P1 | 585 |
| Europa League | 17 | P1 | 0 |
| Champions League | 16 | P1 | 0 |
| MLS | 11 | P1 | 808 |
| Sweden Allsvenskan | 29 | P2 | 412 |
| Eredivisie | 9 | P2 | 0 |
| Copa do Brasil | 7 | P2 | 0 |
| J1 League | 5 | P2 | 380 |
| EFL Cup | 4 | P2 | 0 |
| World Cup | 4 | P2 | 0 |
| Ligue 2 | 3 | P2 | 0 |
| 2. Bundesliga | 3 | P2 | 0 |
| J2 League | 2 | P2 | 0 |
| Eerste Divisie | 2 | P2 | 0 |

## Unresolved evidence

- `佐加顿斯 vs 哈尔姆斯塔德`; raw competition `None`; reason `no exact reviewed competition alias`; sources `postmatch_schedule_index`.
- `杰尔 vs 雷克雅未克维京人`; raw competition `None`; reason `no exact reviewed competition alias`; sources `postmatch_schedule_index`.
- `新圣徒 vs 萨巴赫`; raw competition `None`; reason `no exact reviewed competition alias`; sources `postmatch_schedule_index`.

Unresolved demand is not assigned to P0/P1 by name guessing. It remains available for a later reviewed metadata repair.
