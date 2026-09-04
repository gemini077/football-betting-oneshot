# 19_DECISIONS_关键决策.md

最后更新：2026-09-04
角色：只记录**仍会约束今天与未来路线的 Durable Decisions / Anti-Rollback**。

本文件不是 milestone ledger。旧 D-xxx 全量历史继续存在于 Git history、Issues/PR、evidence docs 与 Memory-Hub；不在当前文件重复保存。

长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

# D-CURRENT-01 — Product Identity

Decision：Football Betting OneShot 是足球信息 + 市场信息 + 赛前概率 + 可审计验证的**决策支持产品**。

- 核心玩法：1X2 / Exact Score / O-U / BTTS；
- 比分是一级能力，但不是唯一产品；
- 产品不是彩票交易、代购、出票、充值、自动下注或官方彩票服务；
- Betting Decision Layer（EV/stake/portfolio）保持 downstream，直到 probability / calibration / executable price / compliance 均过 Gate。

---

# D-CURRENT-02 — Immutable Prematch Truth

Decision：正式 prediction 必须 prematch frozen，赛后只能追加 result/evaluation，不得改写赛前答案。

- postmatch truth 不得进入赛前生成；
- `one football match = one observation`；
- version history 可审计但不能放大统计样本；
- source cutoff / model identity / probability state / freeze time 必须可追溯。

---

# D-CURRENT-03 — Champion / Challenger Governance

Decision：

- Champion=`recent_form_market_calibrated_poisson_v2`；
- Challenger C=`market_side_only_hybrid / shadow-only`；
- `auto_promote=false`；
- `<50 unique=NOT_REACHED`；`50–99=CHECKPOINT`；`>=100=PROMOTION_REVIEW_READY at most`；
- Promotion 只能经独立 review。

任何新 Challenger 都必须：

`Research → fixed experiment → historical holdout/replay → prospective shadow → unique-match evaluation → independent Promotion Review`。

---

# D-CURRENT-04 — Challenger C Is Promising, Not Established

Accepted 50+ snapshot：`80 eligible / 56 verified / 24 unmatched`。

Exact Score NLL `C - Champion` mean=`-0.026121699`，但 IID 与 chronology-aware bootstrap 95% CI 都跨 0；存在时间段与英冠 slice 的 Champion-favored 反向证据。

Decision=`C_SIGNAL_PROMISING_NOT_ESTABLISHED`。

因此：

- 不 Promotion；
- 不为显著性调 C；
- 不反复扫描参数/inference；
- C 后台自然积累到 >=100。

---

# D-CURRENT-05 — Exact-Score Failure Routes Already Closed

以下路线不能无新证据复活：

- selector patch 不是 1-1 collapse 根因；
- Challenger D / market-calibrated lambda：REJECTED；
- global recency half-life scan：REJECTED；
- current 61-match FRIENDLY_EXCLUDED causal route：RETIRED（provenance/sample 不足）；
- global +lambda：当前 chronology/universe evidence 不支持；
- 简单“打开 Dixon-Coles rho”：旧 Sweden strict holdout 未优于 rho=0 control；
- 1-1 penalty / diversity quota / random replacement / threshold hack：禁止。

新模型必须来自新的 failure-mode + applicability evidence，而不是换名字重跑旧路线。

---

# D-CURRENT-06 — Current Universe / Data Source Boundary

Decision：Nowscore public JC 是当前 production current-universe 主路径；500 已退出 current-universe fallback 主链。

原则：

- source 可访问 ≠ rights 已解决；
- provider failure 不应静默变成空 universe；
- identity / business-date / source cutoff 均 fail closed；
- provider 与模型职责分离。

---

# D-CURRENT-07 — Sporttery CRS Rights Not Cleared

Decision：Sporttery `CRS/比分` 与 Exact Score target 高度匹配，但当前未经书面许可的第三方接入/复制/相关数据利用边界不足以支持自动化商业生产链。

状态=`RIGHTS_NOT_CLEARED`。

不得因为技术上能访问就直接接 production。

---

# D-CURRENT-08 — The Odds API Is Benchmark-Only Until Further Gate

Decision：锁定 `the-odds-api.com / api.the-odds-api.com` 作为当前 rights-clear external correct-score benchmark candidate。

允许：future-only benchmark/capture、storage/analytics/derived/model-training 在其当前公开 Terms 边界内。

禁止：

- 把 raw feed 当独立数据产品转售/再分发；
- 历史 backfill 伪装 prematch；
- benchmark 自动成为 Champion/C 输入；
- provider hopping 规避失败 Gate。

PR #179 的 `0 exact identity` 只证明 identity mapping 未就绪，**不证明 correct-score coverage=0**。

---

# D-CURRENT-09 — Cross-Provider Identity Must Be Deterministic

Decision：跨源 team/match identity 必须可审计并 fail closed。

不能单独作为 authoritative identity 的信号：

- kickoff overlap；
- fuzzy similarity；
- LLM translation；
- on-the-fly transliteration；
- result score；
- manual post-hoc guessing。

当前 repo 的 `team_identity.py + team_aliases.json` 只允许 confirmed alias/evidence。

Current candidate #180：Reep v1 exact/typed alias + competition context preflight。

#180 完成后必须回项目 Gate，不自动继续 identity 子树。

---

# D-CURRENT-10 — Product Roadmap Is No Longer Model-First Serial

Decision：旧“数据基础 → 模型成熟 → 分析 → 完整产品 → 用户/商业”的串行路线不再作为默认 Roadmap。

当前产品已具备 substantial production/product foundation；下一阶段必须并行管理：

- Prediction Trust；
- User Trust / Product；
- Data / Identity / Rights；
- Operations / Reliability；
- Closed Beta / User Validation；
- Compliance / Commercial；
- Advanced Model R&D（supporting lane）。

局部技术 blocker 不能吞掉整个 Roadmap。

---

# D-CURRENT-11 — Prediction Trust Must Become User-Facing Truth

Decision：后台的 freeze、prospective evaluation、confidence/evidence quality、degraded/abstain、historical performance 不能永远只作为工程资产。

产品长期需要让用户知道：

- 这场怎么看；
- 哪些比分情景最可能；
- 有多大把握；
- 为什么；
- 最大风险；
- 什么时候系统选择不强猜；
- 过去类似判断真实表现如何。

禁止只宣传单一“命中率”或把 degraded prediction 包装成 normal recommendation。

---

# D-CURRENT-12 — Closed Beta Before Model Perfection

Decision：Closed Beta 不需要等待最终模型架构完成，但必须明确展示不确定性与 abstention，并保持 Prediction Trust Gate。

目的：获得当前最缺失的 evidence——真实用户是否理解、使用、回访，以及哪些玩法/页面真正有价值。

用户喜欢 ≠ 模型可信；模型可信 ≠ 用户产品成立。两类证据并行。

---

# D-CURRENT-13 — Technical Accessibility Is Not Commercial Permission

Decision：任何数据/API/网页必须分别判断：

`technical access / storage / analysis / commercial app use / redistribution / raw-feed resale`

不得把“能抓”写成“能商用”。

Public commercialization 前 Data Rights 必须作为独立 Gate 关闭。

---

# D-CURRENT-14 — Completion Returns to Project Gate

Decision：一个 bounded task 完成后，默认动作不是沿同一技术树继续。

Founder 回复“已完成”触发：

`Independent acceptance → Canonical Evolution Gate → 必要的外部 Research Gate → route comparison → unique best next step`

如果新事实证明 Roadmap 假设已失效，先改 Roadmap。

---

# Historical Decision Archive Pointer

旧 D-001...D-041 等详细决策仍可从：

- Git history 中本文件旧版本；
- GitHub Issue / PR / Actions；
- `docs/data-foundation/`；
- `docs/prediction-quality/`；
- `docs/model-governance/`；
- `docs/research/`；
- Memory-Hub `RESEARCH_ASSETS.md` / Canonical Decision Lineage

恢复。

**只有仍影响当前路线的 durable decision 才允许重新进入本文件。**
