# FE-DA-1 — Dynamic Attack/Defense Bounded Baseline

状态：`READY_FOR_ACCEPTANCE`

## Scope

本实验是 research/shadow-only。使用已存在的
`prospective_football_evidence.v1` sidecar 中、目标开球前已捕获的历史比赛
结果；不改 Champion、production、frozen prediction、provider 或任何
rolling xG / lineup 分支。

模型只有一个预注册配置：
`dynamic-attack-defense:bounded-v1`。它按历史比赛时间顺序更新攻击与防守
latent factor，固定 `learning_rate=0.12`，不进行 recent-form weight sweep。
目标比赛结果从未传给特征构造；同日但只有日期精度的历史行不纳入。

## Paired sample

- Current Champion：`recent_form_market_calibrated_poisson_v2`，正式冻结、已结算记录。
- 选择规则：按 `match_key` 去重，每场保留最新合法的开球前 Champion freeze，且必须有匹配 evidence sidecar。
- 候选记录：28；去重排除：21；最终严格配对：7 个唯一 `match_key`。
- 目标 kickoff（UTC）：`2026-08-28T17:00:00+00:00` 至 `2026-08-28T19:30:00+00:00`。
- 每场历史行：58–60；历史日期范围：2025-11-29 至 2026-08-24。
- 7/7：history kickoff < target kickoff；source cutoff < target kickoff；evidence capture < target kickoff；target result excluded。

## Metrics (n=7)

| metric | Dynamic A/D | Champion | Dynamic - Champion |
|---|---:|---:|---:|
| 1X2 Brier | 0.636382 | 0.578259 | +0.058123 |
| 1X2 LogLoss | 1.061186 | 0.970788 | +0.090398 |
| Goal MAE | 1.319707 | 1.058858 | +0.260849 |
| Exact Top1 | 0.142857 | 0.000000 | +0.142857 |
| Exact Top3 | 0.142857 | 0.142857 | 0.000000 |
| Exact Top5 | 0.142857 | 0.142857 | 0.000000 |
| 1:1 share | 0.285714 | 0.857143 | -0.571429 |

Dynamic Score NLL：`3.889033`，`REAL`，n=7。Champion Score NLL：不计算；
frozen Champion 只保存 top-10 score cells，缺少可复核的完整 score distribution。

## Lambda / tail evidence

- Dynamic λ_home：mean 1.197398，median 1.381848，min–max 0.770010–1.469304。
- Dynamic λ_away：mean 1.173886，median 1.131032，min–max 0.827191–1.710627。
- Champion λ_home：mean 1.655361，median 1.476760，min–max 1.186362–2.464835。
- Champion λ_away：mean 1.423211，median 1.365984，min–max 1.249777–1.855165。
- 实际大比分尾部（总进球 ≥5）：4/7 = 0.571429；Dynamic 完整 Poisson 预测尾部：0.096057。
- `1:1 share` 与大比分尾部均为描述性指标，不是优化目标。

## Production mutation check

本分支只新增 research module、focused tests、紧凑结果与本说明；没有修改
`scripts/automatic_model_core.py`、`scripts/base_prediction_runner.py`、
production workflow、Champion prediction 或 frozen input snapshot。
`research_only=true`、`validated_for_model=false`、`production_mutation=false`。

## Known limitations / result

样本仍小，且受现有 evidence sidecar 覆盖限制；provider-scoped numeric team ID
没有被提升为 canonical identity。该结果只说明本 bounded baseline 在当前 7 场
严格配对样本上弱于 Champion 的 1X2 与 Goal MAE，不触发 promotion 或生产接线。

RESULT：`READY_FOR_ACCEPTANCE`
