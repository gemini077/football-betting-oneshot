# FE-DC-1 — Sweden League Dixon-Coles Baseline

状态：`READY_FOR_ACCEPTANCE`

## Scope

本结果是 research/shadow-only。它不修改 Champion、production、frozen prediction 或历史 DuckDB；不接入新 provider、xG、lineup、Elo，也不做 recent-form / half-life / rho / learning-rate sweep。

拟合对象是 Sweden Allsvenskan 的完整 canonical historical network。每个 target 只使用 target kickoff 之前的全部 eligible league matches；attack / defense 采用联赛级 sum-to-zero log-rate 参数化，home advantage 为独立参数，Dixon-Coles 只修正 `(0,0)/(1,0)/(0,1)/(1,1)` 四个低比分 cell。

## Pre-registered configuration

- competition: `competition:sweden-allsvenskan`
- warmup: `32` matches；fixed exponential half-life: `365.0` days
- score grid: `0..12 × 0..12`；输出前记录 grid mass、tail mass 和 normalization
- rho policy: primary fitted in `[-0.1, 0.1]`；internal control fixed at `rho=0`
- optimizer: deterministic projected Newton with analytic gradient/Hessian；max iterations `500`；tolerance `1e-06`
- no parameter sweep；control 与 primary 使用同一 chronological target set、同一历史切片和同一时间权重

## Data and network

- source DB: `C:\Users\Administrator\.football-betting-oneshot\football_data\historical_results.duckdb`（read-only）
- full DB rows: `1554`；full DB digest: `710b0fdc8046d69aa86411b748d9c1966c45fabd0ac83678f58719b1f3bbfb5e`
- FE-DC-1 input: `135` unique eligible league matches；teams: `18`；components: `1`
- input kickoff range: `2025-03-29T15:00:00Z` → `2026-08-03T18:00:00Z`
- held-out predictions: `103`；warmup skipped: `32`
- providers: `{"football-data.co.uk":119,"openfootball":16}`；seasons: `{"season:sweden-allsvenskan:2025":16,"season:sweden-allsvenskan:2026":119}`
- input match-id digest: `b2c3731a5b63670a4ea548ae4c7585ae6a272166e50d88cd909dafe5405a5e09`

Durable identity/crosswalk evidence retained from the independently accepted FE-ID-BRIDGE-1 scope:

- `data/football_data/current_match_identity_evidence.json`
- `data/football_data/verified_project_provider_crosswalk.json`
- `data/football_data/fe_id_bridge1_evidence.json`

## Chronological integrity

- predictions have unique target IDs: `True`
- every recorded history row is strictly before its target: `True`
- every full score matrix sums to one after recorded normalization: `True` (max error `6.66e-16`)
- all primary/control fits converged: `True`
- same target set for primary/control: `True`

## Held-out metrics

n = `103` for both models. Brier is multiclass sum-of-squares; Goal MAE is mean absolute error between each predicted λ and its realized home/away goals.

| 指标 | Dixon-Coles | rho=0 control |
|---|---:|---:|
| 1X2 Brier | 0.662536 | 0.661719 |
| 1X2 LogLoss | 1.156665 | 1.150062 |
| Goal MAE | 1.122284 | 1.119640 |
| Total-goal MAE | 1.672452 | 1.671589 |
| Exact Top1 | 0.145631 | 0.116505 |
| Exact Top3 | 0.291262 | 0.281553 |
| Exact Top5 | 0.427184 | 0.475728 |
| Score NLL | 3.545294 | 3.542491 |
| 1:1 Top1 share | 0.427184 | 0.271845 |
| Actual 1:1 share | 0.165049 | 0.165049 |

### Dixon-Coles minus rho=0 control

| 指标 | Δ（primary - control） |
|---|---:|
| 1X2 Brier | 0.000817 |
| 1X2 LogLoss | 0.006603 |
| Goal MAE | 0.002645 |
| Total-goal MAE | 0.000863 |
| Score NLL | 0.002803 |
| Exact Top1 | 0.029126 |
| Exact Top3 | 0.009709 |
| Exact Top5 | -0.048544 |
| 1:1 Top1 share | 0.155340 |

## λ / rho / score-tail diagnostics

| 分布 | n | mean | p05 | median | p95 | max |
|---|---:|---:|---:|---:|---:|---:|
| λ_home | 103 | 1.593209 | 0.485216 | 1.399396 | 3.165937 | 6.879274 |
| λ_away | 103 | 1.424861 | 0.487729 | 1.217445 | 3.023142 | 7.372208 |
| λ_total | 103 | 3.018070 | 1.352865 | 2.916098 | 4.662893 | 10.108061 |
| rho | 103 | -0.081909 | -0.100000 | -0.100000 | -0.040662 | -0.028420 |
| score grid tail mass | 103 | 0.000629 | 0.000000 | 0.000000 | 0.000122 | 0.038175 |

- predicted `P(total goals ≥ 5)`: `0.204361`；actual frequency: `0.213592`
- predicted total-goal distribution: `{"0":0.08692143868649088,"1":0.15495792032017877,"10":0.004345783951140579,"11":0.002615417129921557,"12":0.0016562509309536286,"13":0.0009560869649646509,"14":0.0005632296812820667,"15":0.0003163386658662024,"16":0.00015968545703115374,"17":7.120212991156821e-05,"18":2.8063234461992317e-05,"19":9.839000521894433e-06,"2":0.21803699618985103,"20":3.090517077457605e-06,"21":8.738870583510513e-07,"22":2.2170832832047668e-07,"23":4.897199322482775e-08,"24":8.137565152154135e-09,"3":0.19261787029085783,"4":0.1431052064707874,"5":0.09128207582191578,"6":0.05220706721193806,"7":0.02788810829854711,"8":0.014531092196053,"9":0.007726084145302316}`
- history visible per prediction — all league: `{"count":103,"max":133.0,"mean":82.35922330097087,"median":83.0,"min":32.0,"p05":34.400000000000006,"p25":57.0,"p75":107.0,"p95":128.89999999999998}`；home team: `{"count":103,"max":20.0,"mean":9.766990291262136,"median":10.0,"min":2.0,"p05":3.0,"p25":6.5,"p75":13.0,"p95":16.0}`；away team: `{"count":103,"max":21.0,"mean":9.718446601941748,"median":10.0,"min":2.0,"p05":3.0,"p25":6.0,"p75":13.0,"p95":16.89999999999999}`
- rho distribution: `{"count":103,"max":-0.02841955352176195,"mean":-0.08190855687927402,"median":-0.1,"min":-0.1,"p05":-0.1,"p25":-0.1,"p75":-0.06346308665704609,"p95":-0.040662059276587705}`

## Calibration / extreme probabilities

### Maximum 1X2 probability bins

| bin | n | mean probability | empirical rate | gap |
|---|---:|---:|---:|---:|
| <0.50 | 41 | 0.433610 | 0.487805 | 0.054195 |
| 0.50-<0.55 | 12 | 0.514193 | 0.333333 | -0.180860 |
| 0.55-<0.60 | 13 | 0.573900 | 0.461538 | -0.112361 |
| 0.60-<0.65 | 7 | 0.632375 | 0.428571 | -0.203804 |
| >=0.65 | 30 | 0.778627 | 0.566667 | -0.211960 |

- observed-outcome probability summary: `{"count":103,"max":0.9244912027417664,"mean":0.39859585575369255,"median":0.34049627863188553,"min":0.0020360421098215074,"p05":0.0928061611756359,"p25":0.23128724045615495,"p75":0.5421114424017541,"p95":0.8107532697999222}`
- observed-outcome probability `<0.05`: `{"n":3,"share":0.02912621359223301}`
- strong-favourite diagnostics: `{"p_ge_0.55":{"mean_probability":0.7049223889466445,"n":50,"top1_outcome_hit_rate":0.52},"p_ge_0.60":{"mean_probability":0.7509573378349086,"n":37,"top1_outcome_hit_rate":0.5405405405405406},"p_ge_0.65":{"mean_probability":0.7786265638452702,"n":30,"top1_outcome_hit_rate":0.5666666666666667}}`

## Conclusion

本轮首先验证了结构问题：完整 Sweden Allsvenskan network 可在 `103` 个 chronological targets 上拟合并输出可复核的 full score distribution；它不再是 FE-DA-1 那种只对少量近期配对样本做局部更新的模型。当前 primary 的 `1:1 Top1 share` 为 `0.427184`，不是 100% 的 headline collapse，但仍明显高于 rho=0 control 的 `0.271845`，且 rho 的中位数触及预注册下界，说明低比分修正存在边界压力。

在同一 held-out target set 上，Dixon-Coles 相对 rho=0 control 的 1X2 Brier、LogLoss、Goal MAE 和 Score NLL 分别为 `+0.000817`、`+0.006603`、`+0.002645`、`+0.002803`；这些方向没有证明 correction 本身有价值。Exact Top1/Top3 有小幅上升，但 Top5 下降，不能单独解释为模型质量提升。

因此答案是：FE-DC-1 在数据结构和可审计性上比 FE-DA-1 更像健康的足球比分模型，具备继续研究价值；但这次样本不支持 promotion，也不支持继续围绕 rho、half-life 或其他参数连续调优。下一步应由独立验收决定是否保留 research/shadow 结果，Champion 保持不变。

## Source landscape

- `docs/team-strength/FE_DC_1_DIXON_COLES_LANDSCAPE.md`
- `https://doi.org/10.1111/j.1467-9574.1982.tb00782.x`
- `https://doi.org/10.1111/1467-9876.00065`
- `https://github.com/martineastwood/penaltyblog`
- `https://github.com/jpmouracodex/football-mle`

## Artifacts

- summary: `data\football_data\fe_dc1_results_summary.json`
- predictions JSON: `data\football_data\fe_dc1_predictions.json`
- predictions CSV: `data\football_data\fe_dc1_predictions.csv`
- status: `READY_FOR_ACCEPTANCE`
