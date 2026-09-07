# EXACT-DISTRIBUTION-FAMILY-SHADOW-BENCHMARK-1

Decision: **`FAIL_CLOSED_TRAINING_AUTHORITY`**
Integrity: **`PASS`**

## Fixed evaluation authority

- Accepted fixed cohort: `107/107` unique matches; manifest digest `a70bba7d935bb3f695dd5d9b71c4095bbc52cd18ab0fa5c96c5cd1aac0d49f85`.
- Evaluation chronology: `2026-08-30T19:30:00+08:00` through `2026-09-06T23:00:00+08:00`.
- Fixed cohort validation: `PASS`; failures: `[]`.
- Memory-Hub authority: [PROJECTS/Football-Betting-OneShot/RESEARCH/2026-09-06-POST-221-DISTRIBUTION-FAMILY-ROUTE-R2.md](https://github.com/gemini077/Memory-Hub/blob/main/PROJECTS/Football-Betting-OneShot/RESEARCH/2026-09-06-POST-221-DISTRIBUTION-FAMILY-ROUTE-R2.md) (blob SHA `589dc62fbeedaf0cff8468495ec9bf8dff967a6b`).
- Accepted #189 Market lambda was not recomputed or changed; no family scoring was attempted before training authority passed.

## Training authority

- Candidate historical pair-version rows strictly earlier than the earliest evaluation kickoff: `1`.
- Legal, verified, disjoint training unique matches: `1`; minimum necessary global-parameter count: `2`.
- Training chronology: `2026-08-16T09:30:00+08:00` to `2026-08-16T09:30:00+08:00`; strictly earlier: `True`; identity overlap: `0`.
- Training status: **`FAIL_CLOSED_TRAINING_AUTHORITY`** — `no_sufficient_disjoint_pre_evaluation_training_authority_for_global_rho_kappa`.
- No rho/kappa was fit on the 107 evaluation outcomes. The family benchmark stops before scoring.

## Family results

All Exact, bootstrap, stability, distribution-shape, and 1X2 safety metrics are `NOT_EVALUATED_TRAINING_AUTHORITY`.

- `POISSON_EXACT_NLL`: `NA`.
- `DC_EXACT_NLL`: `NA`.
- `NB_EXACT_NLL`: `NA`.
- `DC_DELTA_CI`: `NA`.
- `NB_DELTA_CI`: `NA`.
- `BEST_SUPPORTED_FAMILY`: `NA`.
- `1X2_SAFETY`: `NOT_EVALUATED_TRAINING_AUTHORITY`.

## Stop state

- Research-only artifact; no model, parameter, selector, serving, UI, or historical-data change.
- No merge and no automatic promotion.
- STOP: obtain a separate, strictly earlier, legally frozen and sufficiently sized training authority before rerunning.
