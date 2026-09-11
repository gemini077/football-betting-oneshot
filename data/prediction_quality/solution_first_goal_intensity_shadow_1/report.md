# SOLUTION-FIRST-GOAL-INTENSITY-CHALLENGER-1

- Decision: `FAIL_CLOSED`
- Training authority: `EXTERNAL_PRETRAIN_ONLY/HORIZON_TRANSFER`
- Model family: `market_offset_goal_intensity_boosted_poisson_v1`; backend `xgboost_count_poisson_base_margin_v1`
- Feature schema: `prematch_recent_form_competition_scoped_v3`
- Train/validation/test: `6295/1349/1349`
- Shadow output rows: `0`
- Market contract parity: `{"checked_live_rows": 0, "contract": "accepted_same_time_market_lambda_v1", "passed_live_rows": 0, "prior_accepted_evidence": "5ba8f8be000911b91b6bfdf7983d16c485dcb7ed", "source": "Issue #189 / PR #190", "status": "NOT_RUN_SCOPE_BLOCKED"}`

## External test sanity evidence
- Exact NLL `2.8516401758996452`; Top1 `0.12750185322461083`; Top3 `0.335063009636768`; Top5 `0.5040770941438102`
- 1-1 actual rate `0.12601927353595255`; 1-1 top-score share `0.5796886582653817`
- Lambda calibration: `{"away": {"bias_observed_minus_predicted": 0.0025546437859644165, "mae": 0.8214907968945574, "observed_mean": 1.2409191994069682, "predicted_mean": 1.2383645556210037}, "home": {"bias_observed_minus_predicted": -0.03929786738683543, "mae": 0.9302900420726709, "observed_mean": 1.4885100074128985, "predicted_mean": 1.527807874799734}, "total": {"bias_observed_minus_predicted": -0.03674322360086064, "mae": 1.249670622236564, "observed_mean": 2.7294292068198667, "predicted_mean": 2.766172430420727}}`
- 1X2 Brier `0.5977505100257016`; O/U2.5 Brier `0.24370454170888797`; BTTS Brier `0.2436328914770177`
- Controls retained — Market NLL `2.8519237156164365`, Champion NLL `None`, C NLL `None`

## Integrity
- External odds are retained with source timing semantics and labelled HORIZON_TRANSFER; no closing odds are relabeled as FBOS earlier horizons.
- Fixed 107 outcomes are excluded from fitting, validation selection, and test construction.
- Champion serving, C, selector, UI and history are unchanged; the namespace is shadow-only and not user-visible.
- No anti-1-1 rule, manual lambda scale, result-aware score selection, Dixon-Coles/NB/CMP expansion or automatic promotion.
