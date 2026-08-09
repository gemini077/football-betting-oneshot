# Model Governance

Football Betting OneShot is an event-analysis and probability-prediction
platform. Betting reference is a downstream output. `analysis_output` may be
available without a prediction; `prediction_output` may be available without a
betting reference. If there is no verified executable price,
`betting_reference_output.status` is `not_evaluable` and the prediction is not
deleted or converted into a bet.

## Frozen Champion

Phase 0.1 has one registered Champion:

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
   versions, calibration artifact hash, prompt version, source commit, and
   Challenger id where applicable.

`prediction_id` is the hash of those three identities. Re-running the same
match, snapshot, model run, and input is idempotent. A different release,
feature version, code source, or Challenger gets a different id. The same id
with changed output is an immutable-content conflict.

The deterministic model input is stored once under
`data/model_governance/input_snapshots/<sha256>.json`. The prediction record
stores its manifest/reference/hash rather than a second copy. Narrative-only
changes are excluded from the deterministic input projection.

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

Phase 0 and 0.1 establish the trustworthy freeze, identity, provenance,
settlement, and evaluation contracts. Phase 1 may later build the Market
Baseline, Simple Baseline, and same-snapshot shadow framework. Only after that
framework accumulates the required independent matches may a Challenger be
considered for promotion. Phase 0.1 does not start model tuning or add xG,
Elo, lineup, market, or page features.
