# PRED-AVAIL-1 — Daily Prediction Availability Closure

Status: `READY_FOR_ACCEPTANCE`

Business date: `2026-08-30`  
Frozen cohort: 25 fixtures  
Cohort SHA-256: `0cf4f106c34f183c3d61a81952f70e9c7f2525c0376a1e6eff74bb087e15cb8d`

## Scope and protected boundary

The exact cohort is frozen from `data/prediction_universe/2026-08-30.json` and
`data/prediction_dashboard/latest.json`. The current Champion,
`recent_form_market_calibrated_poisson_v2`, its mathematics, frozen prediction,
automatic market/prospective/dashboard/runtime artifacts, and historical store
were not rewritten. No league-specific branch, identity alias, new provider,
synthetic evidence, degraded production fallback, or frontend change was added.

## Same-cohort result

| Metric | BEFORE | AFTER |
|---|---:|---:|
| FULL prediction | 1 | 2 |
| DEGRADED prediction | 0 | 0 |
| INSUFFICIENT_DATA | 24 | 23 |
| MISSING_RECENT_FORM | 24 | 23 |
| identity-blocked | 23 | 23 |
| source-blocked | 24 | 23 |
| history-blocked | 23 | 23 |
| prediction_failed | 0 | 0 |
| Champion jobs blocked | 0 | 0 |

AFTER is an isolated bounded replay of the same 25 jobs. The existing frozen
Celta Vigo–Athletic Club artifact was excluded from rerun. One new scratch
freeze, `500-1364199` Bodø/Glimt–Rosenborg, was produced through the generic
authoritative-history route. Production automatic state remains unchanged and
must be independently accepted before any live refresh is considered.

Per-competition counts and the exact fixture rows are retained in:

- `data/football_data/pred_avail_1/baseline_2026-08-30.json`
- `data/football_data/pred_avail_1/root_cause_audit_2026-08-30.json`
- `data/football_data/pred_avail_1/availability_before_after_2026-08-30.json`
- `data/football_data/pred_avail_1/protected_state_verification_2026-08-30.json`

## Root-cause audit

The 24 missing rows share a downstream error label but not one identical
fixture-level blocker:

- 1 row: `HISTORY_EXISTS_BUT_NOT_USED`. Bodø/Glimt and Rosenborg already have
  exact reviewed IDs and fresh eligible records in the authoritative store;
  BASE did not previously route that store into its recent-form contract.
- 23 rows: `IDENTITY_BLOCKED`. Three are partial exact resolutions and 20 have
  no exact reviewed pair. The resolver therefore does not query or invent a
  team history from display names.
- All 24 also record the same contributing system causes:
  `RECENT_FORM_SOURCE_NOT_ROUTED`, `RECENT_FORM_SOURCE_UNAVAILABLE`, and
  `FIXTURE_PROVIDER_MAPPING_MISSING`.

The runtime path attempted the existing 500 deep source and observed connection
refused errors. The current universe has no exact Nowscore match mapping. The
OpenFootball recent-form cache contains a reviewed exact entry for the already
frozen Celta fixture, but not for the other 24. The historical store is
available (`1778` eligible rows; digest
`48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2`) but was
not connected to BASE before this change.

## Generic fix

`scripts/recent_form_cache.py` now exposes
`load_authoritative_recent_form`. It reuses the existing exact coverage
resolver, reads eligible pre-kickoff rows from the read-only historical store,
converts them to the existing four-block recent-form contract, enforces the
current freshness window, and carries dataset/source references. The runner
tries this route only after the existing prematch, Nowscore, 500 deep, and
reviewed-cache paths. The 500 error envelope is no longer projected as a usable
source timestamp when it contains neither valid form nor valid market data.

No Champion formula or weight changed. The market-only baseline remains
metadata-only; there is no unvalidated market-only prediction route, so
`DEGRADED=0` is intentional.

## Source landscape and bounded import decision

The project already has both generic adapters:

- `scripts/football_data/providers/football_data_uk.py`
- `scripts/football_data/providers/openfootball.py`

The [Football-Data source index](https://www.football-data.co.uk/data.php) is a
free results/odds source with broad country coverage and states that files are
updated at least twice weekly; the project manifest still requires its terms
and attribution review. Its [disclaimer](https://www.football-data.co.uk/disclaimer.php)
does not guarantee correctness, so the source remains a corroborating
historical input rather than a sole live dependency. The community
[soccerdata issue tracker](https://github.com/probberechts/soccerdata/issues/927)
also records repeated 503 failures while downloading Football-Data files,
which is consistent with treating source availability as a first-class
runtime state. OpenFootball's [Europe repository](https://github.com/openfootball/europe),
[world repository](https://github.com/openfootball/world), and
[Spain repository](https://github.com/openfootball/espana) provide the existing
plain-text Football.TXT source family. The public
[OpenFootball help issues](https://github.com/openfootball/help/issues) show
that result-update latency and missing league files are operational concerns;
this source is therefore suitable for reviewed historical imports, not an
unqualified current-fixture fallback. These sources remain shortlist inputs,
not a reason to add a provider in this milestone.

Japan J1 2025 (`380/380`) and Spain La Liga remain
`READY_FOR_GENERIC_IMPORT_BOUNDED_ONLY`. No production import was run because
the captured raw input and exact identity evidence still need to be verified;
the current 25-fixture Spain rows also include teams outside the reviewed
target set. This is one generic import decision, not a league-by-league work
queue.

## Conclusion and next pointer

Availability improved from 1/25 to 2/25 without lowering evidence quality, but
23/25 remain unavailable. This is still a product blocker for daily coverage,
so the milestone is `READY_FOR_ACCEPTANCE`, not PASS. The identity backlog is
`NON_BLOCKING / ON_DEMAND`; ID-AUTO-2 is not started. After independent
acceptance of this milestone, the next product line returns to Multi-Market
Prediction Quality; no model tuning is started here.
