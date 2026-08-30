# 18_ACCEPTANCE_验收标准.md

最后更新：2026-08-30
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

# 2A. FE-SE-HIST-1 专项验收

`FE-SE-HIST-1 — Sweden Historical Completeness Closure` 的 Codex 状态只允许 `READY_FOR_ACCEPTANCE` 或 `BLOCKED`；本阶段不自动进入 `SEALED`。

必须用真实、可复现证据核对：

- Football-Data 当前 Sweden/Allsvenskan CSV、raw SHA256、capture timestamp、旧 source manifest 与现有 adapter/cache/registry；
- 根因属于抓取缺失、adapter 漏导入、identity、dedup 或其他原因的证据链；
- 2025 `240/240`，canonical competition=`competition:sweden-allsvenskan`，每条 identity deterministic exact、unresolved=0；
- 2025 每队历史场数、完整 connected network、最早/最晚 kickoff；2026 保持 authoritative `119`，不得借机扩展当前赛季；
- candidate duplicate、已有比赛 overlap、duplicate conflict 分开计数；事实冲突必须在 authoritative write 前阻断；
- provenance 中的 source URL、source record ref、source fact time、capture time、raw hash 保留；raw provider 文件不提交；
- 至少一个第二公开来源的 bounded sample 交叉核对；本轮 OpenFootball 53/53 shared fixture、比分冲突=0；
- authoritative DuckDB before/after record count、dataset digest、non-target digest preservation，以及重复运行 idempotent；
- production Champion、production prediction、frozen prediction、FE-DC-1 参数和其他联赛均未改变。

FE-SE-HIST-1 的代码、normalized sample、source/identity manifest、audit JSON、focused tests 和 PR 必须留在 GitHub；不生成 ZIP。该数据 closure 只为后续 research/shadow 使用，不构成模型 promotion。

# 2B. FE-SE-DC-CLOSE Acceptance

`FE-SE-DC-CLOSE — Sweden History Closure + Fixed-Config Re-evaluation` uses only the FE-DC-1 implementation, runner/evaluation contract, and focused tests needed for a fixed replay. Its Codex status is only `READY_FOR_ACCEPTANCE` or `BLOCKED`.

Acceptance evidence must show:

- PR #115 merged to main and FE-SE-HIST-1 recorded as `SEALED / ACCEPTANCE PASS`; PR #114 remains OPEN and unmerged.
- Exact old FE-DC-1 target set is preserved: 103/103 IDs, with deterministic reconciliation and no silent target substitution.
- Old 1554-row / 135-match input and new 1778-row / 359-match input are recorded by digest; new history is strictly pre-match and the fixed configuration is unchanged.
- Primary metrics include 1X2 Brier/LogLoss/Top1, strong-favourite thresholds, home/away/total Goal MAE, P(total>=5), Exact Top1/3/5, Score NLL, 1:1 shares, lambda/rho/tail/calibration/extreme diagnostics, and visible history counts.
- rho=0 new-vs-old, Dixon-Coles new-vs-old, and Dixon-Coles-vs-rho=0 comparisons state their exact common sample counts. Partial results cannot be promoted as a complete 103-row improvement.
- Any optimizer or data-integrity failure is retained explicitly; no parameter tuning, fallback, silent row removal, or second repair pass is allowed.
- Expanded 359-match diagnostic is secondary only and cannot replace the 103-target paired comparison.
- Champion, production predictions, frozen predictions, user prediction surface, providers, and other leagues are unchanged.
- Final verdict is one of `DATA_COMPLETENESS_WAS_MAJOR_BLOCKER`, `BASE_MODEL_USEFUL_DC_NOT_USEFUL`, `MODEL_ROUTE_NOT_JUSTIFIED`, or `INCONCLUSIVE`; `INCONCLUSIVE` is valid only for the explicit evaluation-integrity blocker recorded in the artifacts.
- Sweden-specific further tuning is `CLOSED`; the next pointer is only `League-Agnostic Historical Coverage / Automatic Coverage Gate`.
# 2C. HC-AUTO-1 Acceptance

`HC-AUTO-1 - League-Agnostic Historical Coverage Foundation` may be marked by
Codex only as `READY_FOR_ACCEPTANCE`. Independent acceptance must verify the
following:

1. A versioned coverage registry exists and every competition row records
   source availability, seasons, latest completed season, current-season
   status, historical/team counts, exact identity coverage, history depth,
   freshness, source quality, use restrictions, automatic-import capability,
   last successful refresh, and failure reasons.
2. One manifest/adapter-driven gate returns only `SUPPORTED`, `DEGRADED`, or
   `UNSUPPORTED`, with machine-readable reason codes including
   `COMPETITION_UNSUPPORTED`, `IDENTITY_UNAVAILABLE`, `HISTORY_INSUFFICIENT`,
   `SOURCE_STALE`, `SOURCE_UNAVAILABLE`, and `CURRENT_SEASON_PARTIAL`.
3. The current mixed Prediction Universe can be audited in one batch; an
   unsupported row never blocks supported/degraded rows or the current
   Champion job.
4. No fuzzy identity, invented history, new country-specific adapter, new
   paid provider, historical-store rebuild, Champion math change, or frozen
   prediction mutation is present.
5. Focused tests and the full test suite pass. Historical-store count/digest,
   Champion behavior, frozen predictions, and prospective records are
   unchanged.
6. The next coverage backlog is recorded as evidence only. The task stops at
   `READY_FOR_ACCEPTANCE` and does not start HC-AUTO-2.

# 2D. ID-AUTO-1 Acceptance

`ID-AUTO-1 - League-Agnostic Deterministic Team Identity Resolution` may be
marked by Codex only as `READY_FOR_ACCEPTANCE`. Independent acceptance must
verify:

1. `identity_registry.v1` exists with canonical team, competition scope,
   provider ID/name, reviewed alias, evidence, confidence and ambiguity fields.
2. The same five-level deterministic ladder is used for every competition;
   fuzzy matching, transliteration, LLM guessing, kickoff proximity and
   highest-score selection are absent.
3. Existing stable provider IDs are reusable, exact names are competition
   constrained, and ambiguous candidates fail closed.
4. The exact 66-fixture cohort has a reproducible BEFORE/AFTER audit, including
   by-competition results, the six existing-history groups, and the A–E identity
   chain counts.
5. Identity gaps do not block Champion jobs; the authoritative historical store,
   frozen predictions, prospective records and Champion mathematics are
   unchanged.
6. Japan J1 and Spain La Liga are only recorded against existing generic import
   paths; no league-specific importer is added or executed.
7. Focused tests pass, evidence is committed, and the task stops at
   `READY_FOR_ACCEPTANCE` without starting ID-AUTO-2.

# 2E. PRED-AVAIL-1 Acceptance

`PRED-AVAIL-1 - Daily Prediction Availability Closure` may be marked by Codex
only as `READY_FOR_ACCEPTANCE`. Independent acceptance must verify:

1. The exact 25-fixture cohort and cohort SHA-256 are retained, with the
   baseline showing 1 frozen/fully predicted and 24 `MISSING_RECENT_FORM`.
2. All 24 missing rows have a fixture-level root-cause audit, reusable-source
   inventory, exact identity status, history status, and acquisition path.
3. The generic authoritative-history bridge is read-only, pre-kickoff, exact-ID
   only, eligible-record only, fresh, provenance-carrying, and covered by tests.
4. The same-cohort AFTER result reports FULL/DEGRADED/INSUFFICIENT_DATA,
   MISSING_RECENT_FORM, identity/source/history blockers, prediction failures,
   Champion jobs blocked, and per-competition deltas.
5. No synthetic evidence, market-only production fallback, Champion math change,
   frozen rewrite, prospective mutation, provider addition, fuzzy identity, or
   league-specific patch is present. Protected automatic state hashes are
   unchanged.
6. The current result remains `READY_FOR_ACCEPTANCE` and is not called PASS by
   Codex. The remaining availability gap is recorded as a product blocker;
   IDENTITY_BACKLOG is `NON_BLOCKING / ON_DEMAND` and ID-AUTO-2 is not started.

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

## Gate 4 — Formal eligible Coverage

必须给出同样 coverage，并明确真正 paired sample size。当前正式分母为 `formal eligible=9`，另有 `excluded pilot=5`；`Formal 14` 仅是历史 label。

## Gate 5 — Paired Sample Integrity

Current / Challenger / Market-only / Uniform 必须使用完全相同 match IDs。

禁止 `Current 14 vs Challenger 6` 直接比较。

## Gate 6 — Leakage

每个 Challenger evaluation 必须满足：

`training_max_date < evaluation_fixture_date`

任何 violation → `LEAKAGE_FAIL`

## Gate 7 — Challenger Parameter Integrity

旧 `Formal 14` label 不得参与 team-strength 参数拟合、recency 参数选择、shrinkage 参数选择、fusion weight 选择；当前 `formal eligible=9` 也不得用于这些选择。

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

## 5A. ID2 当前验收快照

ID2 已验证并可供独立验收，但 Codex 不得将其写成 `SEALED`：

- `formal eligible=9`，`excluded pilot=5`；
- `AVAILABLE=1`、`COMPETITION_UNSUPPORTED=6`、`HISTORY_UNAVAILABLE=1`、`IDENTITY_UNAVAILABLE=1`；
- `paired=1`，`same_match_ids_for_all_methods=true`；
- `result_gate=PARTIAL_PAIRED_EVALUATION`，`verdict=TOO_SMALL_FOR_DECISION`；
- Hearts–Benfica identity 已 deterministic solved，但 Europa history 为 2/5，仍不可 eligible；Elfsborg 仍 identity unavailable；
- shared authoritative baseline 是 1,554 historical results / 160 team-strength snapshots；Europa v3 summary 为 `record_count=2,153`、`eligible_count=1,559`、`excluded_count=594`，只属于 staging；
- FE-SE-HIST-1 后 shared historical store 的当前 digest/计数以 `data/football_data/fe_se_hist1/audit.json` 与 `data/football_data/manifests/historical_results.dataset.json` 为准：1,778 条；该 closure 不重建 team-strength snapshots；
- 赛后 captured Europa source 不得作为 pre-match prospective evidence；Champion 不变，Challenger shadow-only，CA-1 paused，PA-3 not started。

ID2 evidence package/status：`READY_FOR_ACCEPTANCE / INDEPENDENT ACCEPTANCE PENDING`；这不代表 PA-2-R1 model program overall 已通过。

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

# 2G. DATA-PLANE-1 Acceptance

`DATA-PLANE-1 — Cloud Production Football Data Architecture Decision` may be
marked by Codex only as `READY_FOR_ACCEPTANCE`. Independent acceptance must
verify:

1. The latest checked `origin/main` and current production projection are
   recorded without treating the isolated PRED-AVAIL replay as deployment.
2. A clean temporary runner that has no developer `FOOTBALL_DATA_HOME`, local
   cache, Windows file or developer DuckDB is used for the reproducibility
   test.
3. The existing offline rebuild repeats deterministically for its tracked
   inputs, while its 206-row result/digest is explicitly compared with the
   authoritative 1778-row result/digest. The result is
   `PARTIALLY_REPRODUCIBLE`, not `FULLY_REPRODUCIBLE`.
4. The bounded clean source proof uses a versioned temporary dataset and exact
   identity/cutoff checks to make `500-1364199` eligible through the existing
   `authoritative_historical_results` route.
5. Options A-D are compared on build time, source failure, licensing,
   durability, rollback, cost, maintenance, update frequency, scale and
   public-repository impact; GitHub cache/artifact is excluded as sole truth.
6. The final decision is `B. PRIVATE_SNAPSHOT_STORE`, with A retained only as
   an offline publisher/recovery builder. No R2/S3/Supabase provisioning,
   runtime migration, new provider, model change, frontend change or
   production-state mutation is part of this milestone.
7. The later implementation contract includes exact object/version pins,
   artifact and logical digest verification, atomic `FOOTBALL_DATA_HOME`
   bootstrap, read-only DuckDB access, last-known-good fallback and manifest
   rollback.

The milestone ends at `DATA-PLANE-1 = READY_FOR_ACCEPTANCE`; it must not be
marked `SEALED` by the implementation agent and must stop before the separate
implementation milestone.

# 2H. DATA-PLANE-2 Acceptance

`DATA-PLANE-2 — Production Deployment Verification` has independent final
acceptance and is recorded as `SEALED / DEPLOYED / ACCEPTANCE PASS`.

The durable evidence is PR #123 merged at
`8e432d84f5c4d68bd25fb32fb31c3d55a7b6e651`, production workflow run
`33294381128` with SUCCESS, `runtime_data_snapshot.status=READY`, `1778`
records, dataset SHA-256
`48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2`,
durability gate PASS, write-back SUCCESS, and Pages SUCCESS. Publisher live
validation remains `DEFERRED / NON_BLOCKING`; licensing remains
`LICENSING_REVIEW_REQUIRED`; the workflow item is
`NON_SECRET_LOG_HYGIENE_DEBT`. PR #120 remains OPEN / UNMERGED.

# 2I. PRED-TRUST-1 Acceptance

`PRED-TRUST-1 — Unique-Match Prediction Integrity & Multi-Market Quality
Audit` may be marked by Codex only as `READY_FOR_ACCEPTANCE`. Independent
acceptance must verify:

1. The audit is pinned to the accepted production write-back and uses one
   final legal pre-kickoff prematch version per unique match without deleting
   frozen files or rewriting the prospective ledger.
2. Pilot, excluded, post-kickoff, illegal timestamp, superseded, and
   non-selected duplicate versions are excluded from evaluation.
3. Every health duplicate group is classified A/B/C/D, with the unique
   affected-match count and real immutable/frozen violation result recorded.
4. Current-day and historical score distributions, lambda quantiles/buckets,
   1X2/BTTS/totals cross-market statistics, and verified 90-minute prospective
   metrics include explicit sample sizes.
5. The health-gate comparison includes random, empirical actual-score,
   Champion time-window, and competition strata, but does not modify the
   `87.5%` gate.
6. The result records the root-cause ranking and exactly one next milestone;
   no model, Champion, provider, identity, frozen prediction, ledger, monitor,
   or health-gate change is part of this audit.
7. Focused tests and the complete relevant test suite pass, and the audit PR
   body contains the required evidence sections and STOP state.

The audit artifact is
`data/prediction_quality/pred_trust_1/audit_2026-08-30.json`; the human report
is `docs/prediction-quality/PRED-TRUST-1_FINAL_REPORT.md`.

Independent acceptance result: `PRED-TRUST-1 = ACCEPTANCE PASS`. PR #125 was
merged at `1ec57af0b4bae7ca15cd41e2cdf4e578a21f7d89` after the accepted
write-back and audit pins were rechecked.

# 2J. PRED-TRUST-2 Acceptance

`PRED-TRUST-2 - Bounded Strength/Lambda Challenger Shootout` may be marked by
Codex only as `READY_FOR_ACCEPTANCE`. Independent acceptance must verify:

1. The replay uses only the accepted PRED-TRUST-1 pins: production run
   `33294381128`, write-back commit
   `73994d32fc148da49295a5bfef2e1e42e042a22e`, `217` unique final legal
   prematch matches, and `181` verified 90-minute results. Cohort IDs and
   frozen input snapshot hashes are locked in the manifest.
2. The candidate registry contains exactly Champion, Challenger A, and
   Challenger B. The two challengers are deterministic, pre-registered,
   structurally distinct, and use no fitted parameters, new provider, or
   post-match input.
3. The dependency map identifies football evidence, recent form, market
   baseline, strength representation, calibration, lambda generation, and
   the independent-Poisson score matrix boundary.
4. The result reports accuracy, Brier, and LogLoss for 1X2; exact-score Top1,
   Top3, actual-score probability, and NLL; BTTS and O/U 2.5 accuracy/Brier;
   calibration; lambda gap/total distributions; score diversity; and the
   probability right tail. A single machine trade-off table marks every
   challenger metric `BETTER`, `SAME`, or `WORSE` against Champion.
5. The replay has exactly one offline batch, reproduces the Champion lambda
   chain within the recorded tolerance, preserves the pinned cohort, and
   leaves frozen predictions, the prospective ledger, production Champion,
   shadow automation, health monitor/gate, providers, and frontend unchanged.
6. The final result is one of `PROMISING_FOR_SHADOW`,
   `NO_CHALLENGER_BEATS_CHAMPION`, or `INCONCLUSIVE`. This milestone does not
   promote or enable any challenger. For this result, the next sole milestone
   is upstream inputs / football evidence / market fusion; no lambda patch
   series continues.
7. Focused tests, syntax checks, diff checks, GitHub branch/commit/PR evidence,
   and the `REMOTE_DELIVERY_CHECK` all pass. The PR body includes the
   Champion-vs-A-vs-B summary, key metrics, lambda/concentration/right-tail
   result, blockers, tests/evidence, decision, next milestone, and STOP state.

The durable evidence is
`data/prediction_quality/pred_trust_2/pinned_cohort_manifest.json`,
`data/prediction_quality/pred_trust_2/replay_2026-08-30.json`, and
`docs/prediction-quality/PRED-TRUST-2_FINAL_REPORT.md`.

Independent acceptance result: `PRED-TRUST-2 = ACCEPTANCE PASS`. PR #126 was
merged at `81d70ad263d58d067237b88b0c332c284345518d` after the PRED-TRUST-2
pins and evidence were rechecked.

# 2K. PRED-TRUST-3 Acceptance

`PRED-TRUST-3 - Market-Side-Only Hybrid Knockout` may be marked by Codex only
as `READY_FOR_ACCEPTANCE`. Independent acceptance must verify:

1. The replay reads the accepted PRED-TRUST-2 artifact and preserves its
   production/write-back pins, `217` unique final legal prematch matches, and
   `181` verified 90-minute results. The PRED-TRUST-2 replay and cohort
   manifest hashes are recorded in the output.
2. The comparison contains exactly Champion, existing Challenger B, and one
   new deterministic Challenger C. Challenger A remains excluded after its
   prior `REJECT` result. C uses exactly `total=Champion total` and
   `share=market_share`, with the existing clamp, independent Poisson, `rho=0`,
   and score matrix.
3. The output includes 1X2 accuracy/Brier/LogLoss/ECE; exact-score Top1/Top3,
   NLL, and actual-score probability; BTTS and O/U 2.5 accuracy/Brier/ECE;
   lambda total/gap distributions; score diversity and margin shares; and
   right-tail probabilities for totals `>=4`, `>=5`, and `>=6`.
4. One machine trade-off table marks Existing B and C as `BETTER`, `SAME`, or
   `WORSE` against Champion. The experiment records the confounding boundary
   and does not claim a final causal root from B or C.
5. Exactly one offline batch is used, with no new data, parameter sweep,
   post-match parameter input, production/shadow enablement, frozen rewrite,
   ledger rewrite, health change, provider change, or frontend change.
6. The final result is exactly one of `MARKET_SIDE_FUSION_PROMISING` or
   `MARKET_SIDE_ONLY_NOT_SUFFICIENT`. For this result, the next sole milestone
   is `football evidence / team strength representation`; the market/lambda
   patch series stops and no Challenger is promoted.
7. Focused tests, syntax checks, diff checks, GitHub branch/commit/PR evidence,
   and `REMOTE_DELIVERY_CHECK` pass. The PR body contains Champion-vs-B-vs-C,
   key metrics, BTTS/O-U/right-tail status, blockers, decision, next milestone,
   and STOP state.

The durable evidence is
`data/prediction_quality/pred_trust_3/replay_2026-08-30.json` and
`docs/prediction-quality/PRED-TRUST-3_FINAL_REPORT.md`.
