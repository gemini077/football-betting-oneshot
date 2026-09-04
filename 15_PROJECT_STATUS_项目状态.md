# 15_PROJECT_STATUS_项目状态.md

最后更新：2026-09-04
角色：**主仓库中的当前状态投影**。只保留今天仍成立、会影响当前决策的事实；不保存 milestone 流水账。

长期 Canonical Source of Truth：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

## 1. 产品定位

Football Betting OneShot 是面向中国用户的足球信息 + 市场信息 + 赛前概率 + 可审计验证的决策支持产品。

核心输出：`1X2 / Exact Score / O-U / BTTS`。

产品不是彩票交易、代购、出票、充值、自动下注或官方彩票机构服务。

---

## 2. 当前成熟度

- Whole product：`LEVEL 4A — ENGINEERING CLOSED-BETA READY / TRUST-BETA MEASUREMENT PREP / PUBLIC LAUNCH NOT READY`
- Strategic program：`PUBLIC-LAUNCH TRUST`
- 最大技术 P0：`Exact Score Prediction Trust`
- Product/UI：Homepage + Match Detail 已存在；G5 functional/product gate 已过。
- Production foundation：Universe、freeze、90m result、prospective ledger、automation、Pages 已建立。

解释：产品已经能运行，也已经具备 Closed Beta 边界文案和单场赛后验证；但真实 Beta 还缺最小用户测量能力、可验证 confidence、按玩法/赛事分层的 serving contract 和聚合 Trust Center。

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

## 4. 当前 Product Trust Surface — 已有与缺口

代码现状已经有：

- `prediction_quality_health` 与 Exact Score serving warning；
- score distribution / Top score alternatives；
- `INSUFFICIENT_DATA / PREDICTION_FAILED / MISSED_PREMATCH_WINDOW` 等 fail-closed 状态；
- Closed Beta / 不售彩 / responsible-use 文案；
- 单场 `prediction vs actual` 赛后核验；
- frozen/source-cutoff 等可追溯字段。

当前缺口：

1. **没有被历史 calibration 证明的 user-facing confidence 语义**；
2. **没有 per-market × competition-tier serving matrix**；
3. Exact Score health 已独立治理，但 1X2 / O-U / BTTS 尚未形成同等级 user-serving contract；
4. 首页当前主要仍按 kickoff 排序，不是真正按 evidence/trust 帮用户优先决策的 queue；
5. 没有聚合 Trust Center：per-market proper scores、calibration、样本、赛事分层、known weaknesses、market benchmark 尚未产品化；
6. Closed Beta 没有最小行为/理解度 measurement surface。

因此下一阶段不是“再多做几个页面模块”，而是把已有后台真相组织成可验证的用户信任系统。

---

## 5. Segmented Trust Contract — 当前新战略真相

正式 serving 以后至少按：

`Market × Competition Support × Evidence Quality × Prediction Quality`

分别判断。

### Markets
`1X2 / O-U / BTTS / Exact Score`

### Competition Support
`SUPPORTED / LIMITED / EXPERIMENTAL / UNSUPPORTED`

### Evidence Quality
`FULL / PARTIAL / INSUFFICIENT`

### Serving State
`NORMAL / CAUTION / DEGRADED / ABSTAIN`

一个玩法 DEGRADED 不得自动拖累其他玩法；其他玩法表现好也不得替 Exact Score 背书。

任何“高/中/低置信度”若不能映射到 prospective calibration / reliability / sample uncertainty，不得作为正式用户 confidence。

---

## 6. External Correct-Score Benchmark

Issue #178 / PR #179 accepted：

- FBOS future candidates=`60`
- provider events=`646`
- kickoff overlap=`60/60`
- exact identity=`0`
- correct_score probes=`0`
- credits=`0`
- decision=`IDENTITY_MAPPING_NOT_READY`

`0 exact identity` 不等于 provider coverage=0；market 尚未真正 probe。

Current bounded execution：Issue #180 `EXACT-SCORE-REEP-IDENTITY-BRIDGE-PREFLIGHT-1`。

#180 属于 Data / Identity / Rights lane；完成后必须回项目级 Gate，不自动继续 identity/provider 子树。

---

## 7. 当前 Product Lanes

| Lane | 状态 |
|---|---|
| Prediction Trust | `CURRENT / P0` |
| User Trust / Decision Product | `CURRENT / P0` |
| Trust Center / Public Track Record | `CURRENT DESIGN PRIORITY` |
| Data / Identity / Rights | `CURRENT / P0 FOUNDATION` |
| Operations / Reliability | `REQUIRED BEFORE PUBLIC LAUNCH` |
| Closed Beta / User Validation | `NEXT PRODUCT MATURITY GATE` |
| Compliance / Commercial | `REQUIRED BEFORE PUBLIC COMMERCIALIZATION` |
| Distribution / Business Model | `DISCOVERY AFTER BETA SIGNAL` |
| Advanced Model R&D | `SUPPORTING / DEMAND-TRIGGERED` |

---

## 8. 仍生效的 Anti-Rollback

- frozen prematch history 不重写；postmatch truth 不进入赛前生成。
- selector 不是历史 1-1 collapse 主因。
- Challenger D REJECTED；global recency route REJECTED；61-match friendlies causal route RETIRED。
- 不机械打开 Dixon-Coles rho；不做 1-1 penalty / diversity quota / random replacement。
- C=`PROMISING_NOT_ESTABLISHED`，不得包装成稳定优于 Champion。
- Sporttery CRS rights=`NOT_CLEARED`。
- external market benchmark 先是 benchmark，不自动成为模型输入。
- technical accessibility != commercial reuse permission。
- transparency/track record 本身不是唯一 moat；必须和 segmented reliability / abstention / benchmark / failure transparency 组合。

---

## 9. 历史 Pointer

历史 milestone 只从 Git history、Issues/PR/Actions、`docs/*` evidence 与 Memory-Hub Research Assets 恢复。

**禁止再次把历史正文复制回当前状态文件。**
