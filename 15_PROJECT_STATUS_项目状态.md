# 15_PROJECT_STATUS_项目状态.md

最后更新：2026-09-04
角色：**主仓库当前状态投影**。只保留今天仍成立、会影响当前决策的事实；不保存 milestone 流水账。

长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

## 1. 产品定位

Football Betting OneShot 同时服务两个长期 Job：

1. **Understand Match**：帮助想了解赛事的人理解强弱、节奏、得分路径、证据、市场冲突与不确定性；
2. **Predict / Decision Support**：为有合法竞彩足球或其它足球投注决策需求的用户提供更高质量、可审计的多玩法赛前预测。

核心用户价值：提高用户真正关心玩法的预测命中率与概率质量；Trust / Freeze / Calibration / Benchmark 负责证明成绩真实，不替代预测能力。

**Exact Score / 比分 / 波胆是旗舰一级玩法**，需要最深的模型、概率分布和验证，但不是唯一玩法。

长期 Tier-A 中国竞彩目标：胜平负、让球胜平负、比分（raw + official buckets）、总进球 0–7+、半全场（需 first-half truth/model lane）。

O/U、BTTS、Asian/common handicap 等继续作为重要 Tier-B 市场。

产品不是彩票交易、代购、出票、充值、自动下注或官方彩票服务。

---

## 2. 当前成熟度

- Whole product：`LEVEL 4A — ENGINEERING CLOSED-BETA READY / MULTI-MARKET + HISTORICAL FOOTBALL MEMORY EVALUATION GAP / PUBLIC LAUNCH NOT READY`
- Public-launch umbrella：`PUBLIC-LAUNCH-TRUST`
- 当前技术/产品发动机：`MULTI-MARKET-PREDICTION-QUALITY`
- Exact Score：旗舰玩法，也是最大已知单项技术难题之一，但不代表全部模型质量。
- Product/UI：Homepage + Match Detail 已存在；G5 functional/product gate 已过。
- Production foundation：Universe、freeze、90m result、prospective ledger、automation、Pages 已建立。
- Historical infrastructure：已有 historical result ledger/samples、competition registries 与 OpenFootball CC0 pilot；不是 greenfield。

当前最大的上游新缺口有两个：

1. **其它玩法没有和 Exact Score 同等级的 prospective scorecard / baseline / coverage / failure map；**
2. **当前 Champion Football-side 主要依赖短 recent-form actual goals + market，长期 point-in-time team/league Football Memory 的训练价值尚未建立。**

---

## 3. 当前 Prediction Truth

### Champion / Challenger

- Champion=`recent_form_market_calibrated_poisson_v2`
- Challenger C=`market_side_only_hybrid / shadow-only`
- `auto_promote=false`
- `one football match = one independent observation`

### C accepted checkpoint

- eligible unique=`80`
- verified unique=`56`
- unmatched=`24`
- Exact Score NLL mean delta `C - Champion=-0.026121699`
- IID bootstrap 95% CI=`[-0.098861103, 0.042938854]`
- chronology-aware block bootstrap 95% CI=`[-0.119570177, 0.062407291]`
- decision=`C_SIGNAL_PROMISING_NOT_ESTABLISHED`

C 继续自然积累到 >=100；禁止为显著性调参或机械反复 review。

---

## 4. Training Sample Truth

训练样本和正式证明样本是不同证据层：

### Historical Training / Research Corpus

可以通过合法、真实、时间安全的历史比赛扩张，用于 team/league strength、attack/defence、score structure、chronological holdout。

### Historical Market Research Corpus

历史赔率/盘口单独治理 rights 与 collection time，用于 research-only same-market baseline；不能默认成为 production input。

### Prospective Trust Ledger

只能由未来赛前冻结后的真实比赛逐场增加，用于 Promotion / serving / public claims。

历史增加 10,000 场不能把 56 场 prospective 写成 10,056；bootstrap、Monte Carlo、synthetic rows、forecast versions 也不能创造独立真实比赛。

---

## 5. Multi-Market Quality Contract

禁止跨玩法 blended “overall accuracy”。

每个玩法至少独立报告 full-coverage hit rate、served hit rate、coverage/abstain、same-market/same-horizon baseline、delta、proper score、calibration、sample/CI、competition/regime、chronology、forecast horizon。

1X2 额外审 predicted class mix / Draw recall / confusion matrix。

Exact Score 额外审：Top1/3/5、Score NLL、actual-score rank、concentration/entropy、Top-k predicted mass vs observed coverage，以及 common-score / competition-mode / historical-strength / market-implied baselines。

严格波胆只有双方 90m 进球完全一致才算 hit；近似比分只作结构诊断。

---

## 6. Historical Football Memory / Model Architecture Truth

当前 Champion 的 Football-side 主要从当前 source snapshot 读取近期主客场/整体实际进失球，与当前 1X2/大小球市场融合形成 λ；它不是大历史训练的动态球队强度模型。

长期候选结构：

`Global/Competition Prior → League/Season/Regime → Dynamic Point-in-Time Team Attack/Defence → Current Evidence + Same-Horizon Market Prior → Core Joint Goal State → Per-Market Head if independently justified`

关键边界：

- 先盘点/扩真实历史比分，不默认先扩算法复杂度；
- OpenFootball CC0 pilot 已存在，优先审它的 competition/season/identity/FT/HT 可扩性；
- sparse league / promoted / new team 优先 partial pooling / conservative prior；
- historical feature 必须 point-in-time replay，禁止 current Elo、season-end table、future result/squad 回填；
- 旧 small-cohort DC/rho rejection 只否决旧 applicability，不禁止大历史 dynamic attack/defence 新实验；
- xG、阵容/球员、伤停、weather、GNN/LLM 等 rich feature 仍需增量证明。

---

## 7. Forecast Horizon / Class-Balance / Serving

预测时点是正式评价维度：T-24h、T-6h、T-60m 不能混成同条件成绩；closing market 是 late-information benchmark。

1X2 不能只看 overall accuracy；长期检查 Home/Draw/Away predicted mix、confusion、per-class recall、Draw recall、proper score/calibration。

正式 serving：

`Market × Competition Support × Forecast Horizon × Evidence Quality × Prediction Quality`

Competition=`SUPPORTED/LIMITED/EXPERIMENTAL/UNSUPPORTED`

Evidence=`FULL/PARTIAL/INSUFFICIENT`

Serving=`NORMAL/CAUTION/DEGRADED/ABSTAIN`

任何 user-facing confidence 必须可回到 prospective calibration / reliability / sample uncertainty；否则展示状态与不确定性。

---

## 8. Current Routing Reality

Production core 已存在 `_select_primary()` 跨玩法选择逻辑候选：按概率/价格空间/模型相对市场差选唯一主维度并允许 abstain。

这不等于它已被验证成合格 Best-Market Router。

Post-#180 审计必须查：

- 它是否真正进入当前 user-facing surface；
- routing selection 是否被冻结/可追溯；
- 是否已有独立 holdout/prospective evidence；
- 是否因同一历史数据“选规则+证明规则”产生 selection bias。

---

## 9. External Correct-Score Benchmark / Current Execution

Issue #178 / PR #179 accepted：60 future candidates / 60 kickoff overlap / 0 exact identity / 0 correct-score probe，decision=`IDENTITY_MAPPING_NOT_READY`。

`0 exact identity` 不等于 provider score-market coverage=0。

Current bounded execution：Issue #180 `EXACT-SCORE-REEP-IDENTITY-BRIDGE-PREFLIGHT-1`。

#180 仍属于 Data / Identity / Rights lane；Roadmap rebase 不取消它。完成后必须回项目级 Gate，不自动继续 identity/provider 子树。

---

## 10. Post-#180 Highest Candidate

当前最高信息价值候选仍是只读：

`MULTI-MARKET-PREDICTION-COVERAGE-AND-EVALUATION-GAP-AUDIT`

但必须同时输出四张地图：

1. **Prediction Scorecard Map** — 各玩法 current hit/proper score/coverage/horizon/class balance；
2. **Truth / Projection Map** — JC Tier-A 哪些是 projection/evaluation/truth gap；
3. **Historical Football Memory / Training Corpus Map** — competition×season×team counts、90m/HT semantics、identity continuity、OpenFootball 扩容、point-in-time replay、pooling need、historical market rights/timepoint；
4. **Baseline / Model-Bottleneck Map** — common-score/competition-mode、historical team-strength、same-market/same-horizon、market-implied MAP、Football-only/Market-only/Fusion、Champion/C、现有 router surface，并分类 `MODEL / TRAINING-CORPUS / DATA / IDENTITY / TRUTH / PROJECTION / EVALUATION / RIGHTS / PRODUCT`。

这不是预授权 Issue；#180 完成后仍需完整 Research-Backed Project Gate。

---

## 11. 当前 Product Lanes

| Lane | 状态 |
|---|---|
| Historical Football Memory / Training Foundation | `CURRENT GAP TO AUDIT` |
| Multi-Market Prediction Quality | `CURRENT / TECHNICAL P0` |
| Prediction Proof / Trust / Serving | `CURRENT / P0` |
| Data / Identity / Rights | `CURRENT / P0 FOUNDATION` |
| User Decision Product / Trust Center | `CURRENT PRODUCT LANE` |
| Operations / Reliability | `REQUIRED BEFORE PUBLIC LAUNCH` |
| Closed Beta / User Validation | `NEXT PRODUCT MATURITY GATE` |
| Compliance / Commercial | `REQUIRED BEFORE PUBLIC COMMERCIALIZATION` |
| Distribution / Business Model | `DISCOVERY AFTER BETA SIGNAL` |
| Advanced Model R&D | `DEMAND-TRIGGERED BY MEASURED FAILURE` |

---

## 12. Anti-Rollback

- Prediction Quality 是发动机；Trust 是证明层。
- Understand Match 与 Predict/Decision Support 都是正式产品 Job；解释必须共享同一事实真相。
- Exact Score 是旗舰，但不绑架其它玩法。
- 历史训练样本 ≠ prospective proof；禁止 synthetic/version rows 扩样本。
- 不用跨玩法总命中率；不隐藏 coverage。
- 不只和 random baseline 比；优先 same-market/same-horizon strong baseline。
- 不让 overall 1X2 accuracy 掩盖 Draw/class collapse。
- 不把 closing market 的晚期信息优势写成同条件 baseline。
- 不假设 xG/阵容/球员/GNN/LLM 一定提升；先做 incremental-value ablation。
- historical state 必须 point-in-time；禁止泄漏。
- 核心市场不得永久缩成 `1X2/O-U/BTTS/Exact`。
- HTFT 在 first-half truth 未证明前不实现。
- frozen prematch history 不重写；postmatch truth 不进入赛前生成。
- C=`PROMISING_NOT_ESTABLISHED`，不得包装成稳定优于 Champion。
- technical accessibility != commercial reuse permission。
- bounded task 完成后不沿同 subtree 自动继续。

---

## 13. Historical Pointer

历史 milestone 只从 Git history、Issues/PR/Actions、`docs/*` evidence 与 Memory-Hub Research Assets 恢复。

**禁止再次把历史正文复制回当前状态文件。**
