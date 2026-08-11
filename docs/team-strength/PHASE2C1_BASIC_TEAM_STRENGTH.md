# Phase 2C-1 Basic Team Strength

Generated at: `2026-08-11T11:41:39Z`

This is an offline research experiment. It does not register a production Challenger, alter Champion inputs, or create formal benchmark records.

## Locked cohort

- Cohort: `phase2c-1:standard_recommended:aeca9b371975d229e598507257f0c26961ccbdb24184f38b42c464e6f8198257`
- Match digest: `6e7f22a3db6ba8b1ef32bb7f3601f6c59bfceb579f35c40698ab39261cccdf2a`
- Size: **688**; development **410**, validation **134**, held-out **144**
- Experiment ID: `phase2c1:8bbb53b2c334033e9dcbe6c110cea5b6a05f052185c0dcea85df62313d5586c5`
- Candidate registry digest: `7d6cb986066256d64734921a910ae28d4e1c49c5f77a78da59cd13737ebf3dad`
- Held-out prediction digest: `4c8bd22f04b1b3e51b8abfa084501191a9aeb96e0919389b2c2882b04f0e1e0d`

## Specifications

- Candidates were frozen before validation: **6**
- Selected specification: `basic:last_10:shrink10:venue-fallback`
- Selection: minimum validation 1X2 log loss, then Brier, then goal NLL; candidates were frozen before validation

## Held-out result

- Evaluation count: **1**
- Team Strength 1X2 log loss: **1.0056598740227563**; Baseline A: **1.024359875064467**
- Team Strength goal NLL: **2.9803993377050335**; Baseline A: **2.9658523881160215**
- Research Baseline B is the recommended-competition global historical independent-Poisson reference.
- Research classification: **INCONCLUSIVE**

## Boundaries

- Features use historical goals/results only and strictly exclude target and future kickoffs.
- No xG, lineups, injuries, Elo, opponent strength, schedule strength, odds, or manual judgement is used.
- Partial competition populations remain observed identity-mapped subsets; no entire-league validation claim is made.
- Formal prospective comparisons remain **0**.
- Offline results are not a fair Champion comparison because historical Champion snapshots/market inputs are unavailable.
