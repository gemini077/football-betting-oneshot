# 17_NEXT_WORK_后续工作.md

最后更新：2026-08-17  
角色：当前唯一执行指针。只描述“现在只做什么”。

# 当前唯一主线

`Phase PA-2-R1 — Canonical Identity & Paired Challenger Evaluation`

# 1. 为什么现在做它

PA-2 已证明 opponent-adjusted team strength 在 historical holdout 上有研究价值，但尚未与当前 production Champion 在同一批正式比赛上公平对比。

当前 blocker 不能简单归结为“缺 ID”：

- 一部分比赛可能缺 canonical identity；
- 一部分即使 identity 成功，也可能缺 historical strength coverage；
- historical store 当前只覆盖有限赛事体系。

本阶段必须先量化这两类问题。

# 2. 本阶段目标

回答：

> 当前 production / formal prospective fixture 中，有多少比赛能够在不 fuzzy、不猜测的前提下，映射到 historical canonical identity，并完成真正 paired challenger evaluation？

# 3. 必须完成

## A. Production Identity Signal Audit

检查真实存在的结构化 identity：Prediction Universe、BASE job、frozen prediction、frozen input snapshot、Nowscore / 500 structured snapshot、match identity、provider refs / IDs。

## B. Historical Identity Audit

检查 historical result store 是否有 canonical_match_id、competition_id、home_team_id、away_team_id、provider IDs、source aliases、provenance。

## C. Deterministic Mapping

只允许：

1. 同 provider numeric ID；
2. 已有 canonical registry；
3. 已有正式 alias registry；
4. competition-constrained exact unique alias。

禁止 fuzzy、Levenshtein、LLM、网络猜测和人工“看起来像”。

## D. 分开 Coverage

每场必须区分：

- MAPPED；
- IDENTITY_UNAVAILABLE；
- AMBIGUOUS_IDENTITY；
- COMPETITION_UNSUPPORTED；
- HISTORY_UNAVAILABLE。

## E. Current 23 Coverage Matrix

统计 total、identity_mapped、historical_eligible、failure reasons、competition breakdown。

## F. Formal 14 Coverage Matrix

同样统计，并识别真正可 paired subset。

## G. Same-subset Paired Evaluation

只在完全相同 match IDs 上比较：

- Current Champion；
- New Football-only Challenger；
- Market-only；
- Uniform。

指标至少：

- Brier；
- LogLoss；
- Top1 outcome；
- home/away/total goal MAE；
- Exact Top1/Top3/Top5；
- Score NLL（合法概率存在时）；
- Top1 1-1 share；
- lambda gap。

# 4. 指标完整性修正

本阶段必须一并修正 PA-2 报告中的：

1. validation available=250 vs metric sample=249 对账；
2. reliability bucket 标签必须明确互斥区间；
3. strong favourite `>=55 / >=60 / >=65` 必须另算真正 cumulative thresholds。

# 5. 本阶段禁止

- 修改 production Champion；
- 改 production unique_score；
- 回写旧 frozen team IDs；
- fuzzy matching；
- 扩所有历史联赛；
- 新增 provider；
- 用 formal 14 调模型参数；
- 用 formal 14 选 fusion weight；
- 开始 CA-1；
- 自动开始 PA-3；
- 自动开始 PA-2-R2。

# 6. 完成后的分叉

- `PAIRED SIGNAL PROMISING BUT SMALL` → 建议 PA-3
- `HISTORICAL COVERAGE IS MAIN BLOCKER` → 建议定向历史覆盖扩展
- `CHALLENGER CLEARLY WEAK` → STOP_AND_RETHINK
- `PAIRED SAMPLE TOO SMALL` → TOO_SMALL_FOR_DECISION

# 7. 完成状态

Codex 完成本阶段后只能写：

`READY_FOR_ACCEPTANCE`

不得自行写 `SEALED`。
