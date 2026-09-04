# 15_PROJECT_STATUS_项目状态.md

最后更新：2026-09-04
角色：**主仓库当前状态投影**。只保留今天仍成立、会影响当前决策的事实；不保存 milestone 流水账。

长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

## 1. 产品定位

Football Betting OneShot 是面向中国用户的足球信息 + 市场信息 + **多玩法赛前预测** + 可审计验证的决策支持产品。

核心用户价值：提高用户真正关心玩法的预测命中率与概率质量；Trust / Freeze / Calibration / Benchmark 负责证明成绩真实，不替代预测能力。

长期 Tier-A 中国竞彩目标：

- 胜平负；
- 让球胜平负；
- 比分（raw score distribution + official score buckets）；
- 总进球 0–7+；
- 半全场（需独立 first-half truth/model lane）。

O/U、BTTS、Asian/common handicap 等继续作为重要 Tier-B 市场。

产品不是彩票交易、代购、出票、充值、自动下注或官方彩票服务。

---

## 2. 当前成熟度

- Whole product：`LEVEL 4A — ENGINEERING CLOSED-BETA READY / MULTI-MARKET-EVALUATION GAP / PUBLIC LAUNCH NOT READY`
- Public-launch umbrella：`PUBLIC-LAUNCH-TRUST`
- 当前最大技术/产品发动机：`MULTI-MARKET-PREDICTION-QUALITY`
- Exact Score：仍是最大已知单项技术难题，但不再代表全部模型质量。
- Product/UI：Homepage + Match Detail 已存在；G5 functional/product gate 已过。
- Production foundation：Universe、freeze、90m result、prospective ledger、automation、Pages 已建立。

当前最重要的新缺口不是再做 Trust UI，而是：**其它玩法没有和 Exact Score 同等级的 prospective scorecard / baseline / coverage / failure map。**

---

## 3. 当前 Prediction Truth

### Champion / Challenger

- Champion=`recent_form_market_calibrated_poisson_v2`
- Challenger C=`market_side_only_hybrid / shadow-only`
- `auto_promote=false`
- `one football match = one observation`

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

## 4. Multi-Market Quality Contract

禁止一个跨玩法 blended “overall accuracy”。

每个玩法至少独立报告：

- full-coverage Top1 hit rate；
- served hit rate；
- served coverage / abstain rate；
- same-market baseline；
- delta vs baseline；
- proper score；
- calibration / ECE（样本允许时）；
- sample / uncertainty；
- competition / chronology stability；
- forecast horizon / freeze lead-time。

Exact Score 额外报告 Top1/3/5、Score NLL、concentration/entropy。

命中率是核心指标之一，但不能脱离 coverage；精选越少越容易抬高命中率，因此必须同时看 risk-coverage。

---

## 5. Model Architecture / Feature Truth

长期优先结构：

`shared football/market features → authoritative FT joint goal state → coherent FT markets → market-specific calibration/head when prospective evidence proves gain`

full-time score state 应尽量数学一致地支持 1X2、比分、总进球、O/U、BTTS、handicap 等。

但不再规定“一套模型必须对所有玩法最优”。如果专门 1X2 / Goals / BTTS / handicap head 在 fixed + prospective evaluation 中确有增益，可以独立存在。

任何 xG、阵容/球员、伤停、weather、travel/rest、GNN/embedding 等 rich feature 必须先过 `Feature Incremental Value Gate`：同一比赛、同一赛前信息截止、paired control、chronological holdout，证明相对 Champion / same-time strong market baseline 有增量。

半场/HTFT 必须先有 first-half truth/evaluation；不得机械 `90m lambda / 2`。

---

## 6. Forecast Horizon / Class-Balance Truth

预测时点是正式评价维度：T-24h、T-6h、T-60m 等不能混成一个成绩。

- 先审真实 `minutes_to_kickoff_at_freeze` 分布，再定义 horizon bins；
- 同一比赛不同 horizon 是 paired repeated forecasts，不是多场独立样本；
- 早期 forecast 优先与同一时点或更早 market baseline 比；closing market 单独作为 late-information benchmark。

1X2 不能只看 overall accuracy。长期至少检查 Home/Draw/Away predicted mix、confusion matrix、per-class recall、Draw recall、multiclass proper score / RPS、class-wise calibration（样本允许时），防止“永远猜热门/几乎不猜平局”伪造高准确率。

---

## 7. Segmented Serving

正式 serving 按：

`Market × Competition Support × Forecast Horizon × Evidence Quality × Prediction Quality`

Competition：`SUPPORTED / LIMITED / EXPERIMENTAL / UNSUPPORTED`

Evidence：`FULL / PARTIAL / INSUFFICIENT`

Serving：`NORMAL / CAUTION / DEGRADED / ABSTAIN`

一个玩法 DEGRADED 不得拖累其它玩法；其它玩法好不得替它背书。

任何 user-facing confidence 必须可回到 prospective calibration / reliability / sample uncertainty；否则不显示主观高/中/低。

---

## 8. External Correct-Score Benchmark / Current Execution

Issue #178 / PR #179 accepted：60 future candidates / 60 kickoff overlap / 0 exact identity / 0 correct-score probe，decision=`IDENTITY_MAPPING_NOT_READY`。

`0 exact identity` 不等于 provider score-market coverage=0。

Current bounded execution：Issue #180 `EXACT-SCORE-REEP-IDENTITY-BRIDGE-PREFLIGHT-1`。

#180 仍属于 Data / Identity / Rights lane；本次 Roadmap correction 不取消它。完成后必须回项目级 Gate，不自动继续 identity/provider 子树。

---

## 9. Post-#180 Highest Candidate

当前最高信息价值候选：

`MULTI-MARKET-PREDICTION-COVERAGE-AND-EVALUATION-GAP-AUDIT`

先只读查清：

- current frozen state 已能推导哪些玩法；
- current result truth 已能结算哪些玩法；
- 各玩法 current prospective hit rate / coverage / proper score / baseline；
- actual freeze lead-time distribution 与 horizon-specific performance；
- 1X2 Home/Draw/Away class-balance diagnostics；
- 官方竞彩让球、总进球、比分桶、HTFT 的 prematch/settlement truth 缺口；
- rich-feature coverage 与 potential ablation surface；
- strongest / weakest market；
- 哪些是 evaluation gap，哪些才是真正 model-quality gap。

这不是预授权 Issue；#180 完成后仍需完整 Research-Backed Project Gate。

---

## 10. 当前 Product Lanes

| Lane | 状态 |
|---|---|
| Multi-Market Prediction Quality | `CURRENT / TECHNICAL P0` |
| Prediction Proof / Trust / Serving | `CURRENT / P0` |
| Data / Identity / Rights | `CURRENT / P0 FOUNDATION` |
| User Decision Product / Trust Center | `CURRENT PRODUCT LANE` |
| Operations / Reliability | `REQUIRED BEFORE PUBLIC LAUNCH` |
| Closed Beta / User Validation | `NEXT PRODUCT MATURITY GATE` |
| Compliance / Commercial | `REQUIRED BEFORE PUBLIC COMMERCIALIZATION` |
| Distribution / Business Model | `DISCOVERY AFTER BETA SIGNAL` |
| Advanced Model R&D | `DEMAND-TRIGGERED BY PER-MARKET FAILURE` |

---

## 11. Anti-Rollback

- Prediction Quality 是发动机；Trust 是证明层，不能再次倒置。
- 不用跨玩法总命中率；不隐藏 coverage。
- 不用容易玩法给难玩法背书。
- 不只和 random baseline 比；优先 same-market / same-horizon strong baseline。
- 不让 overall 1X2 accuracy 掩盖 Draw/class collapse。
- 不把 closing market 的晚期信息优势写成同条件 baseline。
- 不假设 xG/阵容/球员/GNN 一定提升；先做 incremental-value ablation。
- Exact Score 仍是一等核心能力，但不绑架其它玩法。
- 核心市场集合不得永久缩窄为 `1X2/O-U/BTTS/Exact`。
- HTFT 在 first-half truth 未证明前不实现。
- frozen prematch history 不重写；postmatch truth 不进入赛前生成。
- C=`PROMISING_NOT_ESTABLISHED`，不得包装成稳定优于 Champion。
- technical accessibility != commercial reuse permission。
- bounded task 完成后不沿同 subtree 自动继续。

---

## 12. Historical Pointer

历史 milestone 只从 Git history、Issues/PR/Actions、`docs/*` evidence 与 Memory-Hub Research Assets 恢复。

**禁止再次把历史正文复制回当前状态文件。**
