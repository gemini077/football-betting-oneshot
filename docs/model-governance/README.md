# Model Governance

Football Betting OneShot is an event-analysis and probability-prediction
platform. Betting reference is a downstream output. `analysis_output` may be
available without a prediction; `prediction_output` may be available without a
betting reference. If there is no verified executable price,
`betting_reference_output.status` is `not_evaluable` and the prediction is not
deleted or converted into a bet.

## Frozen Champion

Phase 0 through 0.2.1 has one registered Champion:

- Core and family: `recent_form_market_calibrated_poisson_v2`
- Release: `v0.19.0`
- `rho`: fixed at `0.0`; this is not an estimated Dixon-Coles parameter
- Challengers: none
- Automatic promotion: forbidden

The governance layer does not alter the model's lambda calculation, weights,
rho, score matrix, scenario selector, primary selector, thresholds, EV rules,
or confidence rules.

## Prediction identity and input provenance

Every new frozen record separates three identities:

1. `match_identity`: the fixture identity;
2. `snapshot_identity`: source cutoff, odds snapshot, input hash, and snapshot
   id;
3. `model_run_identity`: role, core/family/release, feature and pipeline
   versions, effective calibration fingerprint, deterministic
   `model_source_fingerprint`, and Challenger id where applicable. A prompt
   enters this identity only when
   that Challenger explicitly declares `prompt_affects_prediction=true`.

`prediction_id` is the hash of those three identities. Re-running the same
match, snapshot, model run, and input is idempotent. A different release,
feature version, deterministic source fingerprint, or Challenger gets a
different id. `repository_commit_sha` remains an audit provenance field and
does not make unrelated data/report commits a new model run. The same id with
changed model output is an immutable-content conflict.

At the actual deterministic call site, the input is projected into
`deterministic_model_input.v1` and the Champion is run using that exact
projection. It is stored once under
`data/model_governance/input_snapshots/<sha256>.json`; the prediction record
stores its content hash/reference rather than a second copy. The projection
contains the form, market rows, checkpoint features, script context, selected
fixture identity, prematch facts, and effective calibration state needed to
replay the current Champion. It excludes raw calibration research metadata,
bankroll, open bets, HTML, report prose,
LLM wording, and unused Polymarket content. Narrative-only changes therefore
do not alter the deterministic input hash.

Calibration provenance and identity are separate. The complete file hash is
stored as `calibration_artifact_sha256` for audit provenance only. The
`effective_calibration_fingerprint` hashes only the active, compatible,
approved fields consumed by the deterministic core; the compatibility alias
`calibration_fingerprint` points to that effective value. When the artifact is
inactive, changes to generated timestamps, samples, validation metrics, or
unapproved candidates do not create a new Champion run. An active approved
parameter change does create a new model run even when the match snapshot is
unchanged.

`prediction_created_at` is the model execution time. `source_cutoff_at` and
`market_snapshot_at` come only from source/checkpoint capture timestamps; a
generic fetch-batch time is never substituted. Missing proof makes the record
research-only. `model_input_as_of_at` and `source_time_range` preserve the
known source timing evidence.

## Data quality and formal samples

Grades A and B are eligible for formal consideration only when no critical
field is missing. C and D remain usable for research and analysis but are
`formal_eligible=false` and `prediction_status=research_only`.

Critical fields include fixture identity, reliable timestamps, source cutoff,
odds snapshot time, probabilities, lambdas, required market inputs, and a
reproducible input reference. Missing lineup information is classified using
an explicit status:

- `unavailable_by_time`: not a missing confirmation at that prediction time;
- `projected`: allowed only under the configured policy;
- `confirmed`: confirmed lineup;
- `missing_unexpectedly`: critical and research-only.

`manual_override=true` produces `prediction_variant=human_assisted`,
`prediction_status=human_assisted`, and `model_formal_eligible=false`. Such
records are retained separately and never count as pure Champion or Challenger
model performance.

## Sample and review definitions

`data/analysis_reports/current/` is a convenience view, not an independent
sample. Historical reports without a `prediction_id` are inventory only; they
are not renamed as frozen predictions. A checkpoint may be a legitimate
snapshot-level observation, but independent holdout size is measured by
`unique_match_count`, not by repeated snapshots of the same match.

Formal model metrics use only this exact join:

```text
frozen prediction
  exact prediction_id
  exact prediction_sha256
  exact model_run_fingerprint
  exact model_source_fingerprint
  exact canonical model input hash
  exact source/odds/commit metadata
      ↕
postmatch review
```

Missing ids, missing frozen records, hash mismatches, fingerprint mismatches,
or snapshot metadata mismatches are research-only. One prediction is counted
once for settlement. Multiple valid checkpoints can settle against the same
result, but match-level metrics count that match once.

The exported baseline keeps both snapshot-level and match-level metrics and
separates:

- historical report inventory;
- true governance frozen predictions;
- formal model-only predictions;
- exact-settled predictions;
- unique matches at each level.

## Correction and promotion policy

The only valid correction sequence is:

1. freeze the current Champion;
2. run a Challenger in shadow mode on the same matches and same snapshots;
3. compare Market Baseline, Simple Baseline, and Champion;
4. validate out of sample using reproducible inputs and at least 50 unique
   matches;
5. allow human review only when every gate passes;
6. promote or reject with an auditable decision, retaining rollback hashes.

No single match may update formal parameters. `automatic_promotion` remains
false even when all statistical gates pass; `requires_human_approval` remains
true. Brier must improve and Log Loss must not deteriorate. Missing metrics,
inconsistent snapshots, non-reproducible inputs, missing baselines, or
snapshot-only sample inflation block review eligibility.

## Phase route

Phase 0 through 0.2.1 establish the trustworthy freeze, identity, provenance,
snapshot replay, settlement, and evaluation contracts. Phase 1 may later build the Market
Baseline, Simple Baseline, and same-snapshot shadow framework. Only after that
framework accumulates the required independent matches may a Challenger be
considered for promotion. Phase 0.2.1 does not start model tuning or add xG,
Elo, lineup, market, simple-Poisson, or page features.
