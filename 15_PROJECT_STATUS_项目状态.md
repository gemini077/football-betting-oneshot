# 15_PROJECT_STATUS_项目状态.md

最后更新：2026-09-04
角色：**主仓库中的当前状态投影**。只保留今天仍成立、会影响当前决策的事实；不保存 milestone 流水账。

长期 Canonical Source of Truth：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。
若本文件与最新可复现 production/runtime/research truth 或 Memory-Hub Canonical 冲突，以最新事实经 Canonical Evolution Gate 后的结论为准。

---

## 1. 产品定位

Football Betting OneShot 是面向中国用户的足球信息与赛前决策产品。

核心链路：

`比赛发现 → Canonical Identity → 足球证据 → 市场证据 → 概率预测 → 赛前冻结 → 用户解释 → 90m 结果 → Prospective Evaluation → Challenger → 用户决策`

核心输出：`1X2 / Exact Score / O-U / BTTS`。

产品是**分析与信息服务**，不是彩票交易、代购、出票、充值、自动下注或官方彩票机构服务。

---

## 2. 当前成熟度

- Whole product：`LEVEL 4 — CLOSED BETA READY / PUBLIC LAUNCH NOT READY`
- Product/UI：核心 Homepage + Match Detail 已存在；G5 functional/product gate 已通过，视觉 Excellence 非当前最大瓶颈。
- Production foundation：比赛发现、冻结、90m 结果、Prospective ledger、自动化、Pages/Workspace 等主链已建立。
- Prediction Trust：仍是当前最大技术 P0。
- Product-level Roadmap：正在执行 2026-09-04 rebase；**不得再把旧串行“模型→分析→产品”路线视为默认真理**。

---

## 3. 当前 Prediction Trust 真相

### Champion / Challenger

- Champion：`recent_form_market_calibrated_poisson_v2`
- Challenger C：`market_side_only_hybrid / shadow-only`
- C：`auto_promote=false`
- Promotion 统计单位：`one football match = one observation`

### Challenger C accepted checkpoint

Issue #176 / PR #177 accepted snapshot：

- eligible unique=`80`
- verified unique=`56`
- unmatched=`24`
- Exact Score NLL mean delta `C - Champion = -0.026121699`
- IID bootstrap 95% CI=`[-0.098861103, 0.042938854]`
- chronology-aware block bootstrap 95% CI=`[-0.119570177, 0.062407291]`
- decision=`C_SIGNAL_PROMISING_NOT_ESTABLISHED`

解释：C 的平均方向仍优于 Champion，但不确定区间跨 0，并存在时间段/联赛反向证据。

因此：

- `50–99 unique = CHECKPOINT / shadow-only`
- C 原样自然积累到 `>=100`
- 禁止为了显著性调 C、扫描参数或机械反复跑 review
- `>=100` 也只进入 `PROMOTION_REVIEW_READY`，不自动 Promotion

---

## 4. 当前 External Exact-Score Benchmark 真相

Issue #178 / PR #179 accepted snapshot：

- future FBOS candidates=`60`
- The Odds API soccer events discovered=`646`
- kickoff-overlap candidates=`60/60`
- exact event identities=`0`
- correct_score probes=`0`
- credits used=`0`
- decision=`IDENTITY_MAPPING_NOT_READY`

关键解释：

`0 exact identity` **不等于** `provider correct-score coverage = 0`。

60/60 在 kickoff 层面存在 provider 候选；当前失败点是 FBOS 中文球队名与 provider 英文球队名之间缺少可审计、确定性的 cross-source identity bridge，因此市场 coverage 尚未真正被测试。

---

## 5. 当前执行任务

GitHub Issue #180：

`EXACT-SCORE-REEP-IDENTITY-BRIDGE-PREFLIGHT-1`

定位：**Data / Identity / Rights lane 的 bounded research task**，不是整个产品 Roadmap 本身。

目标：验证 current Reep v1 exact/typed aliases + competition context 能否把 FBOS 中文球队与 The Odds API 英文球队确定性桥到同一 stable team ID，并在身份成立后 bounded probe `correct_score`。

硬边界：

- future-only
- fail closed
- no fuzzy / LLM translation / generated transliteration / result-based matching
- no bulk manual alias authoring
- no model / Champion / C / frozen truth / serving / promotion change

**#180 结束后必须回到项目级 Gate；不得自动沿 identity/provider 子树继续下钻。**

---

## 6. 当前产品级工作流（Roadmap Rebase 中）

当前项目不再用单一技术 Phase 串行推进。至少同时维护以下 lanes：

| Lane | 当前作用 |
|---|---|
| Prediction Trust | Exact Score、概率质量、C prospective maturation、外部 benchmark |
| User Trust / Product | 用户能否看懂“怎么看 / 为什么 / 多大把握 / 哪里会错” |
| Data / Identity / Rights | Canonical identity、跨源 bridge、数据许可与可替换性 |
| Operations / Reliability | unattended run、freshness、silent missing、monitor/fail-safe/rollback |
| User Validation | Closed Beta 真实使用、回访、理解与行为证据 |
| Compliance / Commercial | 中国市场宣传、收费、数据权利、交易边界 |
| Advanced Model R&D | 由明确 failure mode 触发；不是默认主干 |

Roadmap 的最终 lane priority / Public Launch gates 仍在本轮产品级审视中确认。

---

## 7. 仍生效的 Anti-Rollback

- frozen prematch history 不重写；postmatch truth 不得进入赛前生成。
- selector 不是历史 1-1 collapse 主因。
- Challenger D 已 REJECTED；不得调参复活。
- global recency half-life route 已 REJECTED；不得继续扫。
- current 61-match friendlies causal route 已 RETIRED；不得降低 sample/provenance gate 硬做。
- 旧 Sweden holdout 中简单 Dixon-Coles 未优于 rho=0；不得机械打开 rho。
- C=`PROMISING_NOT_ESTABLISHED`，不得包装成已证明稳定优于 Champion。
- Sporttery CRS target alignment 高，但自动化/商用 rights=`NOT_CLEARED`。
- external correct-score benchmark 即使成功也先是独立 benchmark，不自动成为模型输入。
- technical accessibility != commercial reuse permission。

---

## 8. 历史信息在哪里

本文件不再复制历史 milestone。

历史事实按用途读取：

- Git history：旧 `15_PROJECT_STATUS_项目状态.md` 全版本；
- `docs/data-foundation/`：数据/身份/生产证据；
- `docs/prediction-quality/`：预测质量与 Challenger 证据；
- `docs/model-governance/` / `docs/research/`：模型治理与研究；
- GitHub Issues / PR / Actions / artifacts：原始执行与验收证据；
- Memory-Hub `RESEARCH_ASSETS.md`：长期研究资产；
- Memory-Hub `CANONICAL.md`：当前项目驾驶舱。

**禁止为了“方便”再把这些历史正文复制回本文件。**
