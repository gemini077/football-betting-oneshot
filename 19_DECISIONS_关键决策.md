# 19_DECISIONS_关键决策.md

最后更新：2026-09-04
角色：只记录**仍会约束今天与未来路线的 Durable Decisions / Anti-Rollback**。

本文件不是 milestone ledger。历史 D-xxx 从 Git history、Issues/PR、evidence docs 与 Memory-Hub 恢复。

长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

# D-CURRENT-01 — Product Identity

Football Betting OneShot 是足球信息 + 市场信息 + 赛前概率 + 可审计验证的决策支持产品。

- 核心玩法：1X2 / Exact Score / O-U / BTTS；
- 比分是一级能力，但不是唯一产品；
- 产品不是彩票交易、代购、出票、充值、自动下注或官方彩票服务；
- Betting Decision Layer 保持 downstream，直到 probability / calibration / executable price / compliance 均过 Gate。

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

无新证据不得复活：

- selector patch；
- Challenger D / market-calibrated lambda；
- global recency scan；
- current 61-match FRIENDLY_EXCLUDED route；
- global +lambda；
- mechanical Dixon-Coles rho；
- 1-1 penalty / diversity quota / random replacement / threshold hack。

---

# D-CURRENT-06 — Current Universe / Source Boundary

Nowscore public JC 是当前 production current-universe 主路径；500 已退出该 fallback 主链。

source 可访问 ≠ rights 已解决；provider failure 不得静默变空 universe；identity/business-date/source-cutoff fail closed。

---

# D-CURRENT-07 — Sporttery CRS Rights Not Cleared

Sporttery CRS 与 Exact Score 高度对齐，但当前自动化/商业数据利用 rights=`NOT_CLEARED`；不得因技术可达直接进 production。

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

# D-CURRENT-10 — Roadmap Is No Longer Model-First Serial

旧 `data → model → challenger → analysis → product` 串行路线废止为默认主干。

当前 product program=`PUBLIC-LAUNCH TRUST`，并行管理 Prediction、User Trust、Trust Center、Data/Rights、Operations、Closed Beta、Compliance、Distribution/Business 与 Advanced R&D。

局部技术 blocker 不能吞掉整个 Roadmap。

---

# D-CURRENT-11 — Prediction Trust Must Become User-Facing Truth

freeze、prospective evaluation、degraded/abstain、historical performance 不能永远只在后台。

用户要知道：怎么看、为什么、多大把握、哪里会错、什么时候不强猜、过去同类判断表现如何。

禁止用单一 hit rate 包装产品可信度。

---

# D-CURRENT-12 — Closed Beta Before Model Perfection

Closed Beta 不等待最终模型架构完成，但必须显式展示 uncertainty / abstention，并保持 Prediction Trust Gate。

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

# D-CURRENT-15 — Serving Is Segmented, Not Global

正式 serving 单位至少为：

`Market × Competition Support × Evidence Quality × Prediction Quality`

Markets：`1X2 / O-U / BTTS / Exact Score`。

Competition：`SUPPORTED / LIMITED / EXPERIMENTAL / UNSUPPORTED`。

Evidence：`FULL / PARTIAL / INSUFFICIENT`。

Serving：`NORMAL / CAUTION / DEGRADED / ABSTAIN`。

一个玩法的失败不得机械拖累其他玩法；其他玩法好也不得替该玩法背书。

---

# D-CURRENT-16 — Confidence Must Be Empirically Defensible

禁止把主观“高/中/低”当正式用户 confidence。

任何 confidence 必须能回到 prospective calibration / reliability bucket / sample size / uncertainty；否则只展示 evidence state、uncertainty 或 serving state。

---

# D-CURRENT-17 — Engineering Beta Ready ≠ Measurement Ready

当前状态=`LEVEL 4A — ENGINEERING CLOSED-BETA READY / TRUST-BETA MEASUREMENT PREP`。

真实 Closed Beta 前先具备最小低成本 measurement：detail activation、scenario comprehension、evidence expansion、Trust Center usage、postmatch return、repeat use、误解点。

不要求先搭账户重系统。

---

# D-CURRENT-18 — Transparency Alone Is Not the Moat

公开历史记录正在成为同类产品常见能力。

FBOS 差异化目标升级为：

`immutable record + segmented reliability + calibrated confidence + abstention + market/simple benchmark + known weakness transparency + compounding prospective ledger`。

---

# D-CURRENT-19 — Distribution / Monetization Is a Separate Discovery Lane

不与通用比分/新闻/社区产品拼 feature breadth。

Track record / methodology / completed reviews 倾向作为长期免费信任资产；future predictions / full evidence / advanced filters/alerts 可作为付费假设，但不得在 Closed Beta willingness-to-pay 与 Compliance Gate 前锁定。

禁止复制 VIP/红单/稳赚叙事。

---

# Historical Decision Archive Pointer

旧详细决策从 Git history、GitHub Issues/PR/Actions、`docs/*` evidence 与 Memory-Hub 恢复。

**只有仍影响当前路线的 durable decision 才允许进入本文件。**
