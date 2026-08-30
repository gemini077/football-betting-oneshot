# MARKET-SIDE-SHADOW-1 — Bounded Prospective Shadow Validation

Status: `READY_FOR_ACCEPTANCE`

Engineering result: `MARKET-SIDE-SHADOW-1 = READY_FOR_ACCEPTANCE`

This milestone wires the accepted PRED-TRUST-3 Challenger C as a background
research sidecar. It does not promote C, replace the production Champion, or
wait for future matches.

## Locked contract

- Champion remains the user-facing and formal prediction namespace.
- C uses the locked PRED-TRUST-3 formula only:
  `total = 0.60 * form_total + 0.40 * market_total`, with the existing clamp;
  `share = market_share`; `lambda_home = total * share`;
  `lambda_away = total * (1 - share)`; independent Poisson with `rho=0`.
- A pair records the same `match_id`, source cutoff, freeze eligibility, and
  frozen input snapshot digest.
- A successful pair is `PAIRED`. C failure is isolated as
  `CHALLENGER_ABSTAIN`; the Champion record remains preserved.
- The C namespace is `market_side_only_hybrid` under the independent
  `market_side_shadow_1` namespace. User-visible, formal-ledger, and
  automatic-promotion flags are false.

## Paired output and evaluation

Each C output stores both lambdas, `1X2` probabilities, the complete 13x13
exact-score distribution, Top1/Top3, BTTS, O/U 2.5, and total-goal tail
probabilities for `>=4`, `>=5`, and `>=6`.

`evaluate_paired_cohort` consumes only verified 90-minute results supplied
after capture. It reports 1X2 accuracy/Brier/LogLoss/ECE, exact-score Top1,
Top3, NLL and actual-score probability, BTTS/O-U metrics, lambda/distribution
statistics, and right-tail calibration.

BTTS calibration watch stores ECE, Brier, LogLoss, and five fixed reliability
bins for Champion and C. Each bin contains count, mean predicted probability,
and observed frequency; ECE is not used as a single automatic veto.

Checkpoint behavior is deterministic: fewer than 50 verified paired matches is
`NOT_REACHED`, 50 is `CHECKPOINT`, and 100 is
`PROMOTION_REVIEW_READY`. Neither checkpoint enables promotion. The first 30
verified matches also expose integrity and severe proper-metric early-stop
sentinels as `SHADOW_EARLY_STOP_RECOMMENDED` when triggered.

## Engineering smoke

The smoke used the first record from the accepted PRED-TRUST-2 pinned
manifest, without adding data or using a result:

- pair: `MS-SHADOW-PAIR-c2419d933d267e88530442231cace2e5`
- match: `500-1358532`
- source cutoff: `2026-08-15T11:45:12+08:00`
- pair status: `PAIRED`
- verified paired sample: `0`
- checkpoint: `NOT_REACHED`
- C exact-score rows: `169`
- C Top1: `1-1`
- C tail probabilities: `P(total>=4)=0.359488961405`,
  `P(total>=5)=0.189802560068`, `P(total>=6)=0.086972600857`

Evidence is stored at:

- `data/prediction_quality/market_side_shadow_1/smoke_2026-08-30.json`
- `data/prediction_quality/market_side_shadow_1/pairs/MS-SHADOW-PAIR-c2419d933d267e88530442231cace2e5.json`

## Automatic evaluation closure

`scripts/market_side_shadow_refresh.py` reads only the existing
`data/postmatch_automation/results/*.json` artifacts, reuses
`normalize_result` and the existing final/regulation-90m verification rules,
matches results by exact canonical `match_key` plus available identity and
kickoff checks, and atomically writes `latest.json`.

The closure smoke consumed the immutable pair above and its existing verified
`1-1` result artifact. It scanned `382` result files, accepted `382`, matched
one pair, persisted `latest.json`, produced `verified_paired_count=1`, and
left the checkpoint at `NOT_REACHED` with `auto_promote=false`. Actual results
remain evaluation-only and are not persisted into the pair capture.

`scripts/automation_cycle.py` invokes the refresh as the optional
`market_side_shadow_evaluation` step after postmatch and prospective
settlement. A refresh failure is recorded as `DEGRADED` with its error while
the production cycle continues.

## Verification and stop state

- `7` dedicated shadow tests pass.
- Existing runner/shadow regression set: `51 passed`.
- Final relevant acceptance suite, including refresh and automation-cycle
  closure coverage: `173 passed`.
- `py_compile` passes for the new sidecar and runner hook.
- No PRED-TRUST-2/3 replay artifact was rewritten; Champion and formal
  prospective records are unchanged by the smoke.
- No new provider, model, parameter, UI, health monitor/gate, or production
  promotion was added.

The engineering wiring stops here. Future verified pairs may accumulate through
the existing runner hook and can be evaluated by the separate result consumer;
that future sample growth is outside this milestone.
