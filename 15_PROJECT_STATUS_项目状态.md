# 15_PROJECT_STATUS_项目状态.md

最后更新：2026-08-30
角色：项目当前唯一人类可读状态真相。只记录当前事实，不承担完整历史档案职责。

# PRED-AVAIL-2 Current State

Status: `READY_FOR_ACCEPTANCE`

PRED-AVAIL continuous development is `CLOSED` after this bounded milestone.
The exact 2026-08-30 frozen cohort remains 25 fixtures with cohort SHA-256
`0cf4f106c34f183c3d61a81952f70e9c7f2525c0376a1e6eff74bb087e15cb8d`.
BASELINE (PRED-AVAIL-1 AFTER): 2 `FULL`, 23 `MISSING_RECENT_FORM`.
PRED-AVAIL-2 offline AFTER: 2 `FULL`, 0 `DEGRADED`, 23
`INSUFFICIENT_DATA` / `MISSING_RECENT_FORM`, 0 prediction failures, and 0
blocked Champion jobs. `CALL_COUNT = 0` and `CACHE_HIT_COUNT = 0` because the
required football-data.org credential is absent.

Source preflight result:
`LIVE_VALIDATION_BLOCKED_BY_CREDENTIAL`. No token was logged, persisted, or
registered. The adapter contract, exact fixture bridge, provider-scoped team
identity, cache governance, no-leakage checks, and offline evidence are ready;
live coverage improvement was not claimed.

The primary candidate is the official football-data.org v4 API: free-tier
competition coverage, stable provider fixture/team IDs, exact UTC kickoff
bridge, and competition/team match routes. FotMob and SofaScore remain
research-only candidates. Football-Data.co.uk remains the existing historical
download source and is not confused with football-data.org.

The provider route keeps `CURRENT_FORM_PROVIDER_IDENTITY` separate from
`CANONICAL_HISTORICAL_IDENTITY`, uses no fuzzy or LLM team matching, and emits
the existing Champion `home_overall`, `home_home`, `away_overall`, and
`away_away` contract only after FINISHED, pre-kickoff, complete-goal evidence.
No Champion math, evidence gate, market-only fallback, synthetic evidence,
frozen prediction, prospective ledger, dashboard, runtime state, or
league-specific adapter changed.

Final verdict: `D. LIVE_VALIDATION_BLOCKED_BY_CREDENTIAL`.
The product remains blocked at 23/25 unavailable. The next decision is
`Data Supply Architecture Decision`; PRED-AVAIL-3 and additional provider
patches are not started.

# PRED-AVAIL-1 Engineering Acceptance Record (historical)

Status: `ENGINEERING_ACCEPTED / PRODUCT_BLOCKER_REMAINS`

The same 25-fixture cohort was retained. BEFORE was 1 FULL/frozen and 24
`MISSING_RECENT_FORM`; the bounded AFTER replay is 2 FULL, 0 DEGRADED, 23
`INSUFFICIENT_DATA` / `MISSING_RECENT_FORM`, 0 prediction failures, and 0
blocked Champion jobs. The generic authoritative-history route released only
`500-1364199` Bodo/Glimt - Rosenborg. The existing frozen Celta Vigo - Athletic
Club artifact was preserved, and no production automatic state was rewritten.

PRED-AVAIL-1 code, tests, evidence, and the latest automatic refresh were
merged through PR #119 at
`f6a130a6ded64cc6e2e337e759064cd1673fba86`. This record deliberately does not
label the product result PASS.

# ID-AUTO-1 Acceptance Record (historical)

Status: `SEALED / ACCEPTANCE PASS`

HC-AUTO-1 is now `SEALED / ACCEPTANCE PASS` after independent acceptance. PR
#117 was merged to `main` at
`7680c57475c907ba87cf40c9c1a3d1d48543edb1` without reverting the latest
automatic prediction-universe, BASE-ledger, market/fetch, prospective, frozen,
dashboard, or runtime state.

ID-AUTO-1 adds a league-agnostic deterministic team identity registry and
resolver. The registry consolidates existing provider IDs, reviewed
crosswalks, canonical historical IDs, source names, and reviewed aliases. It
uses the five-level exact ladder and keeps ambiguous/unresolved identity
fail-closed for the historical challenger. No league-specific resolver,
fuzzy match, new provider, Champion change, frozen mutation, or history-store
mutation was introduced.

The real 2026-08-29 through 2026-08-31 Prediction Universe audit covers 66
fixtures in one batch. BEFORE ID-AUTO-1: 1 `SUPPORTED`, 65 `UNSUPPORTED`, and
0 blocked Champion jobs. AFTER: 2 `SUPPORTED`, 0 `DEGRADED`, 64 `UNSUPPORTED`,
11 resolved sides across 2 fully resolved and 7 partial fixtures, and 0 blocked
Champion jobs. The remaining 57 fully unresolved fixtures and 7 partial rows
are recorded in the deterministic backlog.

`FE-SE-HIST-1` is `SEALED / ACCEPTANCE PASS` after PR #115 was merged to main. Its authoritative Sweden closure remains 2025=240, 2026=119, Sweden=359, global historical=1778, unresolved=0, duplicate/conflict=0, and connected 2025 network=true.

`FE-SE-DC-CLOSE` replays the exact FE-DC-1 103 target IDs with the frozen configuration against old 1554-row history and new 1778-row history. Target reconciliation is exact for 103/103. Complete-history replay has 7 model-specific fixed-optimizer fit failures, leaving 96 targets with both models; no tuning or fallback was applied. Final research verdict: `INCONCLUSIVE` because this is an explicit evaluation-integrity blocker, not a reason to change parameters.

`SWEDEN_SPECIFIC_FURTHER_TUNING` is `CLOSED`. PR #114 remains OPEN and unmerged. Champion `recent_form_market_calibrated_poisson_v2`, production prediction, frozen prediction, and user prediction surface are unchanged.

`FE-SE-DC-CLOSE` is `ACCEPTANCE PASS / CLOSED`; its model verdict remains
`INCONCLUSIVE` solely because 7 of the original 103 fixed-config targets had
optimizer fit failures. `SWEDEN_SPECIFIC_FURTHER_TUNING` is `CLOSED`, PR #114
remains OPEN and unmerged, and no Sweden/DC computation was run in HC-AUTO-1.

ID-AUTO-1 is an accepted historical milestone: `SEALED / ACCEPTANCE PASS`.
Do not start ID-AUTO-2 automatically; the identity backlog is
`NON_BLOCKING / ON_DEMAND`.

# FE-SE-HIST-1 Acceptance Record

`FE-SE-HIST-1` = `SEALED / ACCEPTANCE PASS`

PR #115 was merged without reverting the intervening automatic market/data refresh commits. The closure audit, manifest, normalized sample, deterministic identity evidence, focused tests, and authoritative digest are retained in main. FE-SE-HIST-1 is now historical governance evidence, not the active Sweden execution pointer.
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

- 1,778 场（FE-SE-HIST-1 closure 后）；
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

# 5. PA-2-R1 当前 blocker 与 ID2 状态

PA-2-R1 的 DATA / ID / COV-SRC / ID2 证据已真实生成并完成核验。ID2 evidence package/status 为 `READY_FOR_ACCEPTANCE / INDEPENDENT ACCEPTANCE PENDING`；PA-2-R1 model program overall 仍为 `OVERALL INCOMPLETE / TOO_SMALL_FOR_DECISION`，原因是 formal paired sample 只有 1。

ID2 的正式 cohort 语义为 `formal eligible = 9`，另有 `excluded pilot = 5`。历史文档中的 `Formal 14` 只保留为旧 cohort label，不能继续作为当前执行分母。

正式 eligible=9 的 deterministic bridge 结果：

- `AVAILABLE = 1`；
- `COMPETITION_UNSUPPORTED = 6`；
- `HISTORY_UNAVAILABLE = 1`；
- `IDENTITY_UNAVAILABLE = 1`；
- `paired = 1`，且所有 paired methods 使用同一 match ID。

Hearts–Benfica 两队 identity 已由官方 fixture/球队证据 deterministic solved，但 Europa history 仅满足 2/5 的目标 prior 门槛；Elfsborg 仍为 `IDENTITY_UNAVAILABLE`。这两项不能被写成已 paired。

FE-SE-HIST-1 and FE-SE-DC-CLOSE are historical closure records; HC-AUTO-1 is the active execution pointer.

必须区分：

1. Identity Coverage：能否确定 production 球队对应哪个 canonical team；
2. Historical Strength Coverage：即使知道是谁，历史数据库是否有足够 prior matches。

历史库赛事覆盖有限，因此“补 ID”并不等于当前全部比赛都能进入 challenger。

# 6. 上一研究阶段

`Phase PA-2-R1 — Canonical Identity & Paired Challenger Evaluation`

状态：`HISTORICAL RESEARCH / OVERALL INCOMPLETE / TOO_SMALL_FOR_DECISION`

ID2 evidence package/status：`READY_FOR_ACCEPTANCE / INDEPENDENT ACCEPTANCE PENDING`

FE-SE-HIST-1 是当前已完成、等待独立验收的 bounded closure；PA-2-R1 ID2/PR #114 证据保留为历史研究记录。

目标：

把能安全 deterministic mapping 的 production / formal fixtures 接到 historical strength challenger，在完全相同比赛子集上公平比较 Current、Challenger、Market-only、Uniform。

Champion 保持不变：`recent_form_market_calibrated_poisson_v2`。Challenger 仍为 shadow-only；CA-1 保持 paused；PA-3 尚未开始。

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
- 不使用旧 `Formal 14` label 调 Challenger 参数；当前 formal 分母使用 `formal eligible=9`，且仍不得用于参数选择；
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
