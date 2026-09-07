# SOLUTION-FIRST-GOAL-INTENSITY-CHALLENGER-1

- Decision: `SHADOW_CHALLENGER_WIRED`
- Training authority: `EXTERNAL_PRETRAIN_ONLY/HORIZON_TRANSFER`
- Model family: `market_offset_goal_intensity_boosted_poisson_v1`; backend `stdlib_poisson_stump_booster_v1`
- Feature schema: `prematch_venue_overall_goal_rates_v1`
- Train/validation/test: `6295/1349/1349`
- Shadow output rows: `97`

## External test sanity evidence
- Exact NLL `2.850705612008563`; Top1 `0.12601927353595255`; Top3 `0.3402520385470719`; Top5 `0.502594514455152`
- 1-1 actual rate `0.12601927353595255`; 1-1 top-score share `0.5737583395107487`
- Lambda calibration: `{"away": {"bias_observed_minus_predicted": 0.0023767367502579677, "mae": 0.8215230336801956, "observed_mean": 1.2409191994069682, "predicted_mean": 1.23854246265671}, "home": {"bias_observed_minus_predicted": -0.025015665671469973, "mae": 0.9273593997479355, "observed_mean": 1.4885100074128985, "predicted_mean": 1.5135256730843685}, "total": {"bias_observed_minus_predicted": -0.02263892892122239, "mae": 1.2477486066416492, "observed_mean": 2.7294292068198667, "predicted_mean": 2.752068135741089}}`
- 1X2 Brier `0.597556664669873`; O/U2.5 Brier `0.24358661648811797`; BTTS Brier `0.24358105333537658`
- Controls retained — Market NLL `2.8519237155926573`, Champion NLL `2.8742138244030984`, C NLL `2.857217119276646`

## Integrity
- External odds are retained with source timing semantics and labelled HORIZON_TRANSFER; no closing odds are relabeled as FBOS earlier horizons.
- Fixed 107 outcomes are excluded from fitting, validation selection, and test construction.
- Champion serving, C, selector, UI and history are unchanged; the namespace is shadow-only and not user-visible.
- No anti-1-1 rule, manual lambda scale, result-aware score selection, Dixon-Coles/NB/CMP expansion or automatic promotion.
