## FE-DC-1 current pointer - 2026-08-29

`FE-DC-1 - Sweden League Dixon-Coles Baseline`

Status: `READY_FOR_ACCEPTANCE`

This is the current atomic milestone. It uses the complete authoritative Sweden Allsvenskan connected network with strict chronological held-out evaluation, a fixed pre-registered configuration, full score distributions, and an internal `rho=0` control. It remains research/shadow-only; it does not replace the Champion, modify frozen predictions, add a provider, or modify the shared historical database.

The FE-ID-BRIDGE-1 independent acceptance is treated as `PASS`. Only the durable identity/crosswalk evidence needed by FE-DC-1 is retained; PR #112 and stacked PR #113 audit packages are not merged wholesale.


# 17_NEXT_WORK_后续工作.md

最后更新：2026-08-28

# 当前唯一主线

## PRODUCT-RESET-R1 — Evidence Quality & Prospective Challenger Closure

状态：CURRENT

当前只做四件事：

1. **Production Champion 保持不变**：`recent_form_market_calibrated_poisson_v2` 继续 serving，未通过 Promotion Gate 不替换。
2. **收口现有方向 Challenger**：只使用既有 `market-direction-fusion-full-v1` Shadow；按 `match_key` 去重，每场只计一个合法赛前快照。小样本不得 promotion；禁止再做新的 recent-form weight sweep。
3. **Prospective 自然积累**：修复后的 Shadow pipeline 继续自然 capture / settle 新比赛；产品继续运行，不能停着等样本。
4. **下一研发方向提高 Football Evidence 质量**：本 bounded fusion 问题收口后，研究 Elo、dynamic attack-defense、rolling xG、lineup availability 等更强足球证据，而不是继续给低质量 recent goals 调权重。

停止条件：

- 不做 1:1 cosmetic patch；
- 不重复创建 market-direction Challenger；
- 不为补样本强挖旧历史；
- PA-2-R1 identity / history 只有在真实阻塞 current production / prospective 时才恢复。
角色：当前唯一执行指针。只描述“现在只做什么”。

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
