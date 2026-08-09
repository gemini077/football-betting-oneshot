# Model Governance Phase 0.2 Completion

> Phase 0.2.1 is the final calibration-identity hotfix layered on this
> completion record. It does not change the Champion mathematics or begin
> Phase 1.

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
- Phase 0.2.1 implementation commit:
  `4e5e58ed9afcf50dad30dcfcf5018bd7e104fd91`
- Final baseline provenance commit:
  `5e0ed8ad65e40694ef05a169a3c2a197797d4ba6`
- Champion model source commit:
  `037c1b72a6310c0132b6dadaf5cd18d1925c133e`
- Observed `origin/main` at the final 0.2.1 export:
  `f78de47fc07dde109d294f511148904b2c7004e9`
- `origin/main` changes merged during this task were limited to automatic
  data/report state files; no model-math conflict occurred.
- Baseline export commit: `null`; the existing untracked `artifacts/`
  directory remains preserved, so `working_tree_clean=false` is computed from
  actual `git status --porcelain` output.

## Champion identity and snapshot contract

- Champion: `recent_form_market_calibrated_poisson_v2`, release `v0.19.0`.
- `rho` remains fixed at `0.0`; it is not an estimated Dixon-Coles parameter.
- Challenger list remains empty and automatic promotion remains forbidden.
- Model source fingerprint after the 0.2.1 hotfix:
  `c25d926ab3be05cd42145d7f708229c66b1d011aae0d229a6bea1f5155453eaa`
- Complete calibration artifact audit hash:
  `26b0731f7bc27215ad02366dd7878bc69c9791893d030e9fba0eff215c42fcef`
- Effective calibration fingerprint:
  `8e9c822c620f892f57969314f6e5f783643330c3254afa7a0185fa0f776547d5`
- The raw calibration artifact is currently inactive (`active=false`,
  `shadow_only`). Its research metadata and unapproved candidates are not
  part of the effective Champion identity. Only active, compatible,
  approved fields consumed by the deterministic core enter that fingerprint.
- Canonical model input contract: `deterministic_model_input.v1`.
- Snapshot contract: `governance_snapshot.v2`.
- `repository_commit_sha` remains audit provenance only. Model identity uses
  the deterministic source-component fingerprint, model-run metadata, and the
  exact input snapshot identity; automatic data/report commits do not create a
  new model fingerprint.
- The deterministic core now executes the same projection that is persisted
  for replay. The projection excludes bankroll/open bets, HTML/report prose,
  LLM wording, unused Polymarket data, and inactive calibration research
  metadata.
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
- Governance tests: `57 passed`.
- Directly related tests: `59 passed`.
- Full suite: `349 passed, 6 existing openpyxl warnings`.
- Python compilation passed.
- JSON parsing passed for config and both schemas.
- `git diff --check` passed after removing the one trailing-whitespace issue.
- Schema-contract tests assert the conditional 1.1/3.1 identity requirements;
  no new schema-validation dependency was installed.
- Snapshot replay passed for lambda, expected goals, 1X2, BTTS, totals, score
  matrix, unique score, and primary deterministic contract. Persisted
  content-addressed snapshots also replay successfully and detect tampering.
- Calibration identity tests passed for inactive research updates, inactive to
  active transitions, active approved parameter changes, and active
  validation-only changes. The raw artifact hash changed only as audit data;
  inactive and validation-only changes did not change the effective identity.

## Phase 1 recommendation

Phase 0.2 is complete as a governance hardening step. It is permissible to
begin only the Phase 1 same-match, same-snapshot Market Baseline, Simple
Baseline, and Champion shadow-comparison foundation. Do not tune the Champion,
register or promote a Challenger, or add xG, Elo, lineup, market, simple-
Poisson, or page features. Promotion remains blocked until independent
out-of-sample data and every human-review gate are satisfied.

## Delivery state

- PR #62: `OPEN`, Draft, title
  `chore(model): freeze auditable champion baseline`.
- PR base SHA: `f78de47fc07dde109d294f511148904b2c7004e9`.
- Mergeability: `MERGEABLE`; merge state: `CLEAN`.
- URL: https://github.com/gemini077/football-betting-oneshot/pull/62

The branch is pushed but PR #62 remains Draft and was not automatically
merged.
