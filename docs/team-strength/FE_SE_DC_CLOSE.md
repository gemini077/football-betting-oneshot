# FE-SE-DC-CLOSE — Sweden History Closure + Fixed-Config Re-evaluation

状态：`READY_FOR_ACCEPTANCE`

## Scope and boundaries

本轮是 Sweden / Dixon-Coles 专题的最后执行里程碑。FE-SE-HIST-1 已独立验收 PASS，并在本分支治理记录中标记 SEALED；PR #114 保持 OPEN、未合并。这里只复用 FE-DC-1 的 model implementation、runner/evaluation contract 和 focused tests，不把 PR #114 的旧数据状态覆盖到 main。

唯一预注册变化是历史输入从 FE-DC-1 的 incomplete 1554-row store / 135 Sweden matches 变为 FE-SE-HIST-1 closure 后的 1778-row store / 359 Sweden matches；没有 rho、half-life、attack/defense、optimizer 或 score-grid sweep。

## Fixed configuration

- competition: `competition:sweden-allsvenskan`
- half-life: `365.0` days；warmup: `32`
- max goals: `12`；rho bounds: `[-0.1, 0.1]`；rho=0 control fixed
- optimizer max_iter: `500`；tolerance: `1e-06`
- parameter bounds、home advantage bounds、time weighting：与 FE-DC-1 完全相同
- no sweep / no tuning / no production mutation

## Input and target integrity

- old input: `1554` rows；Sweden `135` matches；digest `710b0fdc8046d69aa86411b748d9c1966c45fabd0ac83678f58719b1f3bbfb5e`
- new input: `1778` rows；Sweden `359` matches；digest `48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2`
- fixed old target IDs: `103`；new resolved IDs: `103`
- exact canonical ID matches: `103`；deterministic reconciliations: `0`
- new target rows with both models: `96` / `103`
- model-specific available rows: `{"dixon_coles": 102, "rho0_control": 97}`
- fixed-config fit failures: `7`; IDs are retained in the audit rather than dropped
- chronology: `True`; score matrix normalization: `True` (max error `1.11e-15`)

## Primary apples-to-apples comparison

同一 103 target IDs 已锁定；但 fixed FE-DC-1 optimizer 在 complete-history replay 中有 model-specific non-convergence，因此不能把 partial rows 冒充完整 103-row improvement。

- DC old vs new common rows: `102`
- rho=0 old vs new common rows: `97`
- DC new vs rho=0 new common rows: `96`

### Metrics (new minus old; only the stated common rows)

| 比较 | n | Brier Δ | LogLoss Δ | Goal MAE Δ | Total MAE Δ | Score NLL Δ | Exact Top1 Δ | Exact Top3 Δ | Exact Top5 Δ | 1:1 Top1 Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DC new - DC old | 102 | -0.027823 | -0.102523 | -0.133332 | -0.257327 | -0.393610 | -0.009804 | 0.029412 | 0.039216 | 0.088235 |
| rho=0 new - rho=0 old | 97 | -0.012995 | -0.076287 | -0.117810 | -0.259591 | -0.376750 | -0.010309 | 0.041237 | -0.010309 | 0.072165 |
| DC new - rho=0 new | 96 | -0.000736 | -0.000798 | 0.001173 | -0.000266 | -0.003188 | 0.020833 | -0.020833 | -0.010417 | 0.187500 |

正负号按 new - old；Brier、LogLoss、MAE、Score NLL 低于 0 才是改善，命中率/Top-k 高于 0 才是改善。由于不是完整 103-row common sample，这些数字只作 partial diagnostic。

## Required model diagnostics

### DC old (full 103) (n=103)

- 1X2 Brier `0.662536`；LogLoss `1.156665`；Top1 outcome hit `0.485437`
- home/away Goal MAE `1.122284`；Total Goal MAE `1.672452`
- Exact Top1/Top3/Top5 `0.145631` / `0.291262` / `0.427184`；Score NLL `3.545294`
- 1:1 Top1 share `0.427184`；actual 1:1 share `0.165049`
- predicted/actual P(total goals ≥5) `0.204361` / `0.213592`
- λ_home `{"count": 103, "max": 6.879273516428838, "mean": 1.5932087068297167, "median": 1.3993956986206701, "min": 0.18675902949481737, "p05": 0.48521630938286703, "p25": 1.024396476643906, "p75": 2.0297505674824956, "p95": 3.1659370276676415}`
- λ_away `{"count": 103, "max": 7.372208201586067, "mean": 1.4248614203974685, "median": 1.2174450940340598, "min": 0.3121530705359969, "p05": 0.48772944133801577, "p25": 0.9198963931826158, "p75": 1.7424530676581371, "p95": 3.023141670907549}`
- λ_total `{"count": 103, "max": 10.10806052212758, "mean": 3.018070127227184, "median": 2.916098238124441, "min": 0.8173964448946879, "p05": 1.3528653935450035, "p25": 2.3696924837279654, "p75": 3.4214380300915685, "p95": 4.662893434670124}`
- rho `{"count": 103, "max": -0.02841955352176195, "mean": -0.08190855687927402, "median": -0.1, "min": -0.1, "p05": -0.1, "p25": -0.1, "p75": -0.06346308665704609, "p95": -0.040662059276587705}`; boundary hits `{"any": 55, "bounds": [-0.1, 0.1], "lower": 55, "share": 0.5339805825242718, "upper": 0}`
- score-grid tail mass `{"count": 103, "max": 0.038175073166594076, "mean": 0.0006291239444688796, "median": 8.601190282231386e-08, "min": 8.770761894538737e-15, "p05": 4.681710574772084e-12, "p25": 4.381317475488089e-09, "p75": 9.480792945160132e-07, "p95": 0.0001221381120487638}`
- strong favourites `{"p_ge_0.55": {"mean_probability": 0.7049223889466445, "n": 50, "top1_outcome_hit_rate": 0.52}, "p_ge_0.60": {"mean_probability": 0.7509573378349086, "n": 37, "top1_outcome_hit_rate": 0.5405405405405406}, "p_ge_0.65": {"mean_probability": 0.7786265638452702, "n": 30, "top1_outcome_hit_rate": 0.5666666666666667}}`
- calibration `{"classwise": {"away": [{"bin": "<0.50", "calibration_gap": 0.05599576569928838, "empirical_rate": 0.3037974683544304, "mean_probability": 0.247801702655142, "n": 79}, {"bin": "0.50-<0.55", "calibration_gap": 0.08438230325381357, "empirical_rate": 0.6, "mean_probability": 0.5156176967461864, "n": 5}, {"bin": "0.55-<0.60", "calibration_gap": -0.2479188896971643, "empirical_rate": 0.3333333333333333, "mean_probability": 0.5812522230304976, "n": 3}, {"bin": "0.60-<0.65", "calibration_gap": -0.23453671055117298, "empirical_rate": 0.4, "mean_probability": 0.634536710551173, "n": 5}, {"bin": ">=0.65", "calibration_gap": -0.4408730724480514, "empirical_rate": 0.36363636363636365, "mean_probability": 0.804509436084415, "n": 11}], "draw": [{"bin": "<0.50", "calibration_gap": 0.027182653786675837, "empirical_rate": 0.2647058823529412, "mean_probability": 0.23752322856626534, "n": 102}, {"bin": "0.50-<0.55", "calibration_gap": 0.4701198331676818, "empirical_rate": 1.0, "mean_probability": 0.5298801668323182, "n": 1}, {"bin": "0.55-<0.60", "calibration_gap": null, "empirical_rate": null, "mean_probability": null, "n": 0}, {"bin": "0.60-<0.65", "calibration_gap": null, "empirical_rate": null, "mean_probability": null, "n": 0}, {"bin": ">=0.65", "calibration_gap": null, "empirical_rate": null, "mean_probability": null, "n": 0}], "home": [{"bin": "<0.50", "calibration_gap": 0.06394148691664503, "empirical_rate": 0.3333333333333333, "mean_probability": 0.2693918464166883, "n": 66}, {"bin": "0.50-<0.55", "calibration_gap": -0.5103910358479683, "empirical_rate": 0.0, "mean_probability": 0.5103910358479683, "n": 6}, {"bin": "0.55-<0.60", "calibration_gap": -0.07169412783491214, "empirical_rate": 0.5, "mean_probability": 0.5716941278349121, "n": 10}, {"bin": "0.60-<0.65", "calibration_gap": -0.12697051588882402, "empirical_rate": 0.5, "mean_probability": 0.626970515888824, "n": 2}, {"bin": ">=0.65", "calibration_gap": -0.07943121675944964, "empirical_rate": 0.6842105263157895, "mean_probability": 0.7636417430752391, "n": 19}]}, "max_1x2_probability": [{"bin": "<0.50", "calibration_gap": 0.054195340723936336, "empirical_rate": 0.4878048780487805, "mean_probability": 0.43360953732484414, "n": 41}, {"bin": "0.50-<0.55", "calibration_gap": -0.18085957213758835, "empirical_rate": 0.3333333333333333, "mean_probability": 0.5141929054709217, "n": 12}, {"bin": "0.55-<0.60", "calibration_gap": -0.1123613805723549, "empirical_rate": 0.46153846153846156, "mean_probability": 0.5738998421108165, "n": 13}, {"bin": "0.60-<0.65", "calibration_gap": -0.20380351207621622, "empirical_rate": 0.42857142857142855, "mean_probability": 0.6323749406476448, "n": 7}, {"bin": ">=0.65", "calibration_gap": -0.21195989717860353, "empirical_rate": 0.5666666666666667, "mean_probability": 0.7786265638452702, "n": 30}]}`
- extreme probability `{"max_1x2_probability": {"count": 103, "max": 0.9956429244284178, "mean": 0.5747031586728343, "median": 0.5244889474885148, "min": 0.34633938935805625, "p05": 0.3862918812301868, "p25": 0.4640182016620412, "p75": 0.6820770718350371, "p95": 0.8878645122264208}, "observed_outcome_probability": {"count": 103, "max": 0.9244912027417664, "mean": 0.39859585575369255, "median": 0.34049627863188553, "min": 0.0020360421098215074, "p05": 0.0928061611756359, "p25": 0.23128724045615495, "p75": 0.5421114424017541, "p95": 0.8107532697999222}, "observed_outcome_probability_below_0.05": {"n": 3, "share": 0.02912621359223301}, "strong_favourite": {"p_ge_0.55": {"mean_probability": 0.7049223889466445, "n": 50, "top1_outcome_hit_rate": 0.52}, "p_ge_0.60": {"mean_probability": 0.7509573378349086, "n": 37, "top1_outcome_hit_rate": 0.5405405405405406}, "p_ge_0.65": {"mean_probability": 0.7786265638452702, "n": 30, "top1_outcome_hit_rate": 0.5666666666666667}}}`

### DC new (available) (n=102)

- 1X2 Brier `0.634426`；LogLoss `1.054492`；Top1 outcome hit `0.490196`
- home/away Goal MAE `0.989903`；Total Goal MAE `1.411416`
- Exact Top1/Top3/Top5 `0.137255` / `0.323529` / `0.470588`；Score NLL `3.151478`
- 1:1 Top1 share `0.509804`；actual 1:1 share `0.166667`
- predicted/actual P(total goals ≥5) `0.180675` / `0.205882`
- λ_home `{"count": 102, "max": 3.8354873911614233, "mean": 1.5207922014463495, "median": 1.4140269695927021, "min": 0.5004812096583273, "p05": 0.7297821140427537, "p25": 1.0712670767234949, "p75": 1.8719181063629842, "p95": 2.6097697583344006}`
- λ_away `{"count": 102, "max": 3.3179187056620045, "mean": 1.398591575362268, "median": 1.3809159752580031, "min": 0.364612561792154, "p05": 0.6891574120471274, "p25": 1.0610491729974343, "p75": 1.7017952516566999, "p95": 2.1884402833934335}`
- λ_total `{"count": 102, "max": 5.037269577647862, "mean": 2.919383776808617, "median": 2.8921047396804354, "min": 1.6969369482365102, "p05": 2.0509995608472957, "p25": 2.453102449143711, "p75": 3.229847932502852, "p95": 3.93787220220961}`
- rho `{"count": 102, "max": -0.025478776832822247, "mean": -0.054366652451662285, "median": -0.05503186342967223, "min": -0.1, "p05": -0.09279246937374387, "p25": -0.06559944155451672, "p75": -0.042345294597437605, "p95": -0.026189370114611987}`; boundary hits `{"any": 5, "bounds": [-0.1, 0.1], "lower": 5, "share": 0.049019607843137254, "upper": 0}`
- score-grid tail mass `{"count": 102, "max": 0.00018406981383867205, "mean": 2.9579733842376464e-06, "median": 5.106242512153969e-08, "min": 1.4920564783693635e-10, "p05": 1.2663373849530757e-09, "p25": 7.249498418238076e-09, "p75": 2.9492288852739357e-07, "p95": 4.534445088033575e-06}`
- strong favourites `{"p_ge_0.55": {"mean_probability": 0.6510430613613405, "n": 44, "top1_outcome_hit_rate": 0.5454545454545454}, "p_ge_0.60": {"mean_probability": 0.6890169664814482, "n": 30, "top1_outcome_hit_rate": 0.5666666666666667}, "p_ge_0.65": {"mean_probability": 0.7129021366747715, "n": 22, "top1_outcome_hit_rate": 0.5909090909090909}}`
- calibration `{"classwise": {"away": [{"bin": "<0.50", "calibration_gap": 0.018685142563660717, "empirical_rate": 0.3026315789473684, "mean_probability": 0.2839464363837077, "n": 76}, {"bin": "0.50-<0.55", "calibration_gap": -0.1656285047702727, "empirical_rate": 0.36363636363636365, "mean_probability": 0.5292648684066363, "n": 11}, {"bin": "0.55-<0.60", "calibration_gap": -0.06588357194597638, "empirical_rate": 0.5, "mean_probability": 0.5658835719459764, "n": 6}, {"bin": "0.60-<0.65", "calibration_gap": -0.024657169921172506, "empirical_rate": 0.6, "mean_probability": 0.6246571699211725, "n": 5}, {"bin": ">=0.65", "calibration_gap": -0.47421601608158304, "empirical_rate": 0.25, "mean_probability": 0.724216016081583, "n": 4}], "draw": [{"bin": "<0.50", "calibration_gap": 0.0368651280423708, "empirical_rate": 0.27450980392156865, "mean_probability": 0.23764467587919785, "n": 102}, {"bin": "0.50-<0.55", "calibration_gap": null, "empirical_rate": null, "mean_probability": null, "n": 0}, {"bin": "0.55-<0.60", "calibration_gap": null, "empirical_rate": null, "mean_probability": null, "n": 0}, {"bin": "0.60-<0.65", "calibration_gap": null, "empirical_rate": null, "mean_probability": null, "n": 0}, {"bin": ">=0.65", "calibration_gap": null, "empirical_rate": null, "mean_probability": null, "n": 0}], "home": [{"bin": "<0.50", "calibration_gap": -0.024223851770501792, "empirical_rate": 0.2537313432835821, "mean_probability": 0.2779551950540839, "n": 67}, {"bin": "0.50-<0.55", "calibration_gap": 0.4850820709725975, "empirical_rate": 1.0, "mean_probability": 0.5149179290274025, "n": 6}, {"bin": "0.55-<0.60", "calibration_gap": -0.07251053422245979, "empirical_rate": 0.5, "mean_probability": 0.5725105342224598, "n": 8}, {"bin": "0.60-<0.65", "calibration_gap": -0.2877920459975381, "empirical_rate": 0.3333333333333333, "mean_probability": 0.6211253793308714, "n": 3}, {"bin": ">=0.65", "calibration_gap": -0.04372127458436881, "empirical_rate": 0.6666666666666666, "mean_probability": 0.7103879412510354, "n": 18}]}, "max_1x2_probability": [{"bin": "<0.50", "calibration_gap": -0.04433316610226673, "empirical_rate": 0.3902439024390244, "mean_probability": 0.43457706854129113, "n": 41}, {"bin": "0.50-<0.55", "calibration_gap": 0.06403405137426965, "empirical_rate": 0.5882352941176471, "mean_probability": 0.5242012427433774, "n": 17}, {"bin": "0.55-<0.60", "calibration_gap": -0.06967040753253817, "empirical_rate": 0.5, "mean_probability": 0.5696704075325382, "n": 14}, {"bin": "0.60-<0.65", "calibration_gap": -0.12333274844980957, "empirical_rate": 0.5, "mean_probability": 0.6233327484498096, "n": 8}, {"bin": ">=0.65", "calibration_gap": -0.1219930457656806, "empirical_rate": 0.5909090909090909, "mean_probability": 0.7129021366747715, "n": 22}]}`
- extreme probability `{"max_1x2_probability": {"count": 102, "max": 0.8330527466159111, "mean": 0.5428919180071506, "median": 0.5281905191763538, "min": 0.36415823796930546, "p05": 0.38871445067951843, "p25": 0.4505172377918971, "p75": 0.6204745337767805, "p95": 0.7372853078795566}, "observed_outcome_probability": {"count": 102, "max": 0.8330527466159111, "mean": 0.393344080004851, "median": 0.33172954910757707, "min": 0.10626125293226375, "p05": 0.13103489600278084, "p25": 0.24143384862037992, "p75": 0.5334484035051947, "p95": 0.7326547740536176}, "observed_outcome_probability_below_0.05": {"n": 0, "share": 0.0}, "strong_favourite": {"p_ge_0.55": {"mean_probability": 0.6510430613613405, "n": 44, "top1_outcome_hit_rate": 0.5454545454545454}, "p_ge_0.60": {"mean_probability": 0.6890169664814482, "n": 30, "top1_outcome_hit_rate": 0.5666666666666667}, "p_ge_0.65": {"mean_probability": 0.7129021366747715, "n": 22, "top1_outcome_hit_rate": 0.5909090909090909}}}`

### rho=0 old (full 103) (n=103)

- 1X2 Brier `0.661719`；LogLoss `1.150062`；Top1 outcome hit `0.475728`
- home/away Goal MAE `1.119640`；Total Goal MAE `1.671589`
- Exact Top1/Top3/Top5 `0.116505` / `0.281553` / `0.475728`；Score NLL `3.542491`
- 1:1 Top1 share `0.271845`；actual 1:1 share `0.165049`
- predicted/actual P(total goals ≥5) `0.205874` / `0.213592`
- λ_home `{"count": 103, "max": 6.835760607279033, "mean": 1.6038036655244756, "median": 1.4201851087678055, "min": 0.18881104787794373, "p05": 0.4955701685219548, "p25": 1.0311457792888512, "p75": 2.0466718922157274, "p95": 3.1728771640239004}`
- λ_away `{"count": 103, "max": 7.331638475104544, "mean": 1.423811344372418, "median": 1.2234993876792464, "min": 0.3118328071763649, "p05": 0.4809171185138638, "p25": 0.9163145016824816, "p75": 1.740089766059266, "p95": 3.015522810199401}`
- λ_total `{"count": 103, "max": 10.073624473051991, "mean": 3.027615009896894, "median": 2.927793540912769, "min": 0.8163089573833442, "p05": 1.338950968102964, "p25": 2.3928229228836093, "p75": 3.4511114880863314, "p95": 4.689346406992154}`
- rho `{"count": 103, "max": 0.0, "mean": 0.0, "median": 0.0, "min": 0.0, "p05": 0.0, "p25": 0.0, "p75": 0.0, "p95": 0.0}`; boundary hits `{"any": 0, "bounds": [-0.1, 0.1], "lower": 0, "share": 0.0, "upper": 0}`
- score-grid tail mass `{"count": 103, "max": 0.03682071336498427, "mean": 0.0006059549462181295, "median": 8.984380872600894e-08, "min": 6.661338147750939e-15, "p05": 3.940348047848387e-12, "p25": 4.271786535614552e-09, "p75": 9.021574407519495e-07, "p95": 0.0001160359104230176}`
- strong favourites `{"p_ge_0.55": {"mean_probability": 0.7103117934463077, "n": 50, "top1_outcome_hit_rate": 0.52}, "p_ge_0.60": {"mean_probability": 0.7515913883774328, "n": 38, "top1_outcome_hit_rate": 0.5526315789473685}, "p_ge_0.65": {"mean_probability": 0.7784978091732491, "n": 31, "top1_outcome_hit_rate": 0.5483870967741935}}`
- calibration `{"classwise": {"away": [{"bin": "<0.50", "calibration_gap": 0.04997618003305265, "empirical_rate": 0.3037974683544304, "mean_probability": 0.25382128832137774, "n": 79}, {"bin": "0.50-<0.55", "calibration_gap": 0.07923269029654645, "empirical_rate": 0.6, "mean_probability": 0.5207673097034535, "n": 5}, {"bin": "0.55-<0.60", "calibration_gap": -0.25189388487929837, "empirical_rate": 0.3333333333333333, "mean_probability": 0.5852272182126317, "n": 3}, {"bin": "0.60-<0.65", "calibration_gap": -0.1362322491095994, "empirical_rate": 0.5, "mean_probability": 0.6362322491095994, "n": 4}, {"bin": ">=0.65", "calibration_gap": -0.46037372549804584, "empirical_rate": 0.3333333333333333, "mean_probability": 0.7937070588313792, "n": 12}], "draw": [{"bin": "<0.50", "calibration_gap": 0.042589911272821884, "empirical_rate": 0.2647058823529412, "mean_probability": 0.2221159710801193, "n": 102}, {"bin": "0.50-<0.55", "calibration_gap": 0.4833517565958565, "empirical_rate": 1.0, "mean_probability": 0.5166482434041435, "n": 1}, {"bin": "0.55-<0.60", "calibration_gap": null, "empirical_rate": null, "mean_probability": null, "n": 0}, {"bin": "0.60-<0.65", "calibration_gap": null, "empirical_rate": null, "mean_probability": null, "n": 0}, {"bin": ">=0.65", "calibration_gap": null, "empirical_rate": null, "mean_probability": null, "n": 0}], "home": [{"bin": "<0.50", "calibration_gap": 0.05402800792488566, "empirical_rate": 0.328125, "mean_probability": 0.27409699207511434, "n": 64}, {"bin": "0.50-<0.55", "calibration_gap": -0.38925090192435774, "empirical_rate": 0.125, "mean_probability": 0.5142509019243577, "n": 8}, {"bin": "0.55-<0.60", "calibration_gap": -0.13327058437056027, "empirical_rate": 0.4444444444444444, "mean_probability": 0.5777150288150047, "n": 9}, {"bin": "0.60-<0.65", "calibration_gap": 0.03929610748889201, "empirical_rate": 0.6666666666666666, "mean_probability": 0.6273705591777746, "n": 3}, {"bin": ">=0.65", "calibration_gap": -0.0846814409681147, "empirical_rate": 0.6842105263157895, "mean_probability": 0.7688919672839042, "n": 19}]}, "max_1x2_probability": [{"bin": "<0.50", "calibration_gap": 0.027991963049387114, "empirical_rate": 0.46153846153846156, "mean_probability": 0.43354649848907445, "n": 39}, {"bin": "0.50-<0.55", "calibration_gap": -0.1596065719511623, "empirical_rate": 0.35714285714285715, "mean_probability": 0.5167494290940194, "n": 14}, {"bin": "0.55-<0.60", "calibration_gap": -0.16292640949774478, "empirical_rate": 0.4166666666666667, "mean_probability": 0.5795930761644115, "n": 12}, {"bin": "0.60-<0.65", "calibration_gap": -0.06100581056738874, "empirical_rate": 0.5714285714285714, "mean_probability": 0.6324343819959601, "n": 7}, {"bin": ">=0.65", "calibration_gap": -0.23011071239905556, "empirical_rate": 0.5483870967741935, "mean_probability": 0.7784978091732491, "n": 31}]}`
- extreme probability `{"max_1x2_probability": {"count": 103, "max": 0.9956001975624034, "mean": 0.5792077196185008, "median": 0.5284651164304841, "min": 0.3534120467241925, "p05": 0.3906608953718664, "p25": 0.46231366422868037, "p75": 0.6883943245153645, "p95": 0.8914051825148028}, "observed_outcome_probability": {"count": 103, "max": 0.9233352279738525, "mean": 0.4003327645460275, "median": 0.35438169655306534, "min": 0.0028982535209143797, "p05": 0.09867484571428019, "p25": 0.2209426470585606, "p75": 0.5461778435871399, "p95": 0.8146376650593884}, "observed_outcome_probability_below_0.05": {"n": 2, "share": 0.019417475728155338}, "strong_favourite": {"p_ge_0.55": {"mean_probability": 0.7103117934463077, "n": 50, "top1_outcome_hit_rate": 0.52}, "p_ge_0.60": {"mean_probability": 0.7515913883774328, "n": 38, "top1_outcome_hit_rate": 0.5526315789473685}, "p_ge_0.65": {"mean_probability": 0.7784978091732491, "n": 31, "top1_outcome_hit_rate": 0.5483870967741935}}}`

### rho=0 new (available) (n=97)

- 1X2 Brier `0.630358`；LogLoss `1.047339`；Top1 outcome hit `0.494845`
- home/away Goal MAE `1.011863`；Total Goal MAE `1.451574`
- Exact Top1/Top3/Top5 `0.113402` / `0.319588` / `0.463918`；Score NLL `3.196841`
- 1:1 Top1 share `0.340206`；actual 1:1 share `0.164948`
- predicted/actual P(total goals ≥5) `0.179670` / `0.216495`
- λ_home `{"count": 97, "max": 3.8433712129829245, "mean": 1.516230168018259, "median": 1.405573841229593, "min": 0.5193498682727704, "p05": 0.7248238125069077, "p25": 1.084253888296186, "p75": 1.8798657789467133, "p95": 2.617093507032987}`
- λ_away `{"count": 97, "max": 3.318093448729524, "mean": 1.400218605121015, "median": 1.383726107547905, "min": 0.4709846808164565, "p05": 0.7062467054838107, "p25": 1.0582124506694017, "p75": 1.6900264771322446, "p95": 2.1618394335586575}`
- λ_total `{"count": 97, "max": 5.0436537643249855, "mean": 2.9164487731392743, "median": 2.906737902197376, "min": 1.716370846140085, "p05": 2.0312955576427885, "p25": 2.492350946550614, "p75": 3.186176292097536, "p95": 3.9568227170871904}`
- rho `{"count": 97, "max": 0.0, "mean": 0.0, "median": 0.0, "min": 0.0, "p05": 0.0, "p25": 0.0, "p75": 0.0, "p95": 0.0}`; boundary hits `{"any": 0, "bounds": [-0.1, 0.1], "lower": 0, "share": 0.0, "upper": 0}`
- score-grid tail mass `{"count": 97, "max": 0.0001877019333332841, "mean": 3.1270240004696723e-06, "median": 4.830265964983482e-08, "min": 1.5680057252609458e-10, "p05": 1.2270241489531488e-09, "p25": 8.488767466729996e-09, "p75": 2.827733318611081e-07, "p95": 4.829895463576144e-06}`
- strong favourites `{"p_ge_0.55": {"mean_probability": 0.6559960764093928, "n": 42, "top1_outcome_hit_rate": 0.5476190476190477}, "p_ge_0.60": {"mean_probability": 0.691749208380022, "n": 29, "top1_outcome_hit_rate": 0.5517241379310345}, "p_ge_0.65": {"mean_probability": 0.7162649720803375, "n": 21, "top1_outcome_hit_rate": 0.5714285714285714}}`
- calibration `{"classwise": {"away": [{"bin": "<0.50", "calibration_gap": -0.005118418266033931, "empirical_rate": 0.28169014084507044, "mean_probability": 0.28680855911110437, "n": 71}, {"bin": "0.50-<0.55", "calibration_gap": -0.07846996649554078, "empirical_rate": 0.45454545454545453, "mean_probability": 0.5330154210409953, "n": 11}, {"bin": "0.55-<0.60", "calibration_gap": -0.07020151122339346, "empirical_rate": 0.5, "mean_probability": 0.5702015112233935, "n": 6}, {"bin": "0.60-<0.65", "calibration_gap": -0.029020571220105373, "empirical_rate": 0.6, "mean_probability": 0.6290205712201054, "n": 5}, {"bin": ">=0.65", "calibration_gap": -0.47824426953506705, "empirical_rate": 0.25, "mean_probability": 0.728244269535067, "n": 4}], "draw": [{"bin": "<0.50", "calibration_gap": 0.041480323352572124, "empirical_rate": 0.26804123711340205, "mean_probability": 0.22656091376082993, "n": 97}, {"bin": "0.50-<0.55", "calibration_gap": null, "empirical_rate": null, "mean_probability": null, "n": 0}, {"bin": "0.55-<0.60", "calibration_gap": null, "empirical_rate": null, "mean_probability": null, "n": 0}, {"bin": "0.60-<0.65", "calibration_gap": null, "empirical_rate": null, "mean_probability": null, "n": 0}, {"bin": ">=0.65", "calibration_gap": null, "empirical_rate": null, "mean_probability": null, "n": 0}], "home": [{"bin": "<0.50", "calibration_gap": -0.017261170351169974, "empirical_rate": 0.265625, "mean_probability": 0.28288617035117, "n": 64}, {"bin": "0.50-<0.55", "calibration_gap": 0.4765893458015419, "empirical_rate": 1.0, "mean_probability": 0.5234106541984581, "n": 6}, {"bin": "0.55-<0.60", "calibration_gap": -0.009985585547642839, "empirical_rate": 0.5714285714285714, "mean_probability": 0.5814141569762142, "n": 7}, {"bin": "0.60-<0.65", "calibration_gap": -0.2913532577443421, "empirical_rate": 0.3333333333333333, "mean_probability": 0.6246865910776754, "n": 3}, {"bin": ">=0.65", "calibration_gap": -0.06638749032628333, "empirical_rate": 0.6470588235294118, "mean_probability": 0.7134463138556951, "n": 17}]}, "max_1x2_probability": [{"bin": "<0.50", "calibration_gap": -0.0713343059146162, "empirical_rate": 0.3684210526315789, "mean_probability": 0.43975535854619513, "n": 38}, {"bin": "0.50-<0.55", "calibration_gap": 0.11743332019754715, "empirical_rate": 0.6470588235294118, "mean_probability": 0.5296255033318646, "n": 17}, {"bin": "0.55-<0.60", "calibration_gap": -0.03777755124414317, "empirical_rate": 0.5384615384615384, "mean_probability": 0.5762390897056816, "n": 13}, {"bin": "0.60-<0.65", "calibration_gap": -0.12739532866669412, "empirical_rate": 0.5, "mean_probability": 0.6273953286666941, "n": 8}, {"bin": ">=0.65", "calibration_gap": -0.14483640065176606, "empirical_rate": 0.5714285714285714, "mean_probability": 0.7162649720803375, "n": 21}]}`
- extreme probability `{"max_1x2_probability": {"count": 97, "max": 0.8352762277639162, "mean": 0.5491357978411509, "median": 0.5306839318728744, "min": 0.3764270888442748, "p05": 0.3971188124678141, "p25": 0.45709456377156443, "p75": 0.6240211217861434, "p95": 0.7466410388104837}, "observed_outcome_probability": {"count": 97, "max": 0.8352762277639162, "mean": 0.39700340071769114, "median": 0.3375110039419582, "min": 0.1143972637920006, "p05": 0.13281339071836556, "p25": 0.24240329531363025, "p75": 0.5425108921406163, "p95": 0.7408030662880865}, "observed_outcome_probability_below_0.05": {"n": 0, "share": 0.0}, "strong_favourite": {"p_ge_0.55": {"mean_probability": 0.6559960764093928, "n": 42, "top1_outcome_hit_rate": 0.5476190476190477}, "p_ge_0.60": {"mean_probability": 0.691749208380022, "n": 29, "top1_outcome_hit_rate": 0.5517241379310345}, "p_ge_0.65": {"mean_probability": 0.7162649720803375, "n": 21, "top1_outcome_hit_rate": 0.5714285714285714}}}`


### History visible per target

- old 103 targets: `{"all_league_match_count": {"count": 103, "max": 133.0, "mean": 82.35922330097087, "median": 83.0, "min": 32.0, "p05": 34.400000000000006, "p25": 57.0, "p75": 107.0, "p95": 128.89999999999998}, "away_team_match_count": {"count": 103, "max": 21.0, "mean": 9.718446601941748, "median": 10.0, "min": 2.0, "p05": 3.0, "p25": 6.0, "p75": 13.0, "p95": 16.89999999999999}, "home_team_match_count": {"count": 103, "max": 20.0, "mean": 9.766990291262136, "median": 10.0, "min": 2.0, "p05": 3.0, "p25": 6.5, "p75": 13.0, "p95": 16.0}}`
- new 103 targets attempted (including fit-failed rows): `{"all_league_match_count": {"count": 103, "max": 357.0, "mean": 306.3592233009709, "median": 307.0, "min": 256.0, "p05": 258.4, "p25": 281.0, "p75": 331.0, "p95": 352.9}, "away_team_match_count": {"count": 103, "max": 44.0, "mean": 32.116504854368934, "median": 36.0, "min": 2.0, "p05": 5.0, "p25": 33.0, "p75": 40.5, "p95": 43.0}, "home_team_match_count": {"count": 103, "max": 44.0, "mean": 32.407766990291265, "median": 36.0, "min": 3.0, "p05": 6.0, "p25": 32.0, "p75": 40.0, "p95": 43.89999999999999}}`
- new successful model rows: `{"both_models": {"all_league_match_count": {"count": 96, "max": 357.0, "mean": 308.1666666666667, "median": 310.0, "min": 256.0, "p05": 258.0, "p25": 284.0, "p75": 334.0, "p95": 353.25}, "away_team_match_count": {"count": 96, "max": 44.0, "mean": 31.927083333333332, "median": 37.0, "min": 2.0, "p05": 5.0, "p25": 32.0, "p75": 41.0, "p95": 43.25}, "home_team_match_count": {"count": 96, "max": 44.0, "mean": 32.864583333333336, "median": 37.0, "min": 3.0, "p05": 6.75, "p25": 32.0, "p75": 40.25, "p95": 44.0}}, "dixon_coles": {"all_league_match_count": {"count": 102, "max": 357.0, "mean": 306.48039215686276, "median": 307.0, "min": 256.0, "p05": 258.2, "p25": 280.5, "p75": 331.0, "p95": 352.95}, "away_team_match_count": {"count": 102, "max": 44.0, "mean": 32.07843137254902, "median": 36.5, "min": 2.0, "p05": 5.0, "p25": 33.0, "p75": 40.75, "p95": 43.0}, "home_team_match_count": {"count": 102, "max": 44.0, "mean": 32.372549019607845, "median": 36.5, "min": 3.0, "p05": 6.0, "p25": 32.0, "p75": 40.0, "p95": 43.94999999999999}}, "rho0_control": {"all_league_match_count": {"count": 97, "max": 357.0, "mean": 308.02061855670104, "median": 309.0, "min": 256.0, "p05": 258.0, "p25": 284.0, "p75": 334.0, "p95": 353.2}, "away_team_match_count": {"count": 97, "max": 44.0, "mean": 31.969072164948454, "median": 37.0, "min": 2.0, "p05": 5.0, "p25": 32.0, "p75": 41.0, "p95": 43.19999999999999}, "home_team_match_count": {"count": 97, "max": 44.0, "mean": 32.896907216494846, "median": 37.0, "min": 3.0, "p05": 6.800000000000001, "p25": 32.0, "p75": 40.0, "p95": 44.0}}}`

## Expanded secondary diagnostic

- complete Sweden input: `359` matches / `19` teams
- chronological candidates after warmup/network gates: `359`
- successful both-model rows: `101`
- skipped: `{"network_not_connected": 6, "not_all_teams_seen": 213, "warmup": 32}`
- fit failures: `7`
- This diagnostic is not used as the old-vs-new primary improvement claim.

## Final verdict

`INCONCLUSIVE`

固定配置 replay 没有完成同一 103 targets 的双模型闭环：新完整历史下有 7 个 target 至少一个 fixed optimizer fit 未收敛。这个明确的评估完整性 blocker 不是理由去调 rho、half-life 或 optimizer；因此本轮不把 partial 指标解释为历史补全改善，也不把 Dixon-Coles 或 rho=0 架构 promotion。

1. 历史补全是否明显改善：当前不能在完整 103 paired sample 上裁决；补全后的输入确实被读取并形成 19-team connected network。
2. 改善来自基础 network 还是 rho correction：当前不能在完整 paired sample 上裁决；DC new vs rho=0 new 只保留 common successful rows。
3. 1:1 concentration：按 partial diagnostic 报告，但不作为完整样本结论。
4. 极端 lambda / strong-favourite calibration：按 partial diagnostic 报告；fixed-fit failure 本身应保留为模型路线风险。
5. 是否跨联赛继续验证：Sweden-specific further tuning 已 CLOSED；下一候选只记录为 League-Agnostic Historical Coverage / Automatic Coverage Gate，不在本轮实现。

## Governance closeout

- FE-SE-HIST-1: `SEALED` / `ACCEPTANCE PASS`
- FE-SE-DC-CLOSE: `READY_FOR_ACCEPTANCE`
- SWEDEN_SPECIFIC_FURTHER_TUNING: `CLOSED`
- Champion、production prediction、frozen prediction、用户侧预测均未修改
- PR #114 未合并；未生成 ZIP

## Verification

- Closure runner: `READY_FOR_ACCEPTANCE`; verdict `INCONCLUSIVE`; 103 fixed targets retained; 96 targets have both new models; 7 fixed-config fit failures are explicit.
- Focused suite: `41 passed`.
- Python compile, JSON validation, and `git diff --check`: passed.
- Full suite baseline: collection still has the pre-existing `tests/test_live_ev_profile.py` import error; ignoring it gives `866 passed, 5 failed, 6 warnings`. The five failures are stale Champion SHA expectations or the existing public-site fixture missing `prediction_dashboard/latest.json`; no FE-SE-DC-CLOSE test failed.
- Detailed verification evidence: `data/football_data/fe_se_dc_close/verification.json`.

## Research references
- `https://doi.org/10.1111/j.1467-9574.1982.tb00782.x`
- `https://doi.org/10.1111/1467-9876.00065`
- `https://github.com/martineastwood/penaltyblog`
- `https://github.com/jpmouracodex/football-mle`

## Artifacts

- comparison: `data\football_data\fe_se_dc_close\old_vs_new_comparison.json`
- paired full score distributions: `data\football_data\fe_se_dc_close\paired_replay_predictions.json`
- expanded secondary: `data\football_data\fe_se_dc_close\expanded_secondary_diagnostic.json`
- integrity audit: `data\football_data\fe_se_dc_close\integrity_audit.json`
- target reconciliation: `data\football_data\fe_se_dc_close\target_reconciliation.json`

最终状态：`READY_FOR_ACCEPTANCE`
