# 18_ACCEPTANCE_验收标准.md

最后更新：2026-08-17  
角色：定义“什么才算真正做完”。测试全绿不等于验收通过。

# 1. 通用验收原则

任何 Phase 的验收必须至少回答：

1. 目标是否真的完成；
2. 是否有真实证据，而不是报告自述；
3. 是否违反 production / frozen / prospective 边界；
4. 是否有 future leakage；
5. 是否出现 silent failure / silent missing；
6. 是否运行 focused tests；
7. 是否运行要求的 full tests；
8. 是否改变了不该改变的 durable production state；
9. 如果声称“上线”，远端是否真的部署；
10. 是否产生下一阶段需要的可复用证据。

# 2. 阶段状态

Codex 允许：`READY_FOR_ACCEPTANCE`

独立验收结果：

- PASS
- FAIL
- R1_REQUIRED
- INCOMPLETE

只有独立 PASS 后：`SEALED`

# 3. 部署类任务验收

涉及 GitHub / Pages / workflows 的任务，必须分别核：

- local code；
- remote branch；
- PR；
- merge commit；
- `main`；
- workflow run；
- workflow step；
- durable generated state；
- actual Pages；
- Health / freshness。

不得用“pytest passed”证明“已经部署”。

# 4. 模型研究类任务验收

必须验证：

- train / validation / holdout 时间分离；
- evaluation match 不参与训练；
- formal prospective 与 pilot/legacy 分开；
- baseline 与 challenger 使用相同 paired sample；
- unavailable metrics 不用 fabricated epsilon 填充；
- research 不改 production Champion；
- shadow 不回写 frozen prediction；
- 结果不能被用于生成同场赛前 prediction。

# 5. PA-2-R1 Acceptance Gates

## Gate 1 — Identity Safety

必须证明无 fuzzy / Levenshtein / LLM / 网络猜球队；ambiguous identity fail closed；exact alias 必须 competition-constrained 且唯一。

## Gate 2 — Identity vs History Coverage

必须分别统计：

- identity_mapped；
- identity_unavailable；
- ambiguous；
- history_available；
- history_unavailable；
- competition_unsupported。

## Gate 3 — Current 23 Coverage

必须给出 total、mapped、historical eligible、每类 failure reason、按赛事体系分布。

## Gate 4 — Formal 14 Coverage

必须给出同样 coverage，并明确真正 paired sample size。

## Gate 5 — Paired Sample Integrity

Current / Challenger / Market-only / Uniform 必须使用完全相同 match IDs。

禁止 `Current 14 vs Challenger 6` 直接比较。

## Gate 6 — Leakage

每个 Challenger evaluation 必须满足：

`training_max_date < evaluation_fixture_date`

任何 violation → `LEAKAGE_FAIL`

## Gate 7 — Challenger Parameter Integrity

Formal 14 不得参与 team-strength 参数拟合、recency 参数选择、shrinkage 参数选择、fusion weight 选择。

## Gate 8 — Metric Integrity

至少检查：

- 1X2 Brier；
- LogLoss；
- Top1 outcome；
- Goal MAE；
- Exact Top1/3/5；
- Score NLL availability；
- 1-1 share；
- lambda gap。

Score NLL 只有真实概率存在时才能计算。

## Gate 9 — Validation Count Reconciliation

必须解释并统一 validation total、challenger available、metric eligible、insufficient。

## Gate 10 — Reliability Labels

互斥 bins：

- `<0.50`
- `0.50-<0.55`
- `0.55-<0.60`
- `0.60-<0.65`
- `>=0.65`

真正 strong favourite 另算累计 `p>=0.55 / 0.60 / 0.65`。

## Gate 11 — Production Mutation Safety

运行前后验证：

- production predictions；
- input snapshots；
- prospective ledger；
- Champion config；
- calibration；
- dashboard latest。

## Gate 12 — Tests

- focused tests PASS；
- full `python -m pytest -q` PASS（若无已知非本任务阻断）。

## Gate 13 — Required Evidence

交付至少：

- `FINAL_REPORT.md`
- `identity_bridge_audit.json`
- `paired_challenger_evaluation.json`
- `paired_challenger_predictions.csv`
- 关键修改源码
- 关键 tests

正式交付放：

`D:\MyProject\_deliveries\football-betting-oneshot\`

# 6. PA-2-R1 最终结论允许值

研究阶段结果：

- PAIRED_EVALUATION_AVAILABLE
- PARTIAL_PAIRED_EVALUATION
- IDENTITY_BRIDGE_INSUFFICIENT
- HISTORICAL_COVERAGE_INSUFFICIENT

Challenger verdict：

- PROMISING
- NEUTRAL
- FAIL
- TOO_SMALL_FOR_DECISION

下一阶段只能建议，不得自动执行：

- PA-3_SHADOW
- TARGETED_HISTORY_EXPANSION
- STOP_AND_RETHINK

# 7. 产品逻辑验收高于“测试全绿”

过去已经出现：

- workflow SUCCESS 但 workspace stale；
- full tests PASS 但 21/23 unique score = 1-1。

因此以后必须同时做：

`Tests + Real Data Sanity + Product Behavior + Durable State`
