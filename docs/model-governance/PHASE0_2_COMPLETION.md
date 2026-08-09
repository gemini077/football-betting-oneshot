# Model Governance Phase 0.2 Completion

## Scope and safety

Phase 0.2 hardened model identity, deterministic input snapshots, timestamp
semantics, and exact post-match joins. It did not start Phase 1, tune the
Champion, add a model, change the frontend, create a prediction, or rewrite
historical reports, results, betting records, or generated site output.

- Repository: `gemini077/football-betting-oneshot`
- Worktree: `D:\MyProject\football-betting-oneshot-model-governance-phase0`
- Branch: `agent/model-governance-phase0`
- Phase 0.2 governance implementation commit:
  `c2e4486083fcbed73b4b52de75017e93ea5ec937`
- Champion model source commit:
  `037c1b72a6310c0132b6dadaf5cd18d1925c133e`
- Observed `origin/main` at export:
  `c2b790326be7603d215fb68fb7ad9fc24095ab21`
- `origin/main` changes merged during this task were limited to automatic
  data/report state files; no model-math conflict occurred.
- Baseline export commit: `null`; the existing untracked `artifacts/`
  directory remains preserved, so `working_tree_clean=false` is computed from
  actual `git status --porcelain` output.

## Champion identity and snapshot contract

- Champion: `recent_form_market_calibrated_poisson_v2`, release `v0.19.0`.
- `rho` remains fixed at `0.0`; it is not an estimated Dixon-Coles parameter.
- Challenger list remains empty and automatic promotion remains forbidden.
- Model source fingerprint:
  `dc0d4aa32f658ed303c71430081c3d70c9b3949681aa50b7834389624ac32592`
- Canonical model input contract: `deterministic_model_input.v1`.
- Snapshot contract: `governance_snapshot.v2`.
- `repository_commit_sha` remains audit provenance only. Model identity uses
  the deterministic source-component fingerprint, model-run metadata, and the
  exact input snapshot identity; automatic data/report commits do not create a
  new model fingerprint.
- The deterministic core now executes the same projection that is persisted
  for replay. The projection excludes bankroll/open bets, HTML/report prose,
  LLM wording, and unused Polymarket data.
- `prediction_created_at` is recorded after deterministic core execution.
  `source_cutoff_at` and `market_snapshot_at` are derived only from real
  source/checkpoint capture timestamps. Generic fetch time cannot satisfy the
  gate; missing proof makes the record research-only.

## Baseline inventory

The regenerated baseline reports:

- Historical report records: `454`
- Convenience-view records excluded: `52`
- True governance frozen predictions: `0`
- Unique prediction IDs in historical reports: `0`
- Formal unique matches: `0`
- Formal settled unique matches: `0`
- A/B formal grades: `A`, `B`
- Formal Brier Score, Log Loss, score metrics, ROI, CLV, and maximum
  drawdown: `null` because there is no exact-settled model-only frozen sample.

Historical reports without a governance `prediction_id` remain inventory only;
they are not relabeled as frozen predictions.

## Verification

- Fixed fixture digest before and after:
  `b104c0f81c2a5c457967d9047b41e389209b99bd3cfc1613d9fb13fb0c2175df`
- Governance tests: `52 passed`.
- Directly related tests: `105 passed` in the final focused run before the
  schema-contract test was added; the full suite below includes the added
  coverage.
- Full suite: `343 passed, 6 existing openpyxl warnings`.
- Python compilation passed.
- JSON parsing passed for config and both schemas.
- `git diff --check` passed after removing the one trailing-whitespace issue.
- Schema-contract tests assert the conditional 1.1/3.1 identity requirements;
  no new schema-validation dependency was installed.
- Snapshot replay passed for lambda, expected goals, 1X2, BTTS, totals, score
  matrix, unique score, and primary deterministic contract. Persisted
  content-addressed snapshots also replay successfully and detect tampering.

## Phase 1 recommendation

Phase 0.2 is complete as a governance hardening step. It is permissible to
begin only the Phase 1 same-match, same-snapshot Market Baseline, Simple
Baseline, and Champion shadow-comparison foundation. Do not tune the Champion,
register or promote a Challenger, or add xG, Elo, lineup, market, simple-
Poisson, or page features. Promotion remains blocked until independent
out-of-sample data and every human-review gate are satisfied.

## Delivery state

PR #62 remains Draft and must not be automatically merged. Final push SHA and
GitHub mergeability are recorded in the handoff package and final delivery
report after the branch is pushed.
