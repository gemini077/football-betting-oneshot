# Phase 2C-2 Opponent / Schedule Strength Research

This is bounded offline exploratory research. It does not register a production Challenger, alter Champion, or write formal benchmark records.

## Locked data boundary

- Research pool: **544** fixtures; development **410**, reused validation **134**.
- Phase 2C-1 spent held-out set: **144** IDs, digest `a1b9ec5d0bf57e73b78eb00abffc95f5650ccf496bc8f8449e42040af097afce`. Result payloads accessed for training/evaluation: **0 / 0**.
- Fresh held-out data is unavailable. The 134-fixture validation result is exploratory evidence only.

## Specifications

- Candidate registry: **3** regularization values, frozen before rolling evaluation.
- Selected specification: `opponent:fixed-point:prior20`.
- Experiment ID: `phase2c2:26413f4a196ecd6dff941871085cfda9abbcbba3a3287d4bcc5423f7b1542601`.

## Validation evidence

- Validation evaluation count: **1**.
- Opponent vs matched raw 1X2 log-loss delta: **0.007891004967715443**; bootstrap CI `[-0.00018813735736937696, 0.016122230268107586]`.
- Opponent vs matched raw goal-NLL delta: **0.010355112729898863**; bootstrap CI `[-0.00120559101619397, 0.02257563145614762]`.
- Exploratory classification: **EXPLORATORY_INCONCLUSIVE**.

## Boundaries

- Only historical results, goals, venue, competition, and target-time prior records were used.
- No Elo, Bradley-Terry, schedule-strength coefficient, market, xG, lineup, injury, or manual judgement was used.
- This is not a fair offline Champion comparison because historical Champion snapshots and market inputs are unavailable.
- Formal prospective benchmark comparisons remain **0**.
