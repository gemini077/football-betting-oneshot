# Model Governance Phase 0.1 Completion

## Scope

Phase 0.1 corrected audit findings in the governance and recording layer only.
The Champion math source remained read-only. No xG, Elo, lineup, market model,
page, historical prediction, result, or betting record was regenerated.

## Provenance

- Repository: `gemini077/football-betting-oneshot`
- Work branch: `agent/model-governance-phase0`
- Worktree: `D:\MyProject\football-betting-oneshot-model-governance-phase0`
- Phase 0.1 implementation commit:
  `2021c0fda35cf1f96c475ea5b4d098a9ff01f5ae`
- Observed `origin/main`:
  `4c01a78b78a80c7e767b5960ed57b0446a923656`
- Baseline export commit: `null`; export was performed with a dirty working
  tree because the existing untracked `artifacts/` handoff directory is kept
  intact and the export is itself a working-tree operation
- Champion: `recent_form_market_calibrated_poisson_v2`, release `v0.19.0`
- Champion `rho`: fixed `0.0`, not estimated Dixon-Coles

## Corrections delivered

- Historical report inventory is separate from the true immutable governance
  ledger; `current/` is excluded from independent counts.
- Snapshot-level and unique-match-level counts are exported separately.
- Post-match formal evaluation requires exact `prediction_id`,
  `prediction_sha256`, `model_run_fingerprint`, source cutoff, odds snapshot,
  and repository commit metadata.
- Critical and noncritical missing fields are separated, including explicit
  lineup timing states.
- Manual overrides are stored as `human_assisted` and excluded from model-only
  metrics and promotion.
- Prediction identity is split into match, snapshot, and model-run identities.
- Deterministic model inputs are saved in content-addressed input snapshots;
  narrative-only changes do not alter that input hash.
- Promotion returns human-review eligibility separately from the permanently
  disabled automatic-promotion flag and requires unique-match gates.
- Baseline provenance separates model source, governance implementation,
  export, and observed `origin/main` commits.

## Verification

- Fixed fixture digest before and after: `b104c0f81c2a5c457967d9047b41e389209b99bd3cfc1613d9fb13fb0c2175df`
- Governance tests: `43 passed`.
- Directly related tests: `122 passed`.
- Full suite: `330 passed, 6 existing openpyxl warnings`.
- JSON schema parsing and Python compilation passed.
- `git diff --check` passed; Git only reports the repository's LF/CRLF
  normalization warnings.
- No historical prediction, result, frontend, real-bet, or generated website
  file was rewritten.

## Remaining limitations

The corrected baseline may report zero true frozen predictions and zero formal
settled unique matches because the prior historical reports do not contain an
auditable governance ledger. This is an evidence gap, not a model result.
Market and simple baselines are still required for future shadow evaluation;
Phase 0.1 does not implement them.

## Phase 1 entry recommendation

Allow only Phase 1 foundation work for same-match, same-snapshot Market
Baseline, Simple Baseline, and Champion shadow comparison. Do not tune the
Champion, register or promote a Challenger, or add new model/page features.
Promotion remains forbidden until the foundation accumulates at least 50
independent reproducible out-of-sample matches and all gates pass with human
approval.
