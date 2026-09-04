# 16_ROADMAP_项目路线图.md

最后更新：2026-09-04
状态：`CLEAN V2 / MULTI-MARKET QUALITY + HISTORICAL FOOTBALL MEMORY REBASE`

角色：描述产品如何从当前状态走向**预测更强、赛事理解更好、可验证、可公开、可持续使用**。不保存历史 milestone。

长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

# 1. North Star

FBOS 同时服务两个 Job：

1. **Understand Match**：帮助用户理解这场球更可能怎么踢、为什么、哪里不确定；
2. **Prediction Decision Support**：在竞彩足球及其它合法足球投注决策中，提供更高质量、可验证的多玩法赛前预测。

其中 **Exact Score / 比分 / 波胆是旗舰玩法**，但不是唯一玩法。

核心关系：

`Historical Football Memory + Current Evidence + Same-Horizon Market`
`→ Multi-Market Prediction Quality`
`→ Prospective Proof / Trust`
`→ Selective Serving / Product`
`→ Public Launch`

Prediction Quality 是发动机；Trust / Freeze / Calibration / Benchmark 是证明系统；UI / Beta / Rights / Operations / Compliance 是交付系统。

---

# 2. Tier-A Market Universe

中国竞彩第一等目标：FT 1X2 / 胜平负、让球胜平负、Exact Score / 比分 / official score buckets、总进球 0–7+、HTFT / 半全场（先过 first-half truth gate）。

Tier-B：O/U、BTTS、Asian/common handicap、team totals、winning margin、double chance。

Mixed parlay 是 downstream composition，不是 model target。

---

# 3. Multi-Market Scorecard

禁止跨玩法 blended overall accuracy。

每个玩法：

`Full Hit Rate + Served Hit Rate + Coverage + Same-Market/Same-Horizon Baseline + Delta + Proper Score + Calibration + CI + Competition/Regime + Horizon + Stability`

1X2 额外审 Home/Draw/Away class mix、Draw recall、confusion matrix。

Exact Score 额外审 Top1/3/5、Score NLL、actual-score rank、concentration/entropy、Top-k expected-vs-observed coverage，以及 common-score / league-mode / historical-strength / market-implied baselines。

严格 Exact Score 只有双方 90m goal count 完全一致才算 hit。

---

# 4. Historical Training ≠ Prospective Proof

Historical Training Corpus 可以通过真实合法历史比赛大幅扩张，用于 team/league state、score distribution、chronological holdout。

Prospective Trust Ledger 只能未来逐场冻结后增长，用于 Promotion / serving / public claim。

历史 100,000 场不等于 prospective 多 100,000 场。Synthetic / bootstrap / Monte Carlo / version rows 不能制造真实独立比赛。

---

# 5. Historical Football Memory Lane | TECHNICAL FOUNDATION

当前 Champion 的 Football-side 主要是短 recent-form actual goals + market；长期 team-strength memory 明显不足。

候选长期结构：

`Global / Competition-Tier Prior → League / Season / Regime → Dynamic Point-in-Time Team Attack / Defence → Current Match Evidence + Same-Horizon Market Prior → Authoritative Joint Goal State`

优先原则：

1. 先盘点/扩真实历史比分，不先堆模型复杂度；
2. 优先复用现有 OpenFootball CC0 pilot 与 rights-clear source；
3. sparse league / promoted / new team 用 partial pooling / conservative prior；
4. 所有历史 state point-in-time replay，禁止 final Elo / season-end table / future info 回填；
5. large-history dynamic attack/defence 是新 applicability hypothesis，不被旧 61-match DC/rho rejection 自动否决；
6. historical odds/market corpus 与 result corpus 分开治理 rights/timepoint。

---

# 6. Model Architecture Lane

`Historical Football Memory + Current Match Evidence + Same-Horizon Market Prior → Core State Champion → coherent FT projections → Per-Market Serving Head/Calibrator only when evidence proves gain`

HTFT 使用独立 half-time truth/state。

Poisson / Dixon-Coles / bivariate / NB / ZIP / state-space / tree / boosting / ensemble / LLM reranker 都只是候选方法；模型名字没有优先权。

---

# 7. Market Prior / Baseline Lane

长期保留 Football-only / Market-only / Fusion。

Exact Score 重点研究：`de-vigged 1X2 + totals (+ handicap) → market-implied score matrix`，作为 strong prior/baseline，再测试 Football Memory 是否有 residual improvement。

这不复活 Challenger D；D 是旧数据状态下一个具体 lambda 机制，已经被 C 击败。

Direct correct-score market 只在 identity/rights 可用时作额外 benchmark。

---

# 8. Forecast Horizon / Feature / Class Gate

T-24h / T-6h / T-60m 不混成绩；closing market 只能作为 final-information benchmark。

xG、阵容、球员、伤停、天气、教练、GNN/LLM 等必须走 fixed ablation + chronological holdout + prospective path。

1X2 不允许 overall accuracy 掩盖“几乎永远猜热门 / 不猜平局”。

---

# 9. Segmented Serving / Router

正式 serving：`Market × Competition × Forecast Horizon × Evidence × Prediction Quality`，状态 NORMAL / CAUTION / DEGRADED / ABSTAIN。

未来“本场最稳观点”若自动选择，Router 本身就是 prediction policy，必须独立 holdout/prospective 验真。

当前 core 已存在跨玩法 `_select_primary()` 逻辑候选，因此后续审计必须查它是否进入 user-facing surface、是否有正式 evidence，不能假设 Router 还不存在。

---

# 10. Current Program

总门=`PUBLIC-LAUNCH-TRUST`；发动机=`MULTI-MARKET-PREDICTION-QUALITY`。

成熟度=`ENGINEERING CLOSED-BETA READY / MULTI-MARKET + HISTORICAL MEMORY EVALUATION GAP / PUBLIC LAUNCH NOT READY`。

Exact Score C accepted：`56 verified / PROMISING_NOT_ESTABLISHED / shadow-only`，后台自然积累到 >=100；不调参救显著性。

Current bounded execution：Issue #180 `EXACT-SCORE-REEP-IDENTITY-BRIDGE-PREFLIGHT-1`，属于 Data / Identity / Rights lane；结束后回 Project Gate，不自动继续 identity subtree。

---

# 11. Post-#180 Highest-Value Candidate — 不是预授权 Issue

## `MULTI-MARKET-PREDICTION-COVERAGE-AND-EVALUATION-GAP-AUDIT`

必须一次形成四张地图：

### A. Prediction Scorecard Map

1X2 / O-U / BTTS / Exact 的 full/served hit rate、proper scores、calibration、CI、coverage、competition/horizon slices、1X2 class balance、strongest/weakest markets。

### B. Truth / Projection Map

中国竞彩 Tier-A 当前哪些可由 score state 数学推导；0–7+、official score buckets 是否只是 projection/evaluation gap；official handicap frozen truth / settlement 是否齐；HT truth 是 raw-source-but-not-contract 还是 source gap。

### C. Historical Football Memory / Corpus Map

current historical count by competition × season × team；regulation-90m semantics；HT coverage；canonical identity continuity；OpenFootball CC0 expansion；其它 rights-clear corpus；point-in-time replay readiness；sparse competitions / promoted teams 的 pooling need；historical odds/timepoint/rights。

### D. Baseline / Model-Bottleneck Map

common-score / league-mode Exact baseline；leakage-safe historical team-strength baseline；same-market/same-horizon market baseline；market-implied Exact MAP where legal；Football-only / Market-only / Fusion；Champion / C；current `_select_primary` routing surface；model-quality gap vs data/truth/projection/training-corpus gap。

完成四张地图以前默认不造新模型。

---

# 12. If Historical Memory Is Confirmed High-Value — Candidate Ladder

不是预授权。候选顺序：

1. historical corpus truth / rights closure；
2. simple leakage-safe dynamic team-strength baseline；
3. hierarchical / partial-pooling challenger；
4. same-horizon market baseline / implied score matrix；
5. football + market residual/fusion challenger；
6. Exact Score distribution family only if residuals justify；
7. enriched xG/lineup/player only if incremental；
8. market-specific heads / Router after independent evidence。

每一步必须能单独失败，不做整套大重构一次上线。

---

# 13. User Product Lane

首页：今天值得看的比赛 + 最稳观点 + Exact Score flagship + serving state。

Detail：`比赛怎么踢 → 多玩法概率 → Exact Top1/3/5 → Football vs Market → 最大风险/分叉 → Evidence → Historical reliability`。

长期区分 Accuracy-first / 命中优先 与 Market-value / 价值优先。高 hit rate ≠ 高 value；model-market disagreement ≠ edge。

---

# 14. Public Launch Parallel Gates

模型 lane 继续进化时并行关闭 Data Rights、Operations、Closed Beta measurement、Compliance、User decision UX、Distribution/repeat use。

不能等“模型最终完成”才开始用户验证，也不能因为 Beta 开始就放松 Prediction Quality Gate。

---

# 15. Explicitly Not Default Next

- 为了比分漂亮继续调 lambda/rho/selector；
- 为显著性调 C；
- 复活已否决 friendlies/recency/D；
- synthetic data 冒充真实样本；
- 大 corpus 不分年代/赛事/90m semantics 全扔进训练；
- closing market 给 T-24h 当 equal-information control；
- 因模型叫 deep/GNN/LLM 就优先；
- 玩法多就直接全部上线；
- generic news/live-score/community breadth；
- EV/stake/portfolio 先于 probability trust。

---

# 16. Completion Rule

每个 bounded task 完成：`Acceptance → Canonical Evolution Gate → 必要外部 Research Gate → route comparison → 唯一下一步`。

事实推翻 Roadmap 假设时先改 Roadmap。
