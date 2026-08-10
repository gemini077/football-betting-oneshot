# Phase 2B Final Coverage — verified team-strength data layer

## Scope

This Draft PR expands the shadow-only historical result layer. It does not change the Champion, any benchmark definition, market reference, Simple Poisson, prediction identity, or frontend. All new football features remain `validated_for_model=false`.

## What changed

- Added explicit history recency: latest historical match time is separate from source capture time. `current`, `stale`, and verified `offseason_bridge` are distinct states.
- Split `history_available` from `current_strength_ready`; stale or unverified bridge history is not ready.
- Separated project analysis usage from source record volume. P0/P1 ranking uses project/current-match evidence only.
- Added `FootballDataCoUkHistoricalAdapter` for offline match date, home/away, full-time score, competition, and season normalization. Odds and ratings are ignored.
- Added pinned source manifest, raw SHA256, parser version, explicit reviewed team mappings, source conflict handling, and cross-source deduplication.
- Corrected OpenFootball completeness: Sweden Allsvenskan 2025 is 53/240 PARTIAL and Sweden Superettan 2025 is 45/240 PARTIAL; Portugal 2025/26 is complete.
- Added API-Football adoption plan as `DEFER`; no key, network adapter, or fake response is enabled.

## Current evidence

- 206 eligible normalized historical result records from OpenFootball plus Football-Data.co.uk.
- 3 current matches: 3 have historical coverage; 2 are current-strength ready; 1 is stale with an unverified opening bridge.
- All six pilot teams have at least five real historical matches. `DATA_PIPELINE_VALIDATED=true`.
- P0/P1 current-strength ready coverage is 0/1; `MODEL_DATA_READY_FOR_PHASE2C=false`.

## Verification

- Full suite: 498 passed.
- Governance: 57 passed.
- Baseline production integration: 13 passed.
- `automatic_model_core.py` SHA256 remains `064f9fa96e2995a66966c916dd9e9f600358b6c49b3ad9aa1efe9704cbdd1f15`.
- Champion fixed digest remains `b104c0f81c2a5c457967d9047b41e389209b99bd3cfc1613d9fb13fb0c2175df`.
- Benchmark definitions remain unchanged; no formal benchmark samples were created.

## Decision

Keep this PR Draft. Do not start Phase 2C or create a Challenger until P0/P1 current-strength coverage meets the project gate.
