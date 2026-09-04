# 17_NEXT_WORK_后续工作.md

最后更新：2026-09-04
角色：**只记录当前要做什么，以及为什么现在做。**

禁止保存历史 milestone、旧 STOP 状态、已关闭 Issue 正文。

长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

# 1. Product-Level Direction

状态：`MULTI-MARKET QUALITY + HISTORICAL FOOTBALL MEMORY REBASE LOCKED`

总门=`PUBLIC-LAUNCH-TRUST`。

发动机=`MULTI-MARKET-PREDICTION-QUALITY`。

两个长期 Job：

- `UNDERSTAND MATCH`
- `PREDICT / DECISION SUPPORT`

Exact Score / 比分 / 波胆是旗舰玩法，但不是唯一玩法。

核心关系：

`Historical Football Memory + Current Evidence + Same-Horizon Market → Prediction Quality → Prospective Proof → Serving/Product → Public Launch`

---

# 2. Current Bounded Execution

GitHub Issue #180：`EXACT-SCORE-REEP-IDENTITY-BRIDGE-PREFLIGHT-1`

Lane：`Data / Identity / Rights`。

目标：验证 current Reep v1 能否 deterministic 地桥接 FBOS 中文球队与 The Odds API 英文球队；只有身份成立后才 bounded probe `correct_score`。

边界：future-only / exact fail-closed / no fuzzy / no LLM translation / no bulk manual alias / no model or serving change / research-only PR。

**#180 保持不变。完成后无论 PASS/FAIL，都必须回 Project Gate，不自动继续 identity/provider 子树。**

---

# 3. Background Work

Challenger C 自然 prospective accumulation。

Accepted：`56 verified unique / PROMISING_NOT_ESTABLISHED / shadow-only`。

- 不调 C；
- 不扫参数；
- 不因少量新样本机械 review；
- >=100 才进入 Promotion Review Ready at most；
- 不自动 Promotion。

---

# 4. Post-#180 Highest-Value Candidate — 不是预授权任务

## `MULTI-MARKET-PREDICTION-COVERAGE-AND-EVALUATION-GAP-AUDIT`

当前研究排序：`HIGHEST`。

必须是**只读全局审计**，一次形成四张地图。

### A. Prediction Scorecard Map

1. 1X2 / O-U / BTTS / Exact 当前 full-coverage hit rate；
2. 若已有 serving，served hit rate + coverage / abstain；
3. proper score / calibration / CI；
4. actual freeze lead-time 与 horizon-specific scorecard；
5. 1X2 Home/Draw/Away mix、confusion、per-class recall、Draw recall；
6. competition / regime / early-season slices；
7. strongest / weakest market。

### B. Truth / Projection Map

1. current FT joint score state 已能数学一致推导哪些玩法；
2. current result truth 已能合法结算哪些玩法；
3. JC 0–7+ / official score buckets 是否只是 projection/evaluation gap；
4. official JC handicap line 是否已有合法 frozen truth；
5. HTFT 是 raw source 已有 HT 但没进 contract，还是 source 根本缺 HT truth；
6. 哪些缺口不需要新模型。

### C. Historical Football Memory / Training Corpus Map

1. current historical real-match count by competition × season × team；
2. regulation-90m semantics / extra-time contamination；
3. HT coverage；
4. canonical team/competition identity continuity；
5. existing OpenFootball CC0 pilot 的可扩范围；
6. 其它 rights-clear corpus 的实际增量与 license boundary；
7. point-in-time replay readiness；
8. promoted/new/cold-start teams 与 sparse leagues 的 pooling need；
9. current Champion 是否真正使用长期 team state；
10. historical market/odds 的 timepoint / rights / coverage。

### D. Baseline / Model-Bottleneck Map

1. Exact common-score / competition-mode baseline；
2. simple leakage-safe historical dynamic team-strength baseline；
3. same-market / same-horizon baseline；
4. market-implied score MAP where legal；
5. Football-only / Market-only / Fusion；
6. Champion / C；
7. current `_select_primary()` 是否进入用户 surface、是否已有 evidence；
8. rich-feature ablation surfaces；
9. 最终把每个 failure 分类为：`MODEL / TRAINING-CORPUS / DATA / IDENTITY / TRUTH / PROJECTION / EVALUATION / RIGHTS / PRODUCT`。

目的：

> **先查清“哪里不准、为什么不准、是不是样本/真相/产品缺口”，再决定要不要造模型以及造哪一种。**

---

# 5. If Historical Football Memory Becomes Highest-Value Route — 仍需 Gate

若上面审计证明历史 Football Memory 是主要瓶颈，候选最短实验梯子：

`historical corpus truth/rights`
`→ simple leakage-safe dynamic team-strength baseline`
`→ hierarchical/partial pooling`
`→ same-horizon market prior / implied score matrix`
`→ football + market residual/fusion`
`→ Exact Score distribution-family experiment only if residual evidence requires`
`→ enriched xG/lineup/player only if incremental`

不得一口气做完。

---

# 6. Exact Score Flagship Questions

后续任何技术路线都必须回答它对波胆究竟增加什么：

- strict Top1 / Top3 / Top5；
- Score NLL；
- actual-score rank；
- Top-k predicted mass vs observed coverage；
- common-score / league-mode baseline；
- market-implied score MAP / direct correct-score baseline（可得时）；
- 是否只让比分“看起来合理”却没有提高 strict future metrics。

近似命中不能冒充 Exact hit。

---

# 7. Parallel High-Value Candidates

完成 #180 后仍由 Project Gate 排序，不机械执行：

- Closed Beta Measurement Minimum；
- Data Rights / Source Commercial Inventory；
- Operations Release-Readiness Audit；
- User Decision / Exact Score product-surface audit。

New Model / New Market Implementation 默认排在 gap audit 后。

---

# 8. Explicitly Not Next By Default

- Challenger E；
- lambda/rho/selector 局部美化；
- 为显著性调 C；
- global recency/half-life scan；
- friendlies weighting；
- provider hopping / bulk alias；
- synthetic/Monte-Carlo 冒充新增真实样本；
- 大历史库不分年代/赛事/90m semantics 直接训练；
- closing market 给早期预测当 equal-information baseline；
- 只看 overall 1X2 accuracy；
- 因“高级”直接接 xG/player/GNN/LLM；
- HTFT 用 90m lambda/2；
- generic news/live-score/community expansion；
- EV/stake/portfolio 先于 probability trust。

---

# 9. Completion Rule

Founder 回复“已完成”时：

`Delta acceptance → Canonical Evolution Gate → 必要 Research Gate → route comparison → unique ACTIVE → self-contained Issue → Memory-Hub durable update → short Codex prompt`

如果事实推翻 Roadmap 假设，先改 Roadmap。

---

# 10. Historical Pointer

旧 Next Work 从 Git history、Issues/PR/Actions、`docs/*` evidence 与 Memory-Hub 恢复。

**不得复制回当前文件。**
