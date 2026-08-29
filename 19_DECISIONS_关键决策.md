# 19_DECISIONS_关键决策.md

最后更新：2026-08-30
角色：记录不能因换对话 / 换 Codex 而重复推翻的关键决定。若新证据足以改变决定，必须新增 superseding decision，不得静默改历史。

# D-030 — Cloud Production Football Data Architecture Decision

Status: `SEALED / ACCEPTANCE PASS`

Decision: `B. PRIVATE_SNAPSHOT_STORE`.

The production runtime must obtain the same versioned private dataset snapshot
as local research/runtime, verify both artifact bytes and the existing logical
dataset digest/count, then open the existing DuckDB read-only under
`FOOTBALL_DATA_HOME`. The Git-tracked manifest is the pin and provenance
boundary; it must not contain restricted raw captures or a full public runtime
dataset.

The clean-runner audit against the latest checked `origin/main` is
`PARTIALLY_REPRODUCIBLE`: tracked legacy inputs repeatably produce 206 rows
with digest `0a1183aa11ae3c27c8b2081cae2f8776dfc50fbb35371ef48374e6f798d01a74`,
not the authoritative 1778 rows with digest
`48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2`. The
manifests pin source facts but do not carry all raw inputs; the current rebuild
command is offline migration, not a full source downloader. A bounded clean
source proof nevertheless rebuilt a temporary versioned Norway dataset and
made `500-1364199` pass authoritative recent-form input eligibility.

Option A remains the offline publisher/recovery builder when all pinned raw
inputs are present. Option C is overbuilt for a read-only 1778-row artifact;
Option D conflicts with the public-repository and Football-Data.co.uk terms
boundary. GitHub cache/artifact remains non-authoritative because of eviction
and retention. R2/S3-compatible vendor choice, snapshot upload, workflow
bootstrap and rollback implementation are explicitly deferred to a separate
milestone.

The full audit, comparison, cost/maintenance assessment, failure recovery,
refresh frequency and bootstrap contract are recorded in
`docs/data-foundation/DATA-PLANE-1_CLOUD_PRODUCTION_DATA_ARCHITECTURE.md`.

Independent acceptance recorded 1,778 authoritative rows with dataset SHA-256
`48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2`,
`PARTIALLY_REPRODUCIBLE` clean-runner behavior, and the clean Norway proof for
`500-1364199` with 10 pre-kickoff authoritative recent-form records. PR #121
merged to `main` at `963f36e7d00e16560fbdcd571dc20415437afa2b`; PR #120 remains
OPEN and unmerged. This acceptance record does not alter the
`B. PRIVATE_SNAPSHOT_STORE` architecture decision.

# D-028 - Daily prediction availability closure

Status: `LOCKED FOR PRED-AVAIL-1`

BASE may reuse an existing immutable historical-result store as a recent-form
source only through one generic exact-identity route. The route must filter
eligible pre-kickoff records, enforce the existing recency window, preserve
source/dataset provenance, and feed the existing four-block recent-form
contract without changing Champion math. It runs after the existing prematch,
Nowscore, 500 deep, and reviewed-cache paths.

There is no unvalidated market-only fallback: market-only remains metadata-only
and no DEGRADED production prediction is enabled. The 2026-08-30 bounded replay
moves availability from 1/25 to 2/25; the remaining 23 rows stay
identity/source/history blocked. The production automatic prediction, market,
prospective, dashboard, runtime, frozen, and historical-state artifacts remain
unchanged. PRED-AVAIL-1 ends at `READY_FOR_ACCEPTANCE`; independent acceptance
is required before any live refresh. IDENTITY_BACKLOG is
`NON_BLOCKING / ON_DEMAND`; ID-AUTO-2 does not start.

# D-027 - League-agnostic deterministic team identity resolution

Status: `LOCKED FOR ID-AUTO-1`

Identity resolution uses one reusable registry and one competition-scoped exact
ladder: stable provider ID, reviewed canonical/provider crosswalk, fixture
canonical ID, competition-constrained exact normalized name, then
competition-constrained reviewed alias. Only a unique candidate may be
`AUTO_RESOLVED`; multiple candidates are `AMBIGUOUS` and unresolved evidence
stays fail-closed. Existing reviewed provider IDs are durable and reusable
across future fixtures. No fuzzy similarity, LLM guessing, transliteration,
kickoff proximity, cross-competition matching, manual per-fixture alias list,
new provider, or league-specific resolver is permitted. Identity status gates
only historical challenger eligibility; the existing Champion stays fail-open.
Japan J1 and Spain La Liga are recorded for a generic import path only; no
league-specific importer is started.

# D-026 - League-agnostic historical coverage foundation

Status: `LOCKED FOR HC-AUTO-1`

The product must route daily fixtures through one manifest/adapter-driven
coverage registry and exact-only gate. The gate returns `SUPPORTED`,
`DEGRADED`, or `UNSUPPORTED` with auditable reason codes. Coverage gaps must
never block other fixtures or the current Champion; insufficient history must
turn off only the historical challenger metadata. The first source priority is
existing free, stable, reproducible adapters. New providers and
country-specific adapters are outside this milestone. Champion mathematics,
frozen predictions, prospective records, Sweden/DC research and paid sources
remain unchanged. HC-AUTO-1 ends at `READY_FOR_ACCEPTANCE`; HC-AUTO-2 does not
start automatically.

Acceptance record: independent acceptance passed HC-AUTO-1. PR #117 is merged
to `main` at `7680c57475c907ba87cf40c9c1a3d1d48543edb1`, with the latest
automatic-run state preserved; HC-AUTO-1 is `SEALED / ACCEPTANCE PASS`.

# D-025 ? Sweden / Dixon-Coles final closeout

Status: `LOCKED FOR FE-SE-DC-CLOSE`

FE-SE-HIST-1 is accepted and sealed after PR #115 merged to main. The final Sweden/DC experiment must reuse the FE-DC-1 fixed configuration and the exact old 103 target IDs, comparing the old 1554-row history with the complete 1778-row history. No rho, half-life, attack/defense, optimizer, score-grid, or fallback changes are permitted.

The recorded run found 7 model-specific fixed-optimizer non-convergence rows in the new complete-history replay, leaving 96 targets with both models. Because this blocks a complete apples-to-apples 103-row evaluation, the verdict is locked as `INCONCLUSIVE`; partial metrics are diagnostic only and do not justify promotion or further tuning.

This closes `SWEDEN_SPECIFIC_FURTHER_TUNING`. PR #114 remains OPEN and unmerged. Champion, production prediction, frozen prediction, user prediction surface, providers, and other leagues remain unchanged. The next candidate is only `League-Agnostic Historical Coverage / Automatic Coverage Gate`, without implementation in this task.
# D-024 — Sweden Historical Completeness 采用 bounded authoritative closure

状态：LOCKED FOR FE-SE-HIST-1

FE-DC-1 的独立验收确认工程/研究实验 PASS，但 Dixon-Coles `NOT_PROMOTABLE`；PR #114 保留为 research evidence，暂不 merge。新的上游数据 closure 只针对 `competition:sweden-allsvenskan`：

- 使用现有 Football-Data.co.uk adapter、source contract 和免费稳定 SWE.csv；不新增 provider，不扩其他联赛；
- 2025 必须是完整 `240/240`，canonical identity 只能使用 reviewed deterministic exact mapping；
- source hash/timestamp/provenance 必须保留，duplicate/conflict 必须显式审计，事实冲突 fail closed；
- 2026 authoritative 结果本轮保持 `119`，不因当前来源已出现更多进行中结果而扩大范围；
- authoritative historical store 可在临时 DuckDB 中从既有记录和目标 source 重建，atomic replace，并保持可重复、无重复、非目标记录不变；
- 不修改 Champion、production prediction、frozen prediction、FE-DC-1 参数或任何 production model。closure 只服务 research/shadow，不能自动 promotion。

# D-001 — Prediction Universe 是当天 canonical schedule

状态：LOCKED

完整赛程更新 Universe。Filtered / single-match fetch 不得覆盖全天 Universe。

# D-002 — Frozen prediction immutable

状态：LOCKED

赛后只能追加 result / evaluation，不能改写赛前预测。

# D-003 — 足球业务时间使用 Asia/Shanghai

状态：LOCKED

# D-004 — 正式结果口径

状态：LOCKED

90 分钟 + 伤停补时，不含加时和点球。

# D-005 — Legacy Mapper 不再发展

状态：LOCKED

仅用于 historical compatibility。

# D-006 — Homepage Slice 1A 保持封版

状态：LOCKED UNTIL REAL PRODUCT EVIDENCE

# D-007 — P0 Workspace Auto-Update Recovery 已完成

状态：SEALED / DEPLOYED

# D-008 — Current exact-score selector 判定 FAIL

状态：LOCKED UNTIL NEW EVIDENCE

2026-08-15：FROZEN 23；21/23 unique score = 1-1；1X2 leader HOME 12 / AWAY 11 / DRAW 0。

# D-009 — 不直接启用 Outcome-conditioned MAP

状态：LOCKED UNTIL NEW PROSPECTIVE EVIDENCE

Formal 14：Exact Top1=0%，selection outcome=28.57%。

# D-010 — 不直接启用 Existing Scenario Challenger

状态：LOCKED UNTIL NEW PROSPECTIVE EVIDENCE

Freeze-time replay 有效，但 Formal 14：Exact Top1=0%，selection outcome=28.57%。

# D-011 — 不人工惩罚 1-1 / 平局

状态：LOCKED

禁止 1-1 penalty、draw penalty、每日 diversity quota、随机改比分。

# D-012 — 当前主问题进入 λ / team-strength 层

状态：LOCKED FOR CURRENT PROGRAM

问题不只是 selector，还包括 lambda compression。

# D-013 — PA-2 Challenger 只作为 Research / Shadow

状态：LOCKED

`opponent_adjusted_strength_poisson_v1` 尚未完成 production paired validation。

# D-014 — CA-1 当前暂停

状态：LOCKED UNTIL PREDICTION QUALITY GATE

禁止用高级自动分析包装已知存在结构问题的预测。

# D-015 — Canonical Identity 禁止 fuzzy 猜测

状态：LOCKED

允许 deterministic provider ID / canonical registry / exact unique alias。

# D-016 — Promotion 必须 prospective

状态：LOCKED

约 40–50 新 prospective 后才进入严肃 review；约 100+ 更成熟样本后才考虑 Champion promotion。

# D-017 — 数据覆盖按阶段治理

状态：LOCKED

不因少量缺口自动 provider hopping；历史赛事扩展按真实 blocker 定向进行。

# D-018 — 用户页面不暴露工程/AI术语

状态：LOCKED

# D-019 — 验收通过不等于已部署

状态：LOCKED

必须核 remote main、workflow、durable state、Pages、health。

# D-020 — Codex 不得自行 SEALED

状态：LOCKED

完成任务只能标记 READY_FOR_ACCEPTANCE。

# D-021 — 正式交付在仓库外

状态：LOCKED

`D:\MyProject\_deliveries\football-betting-oneshot\`

# D-022 — 默认不占用用户电脑前台

状态：LOCKED

优先 CLI / headless / scripts / worktree / CI。

# D-023 — 重大模块与 build-vs-buy 必须主动做市场/工具雷达

状态：LOCKED

项目外部已有持续运行的每日市场/工具雷达，持续到用户暂停；雷达只负责发现与提供证据，不得直接改动 Champion、生产模型或其他生产状态。

任何重大模块或 build-vs-buy 决策，必须先做主动的 landscape scan，不得采用“用户找到一个候选 → 代理只研究该候选 → 沿近邻线索停止”的反应式流程。扫描至少覆盖直接竞品、替代方案、相邻类别、开源项目、国内外商业工具/API、上下游组件、近期发布或更新的选项，以及现实可行的低成本组合。

发现必须迭代扩展：每个有希望的结果都成为新的搜索种子，继续查找其替代品、竞品、fork、依赖、相似项目和不同解决类别。必须维护比较 shortlist，并比较适配度、质量、成本、许可证、数据合法性与可持续性、维护健康度、集成/迁移成本和锁定风险，明确选择直接使用、fork、改造、借鉴或拒绝。

对当前自研模块必须追问“如果今天从零开始，还会自己构建吗？”若答案为否，须定义替代方案和最小验证实验/替换门槛。新发现本身不是架构变更理由；替换必须有明确预期收益阈值和有界实验。与项目实质相关的研究结果应反馈到决策和路线图，但不得绕过 Champion、production、acceptance 或 promotion 既有门禁。只记录有持久价值的新发现/变化，避免重复每日噪声。

# Current Facts — 不是永久 Decision

以下未来可随新 artifact 更新：

- production Champion：`recent_form_market_calibrated_poisson_v2`
- calibration artifact 当前 `shadow_only / active=false`
- current production `rho=0.0`
- PA-2 historical Challenger Brier/LogLoss 优于 uniform，但 exact-score 1-1 仍过度集中。
