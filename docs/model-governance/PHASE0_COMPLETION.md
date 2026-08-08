# Phase 0 Completion

## Baseline

- Repository: `gemini077/football-betting-oneshot`
- Work branch: `agent/model-governance-phase0`
- Work directory: `D:\MyProject\football-betting-oneshot-model-governance-phase0`
- Source baseline commit SHA: `d74f4a5c965f56876555c57ddfb6959bc50f3980`
- Initial safety-precheck HEAD was `8ccef1d78206c0207ccef90d52d8d8b552d72757`;
  `origin/main` advanced to `d74f4a5c965f56876555c57ddfb6959bc50f3980` with
  data/report-only commits, so this branch was fast-forwarded before final
  validation. No model or governance source file changed in that interval.
- Baseline math changed: no
- Champion: `recent_form_market_calibrated_poisson_v2`, release `v0.19.0`
- Champion family: `recent_form_market_calibrated_poisson_v2`
- Champion `rho`: `0.0`, fixed rather than estimated
- Formal A/B prediction samples: `265`
- Formal settled Champion samples: `0`

## Changes

Added:

- `config/model_governance.json`
- `scripts/model_governance.py`
- `tests/test_model_governance.py`
- `docs/model-governance/README.md`
- `docs/model-governance/baseline-v1/manifest.json`
- `docs/model-governance/baseline-v1/current-metrics.json`
- `docs/model-governance/baseline-v1/known-limitations.md`
- `docs/model-governance/baseline-v1/file-hashes.json`

Modified:

- `scripts/generate_analysis_report.py`
- `scripts/deepseek_auto_analysis.py`
- `schemas/analysis_report.schema.json`
- `schemas/postmatch_review.schema.json`

Intentionally untouched:

- `scripts/automatic_model_core.py` and all probability, lambda, matrix,
  scenario, threshold, EV, confidence, and selection rules
- historical prediction, post-match, result, paper-ledger, and real-bet data
- frontend source and generated website output
- GitHub workflows and automatic betting capabilities

## Verification

- Pre-change focused baseline on the original source commit: `27 passed in 0.86s`.
- Governance focused tests after the change: `24 passed`.
- Governance and directly related tests after the change: `104 passed`.
- Full suite after the change: `315 passed, 6 warnings`.
- Fixed fixture canonical math digest before and after:
  `b104c0f81c2a5c457967d9047b41e389209b99bd3cfc1613d9fb13fb0c2175df`.
- Fixed fixture fields compared: 1X2 probabilities, home/away lambda,
  score-probability rows, unique score, primary contract, and dimension
  predictions.
- Both JSON schemas parse successfully.
- `git diff --check` passes; only line-ending normalization warnings were
  reported by Git.
- No prediction, result, frontend, or real-bet history file was rewritten.

## Remaining Issues

Formal Champion evaluation is not yet possible because no A/B settled review
matches the current Champion. Historical records also lack complete immutable
input metadata; the inventory counts 468 report records, while new immutable
governance records are written only for future runs. These are evidence gaps,
not reasons to change the model.

## Phase 1 Recommendation

Do not enter Phase 1 yet. First obtain at least 50 reproducible out-of-sample
same-match, same-snapshot comparisons with market and simple baselines, then
review the formal A/B settlement set. Do not add xG, Elo, lineup models, new
market baselines, or new pages in this Phase 0 branch.
