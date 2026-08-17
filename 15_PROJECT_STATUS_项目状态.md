# 15_PROJECT_STATUS_项目状态.md

最后更新：2026-08-17  
角色：项目当前唯一人类可读状态真相。只记录当前事实，不承担完整历史档案职责。

# 1. 当前生产状态

- 本地项目：`D:\MyProject\football-betting-oneshot-main`
- GitHub：`gemini077/football-betting-oneshot`
- 生产自动化：已运行
- GitHub Pages：已运行
- 足球业务时区：Asia/Shanghai
- 当前正式 Champion：`recent_form_market_calibrated_poisson_v2`
- CA-1 高级当前分析层：PAUSED

# 2. 已完成 / 已封版

## Production Foundation

- Prediction Universe：SEALED
- BASE Job / eligibility / freeze：SEALED
- Verified 90m result settlement：SEALED
- Prospective ledger：SEALED
- Production automation：SEALED
- Production health：SEALED
- P0 Workspace Auto-Update Recovery：SEALED / DEPLOYED

P0 已验证：

- New Dashboard 自动更新；
- Match Workspace 自动更新；
- Core 读取当天 workspace；
- freshness health guard；
- static page version polling / reload；
- GitHub durable state 与 Pages 实际日期一致。

## Frontend

- Slice 1A Homepage：SEALED
- Slice 1B Match Detail Infrastructure：DONE
- R2.1 terminology/timezone cleanup：DONE
- Legacy Mapper：DONE / HISTORICAL COMPATIBILITY ONLY

## Prediction Integrity

- PA-1 Prediction Sanity & Score Collapse Audit：SEALED
- PA-1-R1 Scenario Replay & Metric Integrity：SEALED
- PA-2 Opponent-Adjusted Strength Challenger：HISTORICAL RESEARCH VALID / OVERALL INCOMPLETE

# 3. 当前最重要问题

## 3.1 Exact-score collapse

2026-08-15 production snapshot：

- FROZEN：23
- unique_score = 1-1：21/23 = 91.30%
- 1X2 leader：HOME 12 / AWAY 11 / DRAW 0
- 两边 lambda 同时落在 1–2：21/23
- `abs(lambda_home-lambda_away) < 0.5`：16/23

结论：

`CURRENT_SELECTOR = FAIL`

问题不是随机填值，而是：

`Selector Collapse + Underlying Lambda Compression`

## 3.2 现有 selector 替代方案未通过

Formal prospective 14 场：

| 方法 | Exact Top1 | 比分派生1X2 | Selected Total Goals MAE |
|---|---:|---:|---:|
| Current Matrix MAP | 14.29% | 42.86% | 1.714 |
| Outcome-conditioned | 0% | 28.57% | 1.643 |
| Existing Scenario Challenger | 0% | 28.57% | 1.357 |

因此：

- 不直接切 Outcome-conditioned；
- 不直接切 Scenario Challenger；
- 不用“减少1-1”作为成功目标。

## 3.3 当前 production calibration 状态

当前已审计 calibration artifact：

- `status = shadow_only`
- `active = false`
- direction approved = false
- total goals approved = false
- dispersion approved = false

当前 production Dixon-Coles 调用中 `rho = 0.0`。

因此当前模型名中的 `calibrated` 不能被产品端理解成“已成熟校准”。

# 4. PA-2 Historical Challenger 状态

Research model：

`opponent_adjusted_strength_poisson_v1`

已审计历史结果：

- 约 1554 场；
- 时间范围：2025-02-22 → 2026-08-03；
- 主要覆盖：葡超、挪超、巴甲、芬超、美职联、瑞典超级/次级等有限赛事体系。

Historical holdout：

- total ≈ 314；
- challenger available ≈ 308；
- Football-only Brier ≈ 0.641651；
- Football-only LogLoss ≈ 1.068304；
- Uniform Brier ≈ 0.666667；
- Uniform LogLoss ≈ 1.098612。

说明 opponent-adjusted strength 路线值得继续研究。

但：

- historical predicted Top1 1-1 ≈ 42.21%；
- historical actual 1-1 ≈ 13.31%。

因此 Challenger 仍未解决比分集中问题。

# 5. PA-2 当前 blocker

PA-2 尚未能对 current production 23 场和 formal prospective 14 场完成安全 paired evaluation。

必须区分：

1. Identity Coverage：能否确定 production 球队对应哪个 canonical team；
2. Historical Strength Coverage：即使知道是谁，历史数据库是否有足够 prior matches。

历史库赛事覆盖有限，因此“补 ID”并不等于当前全部比赛都能进入 challenger。

# 6. 当前阶段

`Phase PA-2-R1 — Canonical Identity & Paired Challenger Evaluation`

状态：

`CURRENT / NOT YET ACCEPTED`

目标：

把能安全 deterministic mapping 的 production / formal fixtures 接到 historical strength challenger，在完全相同比赛子集上公平比较 Current、Challenger、Market-only、Uniform。

# 7. 当前暂停

`CA-1 — Current Constrained Analysis Layer`

状态：

`BLOCKED / PAUSED`

暂停原因：

当前 prediction baseline 尚未达到值得建设高级解释层的质量。禁止用高级文本分析包装已知存在结构性问题的比分 headline。

# 8. 当前禁止事项

- 不修改 production Champion；
- 不重写 frozen predictions；
- 不回填赛后数据到赛前模型；
- 不启用 Scenario Challenger；
- 不强制比分服从 1X2；
- 不人工减少 1-1；
- 不重新扩 Legacy Mapper；
- 不开始 CA-1；
- 不在 PA-2-R1 中一口气扩全世界历史联赛；
- 不使用 fuzzy / LLM / 人工猜测 identity mapping；
- 不使用 formal 14 调 Challenger 参数；
- 不把 workflow success 当作部署完成证据。

# 9. Prospective / Promotion 治理

当前约束：

- 新 Challenger 先 shadow；
- 约 40–50 新 prospective 样本后，才进入严肃 challenger review；
- 约 100 或更多成熟样本后，才考虑 Champion promotion；
- promotion 必须综合历史 holdout、prospective、Market-only 和当前 Champion；
- 不因短期连胜或单场表现直接换 Champion。

# 10. 交付治理

正式验收文件统一：

`D:\MyProject\_deliveries\football-betting-oneshot\`

仓库内不新增新的 handoff / delivery / evidence ZIP。

历史 `artifacts/*handoff.zip` 是遗留治理债，暂不在当前阶段删除。
