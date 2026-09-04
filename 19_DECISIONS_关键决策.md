# 19_DECISIONS_关键决策.md

最后更新：2026-09-04
角色：只记录**仍会约束今天与未来路线的 Durable Decisions / Anti-Rollback**。

本文件不是 milestone ledger。历史 D-xxx 从 Git history、Issues/PR、evidence docs 与 Memory-Hub 恢复。

长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

# D-CURRENT-01 — Product Identity / Core Value

Football Betting OneShot 是足球信息 + 市场信息 + **多玩法赛前预测** + 可审计验证的决策支持产品。

核心用户价值：**提高用户关心玩法的预测命中率与概率质量。**

Trust / immutable freeze / calibration / benchmark / abstain 的职责是证明这种预测质量真实、适用范围明确、不可赛后篡改；它们不是预测能力的替代品。

产品不是彩票交易、代购、出票、充值、自动下注或官方彩票服务。

---

# D-CURRENT-02 — Immutable Prematch Truth

正式 prediction 必须 prematch frozen；赛后只能追加 result/evaluation。

- postmatch truth 不进入赛前生成；
- `one football match = one observation`；
- version history 只作审计；
- source cutoff / model identity / probability state / freeze time 可追溯。

---

# D-CURRENT-03 — Champion / Challenger Governance

- Champion=`recent_form_market_calibrated_poisson_v2`；
- C=`market_side_only_hybrid / shadow-only`；
- `auto_promote=false`；
- `<50 NOT_REACHED / 50–99 CHECKPOINT / >=100 PROMOTION_REVIEW_READY at most`；
- Promotion 只能独立 review。

新 Challenger：`Research → fixed experiment → holdout/replay → prospective shadow → unique-match evaluation → independent Promotion Review`。

---

# D-CURRENT-04 — C Is Promising, Not Established

Accepted 50+ snapshot=`80 eligible / 56 verified / 24 unmatched`。

Exact Score NLL `C - Champion=-0.026121699`，但 IID 与 chronology-aware bootstrap CI 均跨 0，并存在时间段/英冠反向证据。

Decision=`C_SIGNAL_PROMISING_NOT_ESTABLISHED`。

不 Promotion、不调 C 救显著性；后台自然积累到 >=100。

---

# D-CURRENT-05 — Closed Exact-Score Routes

无新 evidence 不复活 selector patch、Challenger D、global recency、61-match FRIENDLY_EXCLUDED、global +lambda、mechanical Dixon-Coles rho、1-1/diversity/random/threshold hacks。

---

# D-CURRENT-06 — Current Universe / Source Boundary

Nowscore public JC 是当前 production current-universe 主路径；500 已退出该 fallback 主链。

source 可访问 ≠ rights 已解决；provider failure 不得静默变空 universe；identity/business-date/source-cutoff fail closed。

---

# D-CURRENT-07 — Sporttery Data Rights Not Automatically Cleared

Sporttery 玩法语义与中国目标用户高度相关，但技术可达不等于自动化商业数据利用许可。

官方玩法语义可以指导产品 target；生产抓取/存储/展示/商业利用仍必须过 Rights Gate。

---

# D-CURRENT-08 — The Odds API Benchmark-Only

`the-odds-api.com / api.the-odds-api.com` 当前只作为 rights-clear future-only external benchmark candidate。

PR #179 的 `0 exact identity` 只证明 cross-source identity 未就绪，不证明 correct-score coverage=0。

Benchmark 不自动成为 Champion/C 输入。

---

# D-CURRENT-09 — Cross-Provider Identity Is Deterministic

kickoff overlap、fuzzy、LLM translation、临时 transliteration、赛果、post-hoc manual guess 都不能单独成为 authoritative identity。

Current #180 仅做 bounded Reep v1 preflight；结束后回项目 Gate。

---

# D-CURRENT-10 — Roadmap Is Product-Outcome Driven, Not Model-First or Trust-First

旧 `data → model → challenger → analysis → product` 串行路线废止。

同时也禁止新的反向过度纠偏：`Trust Center → transparency → user trust` 不能成为预测能力的替代主干。

正确层级：

`MULTI-MARKET PREDICTION QUALITY → PROSPECTIVE PROOF/TRUST → USER SERVING → PUBLIC-LAUNCH GATES`

---

# D-CURRENT-11 — Hit Rate Is Core, But Must Be Honest

命中率是核心产品结果指标之一，不再把它降级成“只是营销数字”。

但任何命中率必须逐玩法报告，并与以下内容绑定：

- full coverage vs served coverage；
- coverage / abstain rate；
- same-market baseline；
- proper score / calibration；
- sample size / uncertainty；
- competition/population scope。

禁止一个跨玩法 blended “overall hit rate”。

---

# D-CURRENT-12 — Closed Beta Before Model Perfection

Closed Beta 不等待最终模型架构完成，但必须显式展示 uncertainty / abstention，并保持 Prediction Quality Gate。

用户喜欢 ≠ 模型可信；模型可信 ≠ 用户产品成立。

---

# D-CURRENT-13 — Technical Accessibility Is Not Commercial Permission

每个数据源分别判断：`technical access / storage / analysis / commercial app use / display / redistribution / raw-feed resale`。

Public commercialization 前 Data Rights 必须独立关闭。

---

# D-CURRENT-14 — Completion Returns to Project Gate

bounded task 完成后不自动沿同技术树继续。

Founder “已完成”触发：`acceptance → Canonical Gate → 必要 Research Gate → route comparison → unique best next step`。

---

# D-CURRENT-15 — Serving Is Segmented By Market

正式 serving 单位：

`Market × Competition Support × Evidence Quality × Prediction Quality`

Competition：`SUPPORTED / LIMITED / EXPERIMENTAL / UNSUPPORTED`。

Evidence：`FULL / PARTIAL / INSUFFICIENT`。

Serving：`NORMAL / CAUTION / DEGRADED / ABSTAIN`。

一个玩法失败不得拖累其它玩法；其它玩法好不得替它背书。

“精选高命中”必须同时公开/可追溯 coverage，禁止靠大量 abstain 制造虚高准确率。

---

# D-CURRENT-16 — Confidence Must Be Empirically Defensible

任何正式 confidence 必须能回到 prospective calibration / reliability bucket / sample size / uncertainty / population scope；否则只展示 evidence/uncertainty/serving state。

---

# D-CURRENT-17 — Engineering Beta Ready ≠ Measurement Ready

当前可以工程 Closed Beta，但邀请真实用户前先具备最低成本 measurement：detail activation、market usage、scenario comprehension、evidence expansion、postmatch return、repeat use、误解点。

---

# D-CURRENT-18 — Transparency Is Proof, Not the Moat by Itself

公开历史记录已经逐渐商品化。

FBOS 真正要复利的是：

`better multi-market predictions + immutable record + segmented reliability + calibrated confidence + abstention + same-market benchmark + known weakness transparency + compounding prospective ledger`

顺序不能反过来。

---

# D-CURRENT-19 — Distribution / Monetization Is Separate Discovery

不与通用比分/新闻/社区产品拼 feature breadth。

Track record / methodology / completed reviews 倾向长期免费作为信任资产；future predictions / full evidence / advanced filters/alerts 是待 Beta 验证的付费假设。

禁止复制 VIP/红单/稳赚叙事。

---

# D-CURRENT-20 — China JC Market Universe Is First-Class

长期 Tier-A 不再只写 `1X2 / Exact / O-U / BTTS`。

中国竞彩用户第一等预测 target 至少包括：

- 胜平负；
- 让球胜平负；
- 比分（raw score distribution + official result buckets）；
- 总进球数 0–7+；
- 半全场。

O/U、BTTS、Asian handicap 等继续作为重要 Tier-B 国际/分析型市场。

混合过关是 downstream composition，不是独立模型 target。

---

# D-CURRENT-21 — One Score State May Feed Many Markets, But One Model Need Not Be Optimal For All

长期优先：

`shared features → authoritative full-time joint goal state → coherent FT markets → market-specific calibration/head when prospective evidence proves gain`

允许专门 1X2 / Goals / BTTS / handicap head，但必须固定实验、独立评价，并检查与共同 score state 的冲突。

---

# D-CURRENT-22 — HTFT Requires First-Half Truth

半全场不得通过 `90m lambda / 2` 直接制造。

必须先证明 first-half score/outcome truth、prematch inputs、结算语义与 dedicated evaluation 可用，再决定模型路线。

当前这是一项待审计缺口，不是预授权工程任务。

---

# D-CURRENT-23 — Same-Market Baseline Is Mandatory Where Available

模型不能只因为比 random/naive baseline 好就获得“优秀”标签。

长期按玩法优先比较对应 market/de-vigged/simple strong baseline，并报告 `delta vs baseline`。

Football-only / Market-only / Fusion 长期保持可区分。

---

# D-CURRENT-24 — Post-#180 Highest Candidate Is Multi-Market Evaluation Gap Audit

#180 不取消、不改契约。

但在其完成后，当前最高信息价值候选是：

`MULTI-MARKET-PREDICTION-COVERAGE-AND-EVALUATION-GAP-AUDIT`

先查 current repo 已经能预测/推导/冻结/结算/评价哪些玩法，以及各玩法 current prospective scorecard；再决定下一模型或新玩法实现。

这不是预授权 Issue，#180 完成后仍需完整 Research-Backed Project Gate。

---

# Historical Decision Archive Pointer

旧详细决策从 Git history、GitHub Issues/PR/Actions、`docs/*` evidence 与 Memory-Hub 恢复。

**只有仍影响当前路线的 durable decision 才允许进入本文件。**
