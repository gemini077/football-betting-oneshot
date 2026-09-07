# SOLUTION-FIRST-GOAL-INTENSITY-CHALLENGER-1

- Decision: `SHADOW_CHALLENGER_WIRED`
- Training authority: `EXTERNAL_PRETRAIN_ONLY/HORIZON_TRANSFER`
- Model family: `market_offset_goal_intensity_boosted_poisson_v1`; backend `xgboost_count_poisson_base_margin_v1`
- Feature schema: `prematch_recent_form_all_events_v2`
- Train/validation/test: `6310/1352/1353`
- Shadow output rows: `97`
- Market contract parity: `{"checked_live_rows": 97, "contract": "accepted_same_time_market_lambda_v1", "passed_live_rows": 97, "source": "Issue #189 / PR #190", "status": "PASS"}`

## External test sanity evidence
- Exact NLL `2.8524731374312684`; Top1 `0.12416851441241686`; Top3 `0.3340724316334072`; Top5 `0.5025868440502587`
- 1-1 actual rate `0.12564671101256467`; 1-1 top-score share `0.5838876570583887`
- Lambda calibration: `{"away": {"bias_observed_minus_predicted": -0.0010604920293761997, "mae": 0.822183922472847, "observed_mean": 1.2424242424242424, "predicted_mean": 1.2434847344536186}, "home": {"bias_observed_minus_predicted": -0.03331658735332594, "mae": 0.9294227323352535, "observed_mean": 1.4900221729490022, "predicted_mean": 1.5233387603023283}, "total": {"bias_observed_minus_predicted": -0.03437707938271323, "mae": 1.2496623250835486, "observed_mean": 2.7324464153732446, "predicted_mean": 2.7668234947559576}}`
- 1X2 Brier `0.5978869544065502`; O/U2.5 Brier `0.24373000180306126`; BTTS Brier `0.24358335090541502`
- Controls retained — Market NLL `2.8525426832551757`, Champion NLL `None`, C NLL `None`

## Integrity
- External odds are retained with source timing semantics and labelled HORIZON_TRANSFER; no closing odds are relabeled as FBOS earlier horizons.
- Fixed 107 outcomes are excluded from fitting, validation selection, and test construction.
- Champion serving, C, selector, UI and history are unchanged; the namespace is shadow-only and not user-visible.
- No anti-1-1 rule, manual lambda scale, result-aware score selection, Dixon-Coles/NB/CMP expansion or automatic promotion.
