# Phase 2B.3 plan

## Scope

Populate P0/P1 shadow Team Strength coverage from captured Football-Data.co.uk and OpenFootball result evidence. Keep all feature registry entries `validated_for_model=false`; do not modify the Champion, benchmark definitions, or frontend.

## Bounded inputs

- `scripts/football_data/` adapters, resolver, ledger, builder, health, and coverage modules.
- P0/P1 demand metadata and source manifests under `data/football_data/`.
- Current schedule metadata needed only for the Portugal season-opening bridge.
- Official source references and hashes; raw third-party files remain outside Git.

## Deliverables

1. Strict P0/P1 team identity candidate builder with AUTO_VERIFIED, REVIEW_REQUIRED, UNRESOLVED, and CONFLICT outputs.
2. Normalized source records and cross-source dedup/conflict handling.
3. Retrospective, pre-kickoff-only availability audit with history-scope and bridge separation.
4. Weighted readiness health and reports for the 152 P0/P1 demand fixtures.
5. UEFA OpenFootball source decision, World Cup source registration, and K League source-gap record.
6. Offline tests, full regression evidence, and a bounded handoff ZIP.

## Gate

Report strict-ready and verified-bridge weights separately. Do not create a Challenger or enter Phase 2C in this branch, even if the 80% data gate is reached.
