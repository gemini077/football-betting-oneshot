# 17_NEXT_WORK_后续工作.md

最后更新：2026-08-30

# Current Sole Pointer

# DATA-PLANE-1 - Cloud Production Football Data Architecture Decision

Status: `READY_FOR_ACCEPTANCE`

Decision: `B. PRIVATE_SNAPSHOT_STORE`.

The clean-runner audit is `PARTIALLY_REPRODUCIBLE`: tracked inputs reproduce
206 rows/digest `0a1183aa11ae3c27c8b2081cae2f8776dfc50fbb35371ef48374e6f798d01a74`,
while the authoritative local store is 1778 rows/digest
`48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2`. The
bounded clean source proof makes `500-1364199` eligible through
`authoritative_historical_results`, but does not establish full-dataset
rebuildability or production deployment.

The decision document is
`docs/data-foundation/DATA-PLANE-1_CLOUD_PRODUCTION_DATA_ARCHITECTURE.md`.
Implementation is not started. The later implementation milestone must use a
private versioned snapshot, exact byte/logical digest verification, atomic
`FOOTBALL_DATA_HOME` bootstrap, read-only DuckDB access, immutable rollback and
last-known-good fallback. Source refresh must remain separate from prediction
runs.

STOP CONDITIONS:

- Keep `DATA-PLANE-1` at `READY_FOR_ACCEPTANCE` until independent acceptance.
- Do not provision R2/S3, Supabase or another database in this decision task.
- Do not add a full runtime dataset to the public repository.
- Do not start a workflow bootstrap, provider patch, PRED-AVAIL-3, ID-AUTO-2,
  Sweden/DC, PA-3, Champion promotion, model tuning or frontend work.
- Do not modify frozen predictions, prospective ledger, dashboard, runtime or
  Champion mathematics.
- Stop after the decision and evidence; implementation requires a new
  milestone.

# Historical execution record: PRED-AVAIL-1

## PRED-AVAIL-1 - Daily Prediction Availability Closure

Status: `READY_FOR_ACCEPTANCE`

The same frozen 25-fixture cohort is retained at
`data/football_data/pred_avail_1/baseline_2026-08-30.json`, with cohort SHA-256
`0cf4f106c34f183c3d61a81952f70e9c7f2525c0376a1e6eff74bb087e15cb8d`.
BEFORE: 1 FULL/frozen, 24 `MISSING_RECENT_FORM`, 0 prediction failures, and 0
blocked Champion jobs. AFTER bounded replay: 2 FULL, 0 DEGRADED, 23
`INSUFFICIENT_DATA` / `MISSING_RECENT_FORM`, 0 prediction failures, and 0
blocked Champion jobs. The released fixture is `500-1364199` through the
existing authoritative historical-result store route.

The 24-row root-cause audit shows 1 `HISTORY_EXISTS_BUT_NOT_USED` and 23
`IDENTITY_BLOCKED`. All 24 retain the contributing source-not-routed,
source-unavailable, and provider-mapping-missing causes. The route is generic;
no league-specific importer, alias work, fuzzy identity, synthetic evidence,
new provider, market-only fallback, Champion math change, or production-state
rewrite was used.

`HC-AUTO-1 = SEALED / ACCEPTANCE PASS` and `ID-AUTO-1 = SEALED / ACCEPTANCE PASS`
after independent acceptance. PR #118 merged to `main` at
`04a548416513865e4af4771603fb4369074ecd57`. `IDENTITY_BACKLOG = NON_BLOCKING /
ON_DEMAND`; ID-AUTO-2 is not started. Production automatic state is preserved;
the AFTER result is a bounded local replay, not a deployment claim.

STOP CONDITIONS:

- Leave PRED-AVAIL-1 at `READY_FOR_ACCEPTANCE` until independent acceptance.
- Do not start ID-AUTO-2, Sweden/DC, PA-3, Champion promotion, or model tuning.
- Do not modify frozen prediction, prospective ledger, or automatic market,
  dashboard, and runtime artifacts.
- After independent acceptance, return to Multi-Market Prediction Quality.

# Historical execution record: ID-AUTO-1

## ID-AUTO-1 - League-Agnostic Deterministic Team Identity Resolution

Status: `SEALED / ACCEPTANCE PASS`

HC-AUTO-1 closeout is recorded as `SEALED / ACCEPTANCE PASS` after independent
acceptance. PR #117 was merged to `main` at
`7680c57475c907ba87cf40c9c1a3d1d48543edb1`; latest automatic-run state was
preserved.

Previous closeout remains recorded: `FE-SE-HIST-1 = SEALED / ACCEPTANCE PASS`,
`FE-SE-DC-CLOSE = ACCEPTANCE PASS / CLOSED`, model verdict `INCONCLUSIVE`
because 7 of the original 103 fixed-config targets had optimizer fit failures,
and `SWEDEN_SPECIFIC_FURTHER_TUNING = CLOSED`. PR #114 remains OPEN and
unmerged. No Sweden/DC calculation is part of this milestone.

ID-AUTO-1 delivers a generic team identity contract for every canonical
competition: canonical team ID/name, competition scope, country, provider and
provider team ID/name, reviewed aliases, evidence, resolution method,
confidence class and ambiguity state.

The daily route remains:

`Prediction Universe -> coverage registry/gate -> BASE job ledger -> existing Champion`

Identity resolution is exact-only and follows stable provider ID, reviewed
provider crosswalk, fixture canonical ID, competition exact normalized name,
then competition-scoped reviewed alias. Every row retains a current Champion
job; historical challenger eligibility is turned off when the coverage gate is
not `SUPPORTED`. Ambiguous and unresolved rows never block other fixtures.

ID-AUTO-1 evidence:

- `scripts/football_data/identity_registry.py`
- `scripts/football_data/run_id_auto_1.py`
- `data/football_data/id_auto_1/identity_registry.json`
- `data/football_data/id_auto_1/daily_fixture_audit.json`
- `data/football_data/id_auto_1/identity_resolution_backlog.json`
- `data/football_data/id_auto_1/provider_id_reuse_evidence.json`
- `docs/data-foundation/ID-AUTO-1_IDENTITY_RESOLUTION.md`
- focused identity, gate and audit-artifact tests

The same real 66-fixture snapshots were audited as one mixed fixture set.
BEFORE: 1 `SUPPORTED`, 65 `UNSUPPORTED`, 0 blocked Champion jobs. AFTER:
2 `SUPPORTED`, 0 `DEGRADED`, 64 `UNSUPPORTED`, 2 fully auto-resolved fixtures,
7 partial fixtures, 57 unresolved fixtures, 0 ambiguous fixtures, and 0 blocked
Champion jobs. Existing free/reproducible sources and reviewed evidence were
reused; no manual per-fixture alias work, new provider, country-specific
adapter, paid source, model change, frozen prediction change, or
historical-store rebuild was introduced.

Japan J1 and Spain La Liga are recorded as `READY_FOR_GENERIC_IMPORT` only;
their generic existing adapters were not executed in this milestone. The
remaining identity backlog is evidence for later scope, not a reason to start
a league-specific importer.

STOP CONDITIONS:

- Do not start ID-AUTO-2 automatically.
- Do not tune or calculate Sweden/Dixon-Coles, promote a Champion, or modify
  frozen/prospective records.
- Identity backlog is only recorded for a later separately scoped milestone.
- This historical execution record was independently accepted; ID-AUTO-1 is
  `SEALED / ACCEPTANCE PASS`. HC-AUTO-1 is also recorded as
  `SEALED / ACCEPTANCE PASS`.

# 历史执行记录（非当前指针）

`PA-2-R1-ID3 — Targeted Identity Persistence, Bounded History Closure & Prospective Pair Capture`

状态：HISTORICAL

本指针在本次 Governance Current-State Sync 提交后生效。ID2 evidence package/status 是 `READY_FOR_ACCEPTANCE / INDEPENDENT ACCEPTANCE PENDING`；PA-2-R1 model program overall 仍为 `OVERALL INCOMPLETE / TOO_SMALL_FOR_DECISION`，不是整体已验收。


# 1. 已完成，不再重跑

以下 DATA / ID / COV-SRC / ID2 工作已有真实 evidence，不得重新按陈旧 Formal 14 / pre-ID2 状态施工：

- DATA：shared authoritative baseline 已核验为 1,554 historical results / 160 team-strength snapshots；Europa v3 summary 的 staging 数字为 `record_count=2,153`、`eligible_count=1,559`、`excluded_count=594`，不代表 shared DB 已迁移；
- ID：deterministic bridge 已完成，formal eligible=9、excluded pilot=5，状态为 AVAILABLE=1、COMPETITION_UNSUPPORTED=6、HISTORY_UNAVAILABLE=1、IDENTITY_UNAVAILABLE=1；
- COV-SRC：来源、cutoff、provenance 与赛后/赛前语义已进入现有 evidence，不重跑 source coverage audit；
- ID2：same-match paired sample=1，`result_gate=PARTIAL_PAIRED_EVALUATION`，`verdict=TOO_SMALL_FOR_DECISION`；Champion 不变，Challenger shadow-only，CA-1 paused，PA-3 not started；
- 旧 `Formal 14` 只保留为历史 label；当前正式 cohort 使用 `formal eligible=9 + excluded pilot=5`。

# 2. ID3 最短执行路径

## A. Hearts–Benfica：先审语义，再决定是否补历史

- 现有两队 identity 已由官方 fixture/球队证据 deterministic solved；不要重复做 identity mapping；
- 先检查 Challenger 的历史窗口、recency 与 `min-history` 语义，确认 2/5 是哪一侧/哪一层 prior 门槛；
- 只有真实、pre-cutoff、同一 `UEFA Europa League` competition 的历史记录仍具统计意义时，才允许定向补充；禁止混入 Conference League，也禁止为了凑满 5 场纯补数量；
- 若历史窗口/recency 语义表明补更老样本不再有研究价值，立即停止该分支。

## B. 另外三个 Europa formal target：补 production-side deterministic identity

Pafos–Salzburg、Rangers–Jagiellonia、Anderlecht–PAOK 已有官方赛事 corroboration，但 production-side identity 仍不足以进入 paired。优先检查现有 Nowscore/500 structured snapshots 中的稳定 provider team IDs 与既有 crosswalk：

- 仅接受可复现的 provider ID、既有 canonical registry/crosswalk 或 competition-constrained exact unique alias；
- 不使用中文翻译、非唯一 kickoff time、fuzzy、LLM 或人工“看起来像”匹配；
- 目标不是增加 alias 数量，而是让真实 fixture 获得可审计、可复现的 production-side identity。

## C. Elfsborg：独立 secondary blocker

Elfsborg 继续保持 `IDENTITY_UNAVAILABLE`。没有新的 deterministic provider/crosswalk evidence 就停止，不 fuzzy、不借用未验证别名。

## D. Retrospective 与 prospective 分界

如果 2026-08-14 的 retrospective fixture 因 capture timing 或 identity 不能合法解锁，停止强行补旧比赛，转向 prospective pre-kickoff capture readiness。赛后抓到的 Europa source 必须标注为 post-match captured evidence，不能改写成 pre-match prospective evidence。

# 3. ID3 成功标准

满足以下任一项即可形成可验收进展：

1. 在完全相同 match IDs 上，真实 paired sample 增加；或
2. 关键 blocker 被 deterministic 关闭，并形成可执行、赛前冻结时可复现的 prospective pair-capture 路径。

“新增了多少 alias”或“凑到 5 场历史”本身不算成功。

# 4. 停止条件与硬边界

bounded history 检查没有新的同赛事、pre-cutoff 且统计上有意义的 prior；三场 Europa target 没有稳定 provider ID/crosswalk；Elfsborg 没有新的 deterministic identity；或 retrospective capture 无法满足赛前证据链时，停止历史扩展并等待 prospective pair capture。

不得在 ID3 中：

- 启动 PA-3、CA-1 或 Champion promotion；
- 修改 Champion、模型数学、预测、production/shared DB 或 frozen prediction；
- 扩新 provider、混入 Conference League、使用十年前无意义历史、重跑 DATA/ID/COV-SRC/ID2；
- 把任何 post-match source 当作 prospective evidence。

# 5. 完成状态

Codex 完成 ID3 后只能写：

`READY_FOR_ACCEPTANCE`

不得自行写 `SEALED`。
