## Phase 2B.2 — recover real competition demand coverage

This draft keeps Team Strength shadow-only and restores project competition demand from bounded local metadata. It does not alter the Champion, model math, benchmark definitions, frontend, or `validated_for_model` flags.

### Included

- Recovered 25/25 historical analysis jobs through exact provider-ID or exact home/away metadata links; unresolved evidence remains explicit.
- Separated project analysis usage, current-match demand, and historical source-record volume.
- Added 30-day, 90-day, and all-recoverable usage windows plus P0/P1/P2/P3 ranking.
- Added analysis-weighted strict-ready and ready-plus-verified-bridge coverage.
- Preserved current-match identity evidence when an automated workspace refresh has an empty `matches` list.
- Expanded Football-Data.co.uk source manifests and raw hashes for Brazil, Norway, Finland, Japan, and USA; raw CSVs are not committed and team identity remains `UNVERIFIED` until reviewed.
- Kept OpenFootball and Football-Data.co.uk source completeness separate from project demand. API-Football remains planning-only and `DEFER`.

### Current evidence

- 18 observed project competitions; 220 resolved demand fixtures and 3 unresolved competition rows.
- P0: Portuguese Primeira Liga; P1: Eliteserien, K League 1, Veikkausliiga, Brasileirao, Europa League, Champions League, MLS.
- Current matches: 3; strict current-strength ready: 2; bridge-only: 0; stale: 1.
- P0/P1 analysis-weighted strict ready: `0.0`; ready plus verified bridge: `0.0`.
- `MODEL_DATA_READY_FOR_PHASE2C=false`.

### Verification

- Focused Phase 2B.2 and source tests: 28 passed.
- Model governance: 57 passed.
- Baseline production integration: 13 passed.
- Full suite: 506 passed, 6 warnings.
- `scripts/automatic_model_core.py` SHA256 remains `064f9fa96e2995a66966c916dd9e9f600358b6c49b3ad9aa1efe9704cbdd1f15`.
- Fixed fixture digest remains `b104c0f81c2a5c457967d9047b41e389209b99bd3cfc1613d9fb13fb0c2175df`.
- `validated_for_model=true` count remains `0`.

This PR remains Draft. Coverage is not sufficient for Phase 2C; no Challenger is created here.
