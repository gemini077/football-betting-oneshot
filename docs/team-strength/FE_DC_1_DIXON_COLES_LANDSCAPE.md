# FE-DC-1 Dixon–Coles / Maher landscape and pre-registration

状态：`RESEARCH INPUT / PRE-REGISTERED`

本文件记录 FE-DC-1 编码前完成的公开资料核对、候选比较和有界采用决定。它只服务于 Sweden Allsvenskan 的 research/shadow baseline，不改变 Champion、production runner、frozen prediction 或 shared historical store。

## 1. 公开研究基线

### Maher (1982)

Maher 的模型以主客队 attack / defense strength 解释进球，并把独立 Poisson 作为可用的足球比分描述；论文摘要同时指出，双变量 Poisson 的相关项可以改善小型系统性偏差。原始书目和摘要：

- Maher, M. J. (1982), *Modelling association football scores*, Statistica Neerlandica 36(3), 109–118：[Wiley DOI](https://doi.org/10.1111/j.1467-9574.1982.tb00782.x)

FE-DC-1 采用 Maher 的可解释 attack / defense 网络结构，但用 canonical team IDs 和严格按 kickoff 的历史切片，避免把局部近期统计误称为全联赛强度。

### Dixon–Coles (1997)

Dixon 和 Coles 在 Maher/Poisson 结构上加入动态表现处理与低比分依赖修正，并以最大似然估计参数：

- Dixon, M. & Coles, S. (1997), *Modelling Association Football Scores and Inefficiencies in the Football Betting Market*, Journal of the Royal Statistical Society: Series C 46(2), 265–280：[Wiley DOI](https://doi.org/10.1111/1467-9876.00065)
- 可读论文副本：[PDF mirror](https://ajbuckeconbikesail.net/wkpapers/Airports/MVPoisson/soccer_betting.pdf)

本轮只实现标准四个低比分单元的 `tau` 修正：`0-0`、`1-0`、`0-1`、`1-1`。所有其他 score cells 的 `tau=1`，不加入人工 score diversity、draw penalty 或 outcome-conditioned reranking。

## 2. 成熟实现与替代方案 shortlist

| 候选 | 类型 | 公开可核对能力 | FE-DC-1 决定 | 原因 |
| --- | --- | --- | --- | --- |
| [penaltyblog](https://github.com/martineastwood/penaltyblog) / [Dixon–Coles docs](https://penaltyblog.readthedocs.io/en/master/models/overview.html) | Python OSS | MLE goal model、time weights、rho、score grid、normalization、gradient implementation | `REFERENCE` | API 和实现成熟，但当前项目不新增 NumPy/SciPy 依赖；研究产物需要可审计的本地模型身份、网络统计和逐场 history evidence。 |
| [football-mle](https://github.com/jpmouracodex/football-mle) | Python OSS | 从 Maher / Dixon–Coles 公式实现 MLE、analytic gradient、identifiability、score matrix、temporal validation | `REFERENCE` | 透明度和测试思路适合借鉴；本轮保持项目现有最小依赖并只做 Sweden 单联赛 bounded slice。 |
| [thewongdirection/soccer-betting-strategy](https://github.com/thewongdirection/soccer-betting-strategy) | Python OSS | 明确 look-ahead-free 的按联赛历史攻防、可选 DC、回测与校准告警 | `REFERENCE` | 对样本外评估和 overconfidence 的工程提醒有价值；FE-DC-1 不进入 betting / EV 层。 |
| [RyanSCodes/Dixon-Coles-Football-Predictor](https://github.com/RyanSCodes/Dixon-Coles-Football-Predictor) | GitHub implementation | 基于历史结果估计 home advantage、attack、defense | `REFERENCE` | 作为独立实现交叉核对；维护深度、许可证和研究证据合同不足以直接嵌入。 |
| [Sportmonks Football API](https://www.sportmonks.com/football-api/) | 商业/免费起步数据 API | 历史 fixture、team、lineup、xG、odds 与 prediction API；历史深度与配额按方案变化 | `DEFER` | 不是本轮模型实现；会引入新 provider、ToS/成本和 crosswalk migration，且当前 authoritative Sweden store 已足够。 |
| [Sportradar Soccer API](https://developer.sportradar.com/soccer/reference/soccer-overview) | 商业数据 API | 650+ competitions、历史/实时赛事、team/player、lineup、probability 等覆盖 | `DEFER` | 适合未来覆盖/质量基准，但认证、商业授权和新 provider 变更不属于本 bounded milestone。 |
| [Genius Sports APIs](https://developer.geniussports.com/) | 商业数据 API | warehouse/statistics、fixtures、matching 与 streaming 接口 | `DEFER` | 可作未来官方数据 benchmark；Matching API 不能替代本项目的 deterministic identity policy，当前不引入。 |
| 国内商业/聚合 API 候选 | 商业数据/API | 本轮搜索未找到同时具备可审计 Sweden historical depth、稳定 team crosswalk 和公开可比较模型合同的候选 | `REJECT FOR THIS SLICE` | 不为了填充 landscape 而新增 provider；继续使用现有 authoritative store 和已验收 durable crosswalk。 |

## 3. 常见坑与本轮约束

1. **不可识别性**：attack/defense 的平移或缩放可以不改变 likelihood。实现采用 log-rate 加法形式，并对 attack、defense 各自施加 sum-to-zero；测试必须验证约束。
2. **rho 不是普通相关系数**：`rho` 只通过四个低比分 `tau` 单元起作用，不能把它解释成 home/away goals 的 Pearson correlation，也不能把 rho 作为全矩阵的统一乘数。
3. **tau 必须保持非负**：每个观测比分的 `tau` 必须为正，才能取 log-likelihood；非法参数返回显式不可行目标值，而不是静默产生 NaN。
4. **截断矩阵不等于无限分布**：输出完整的固定 score grid，同时记录 grid mass / tail mass，并在 NLL 前使用显式 normalization；不把截断误报为天然和为 1。
5. **训练/预测时间边界**：目标只允许使用 `kickoff_at < target_kickoff_at` 的同赛事记录；同一时间戳不互相训练。`source captured_at` 不能替代比赛发生时间。
6. **全网络而非局部样本**：每个目标的拟合输入是该目标 cutoff 前整个 Sweden Allsvenskan connected historical network；不按 target 两队单独聚合、不做 recent-form weight sweep。
7. **稀疏/转赛季网络**：warm-up 必须证明 18 个 canonical historical team IDs 已出现且图连通；早于该门槛的比赛不计入 formal held-out metrics，而不是用猜测式 shrinkage 补齐。
8. **同场只计一次**：先按 canonical match identity 做保守去重；冲突或不确定 duplicate 不进入模型，并在 evidence 中报告。
9. **只报命中率会误导**：必须同时报告 1X2 Brier、LogLoss、goal MAE、exact Top-K、score NLL、calibration、lambda 与 total-goal tail；不能用 Top1 代替分布质量。
10. **rho=0 control 不是调参 sweep**：control 与 primary 使用完全相同的训练切片、权重和 optimizer；唯一差异是将 rho 固定为 0，用于隔离低比分修正的增量。

## 4. FE-DC-1 预注册配置

- dataset：现有 `FOOTBALL_DATA_HOME/historical_results.duckdb`；只取 `competition:sweden-allsvenskan`、`entity_type=club`、`match_type=league`、`eligible_for_team_strength=true`。
- chronology：按 `(kickoff_at, canonical_match_id)` 排序；预测目标严格使用 exclusive cutoff。
- formal warm-up：前 `32` 场作为最小训练窗口；该窗口之后确认 18 个 team IDs、1 个 connected component，再开始 held-out。
- primary: weighted maximum-likelihood Maher + Dixon-Coles; fixed `half_life_days=365`; fit `rho` within the fixed `[-0.10, 0.10]` validity range; no half-life/rho/learning-rate sweep.
- control：相同 weighted Maher/Poisson network，`rho=0` 固定。
- parameterization: log-rate with attack and defense sum-to-zero constraints; deterministic bounded projected-Newton optimizer with analytic gradient/Hessian; no new dependency.
- score output: `0..12 ? 0..12` full matrix; record raw grid mass, finite-grid tail diagnostic, and normalization.
- full-distribution guard: the selected fixed rho range is validated at every emitted target; any non-positive low-score tau is an explicit error, never a negative probability or silent NaN.
- evaluation：expanding-window held-out，每场 refit primary 与 control；输出每场可见的全联赛历史场数、两队历史场数、network team/component counts、训练最大 kickoff。
- scope：research/shadow only；不写 production/shared DB、不修改 Champion、不改 frozen prediction、不接 provider、不使用 xG/lineup/Elo。

## 5. 有界采用结论

当前从零开始仍选择本地实现这一窄 slice，而不是接入第三方模型包：模型本身只有少量稳定数学部件，新增依赖会扩大 runtime/lockfile surface，且项目验收要求比通用库更严格的 chronological evidence。第三方实现用于公式、约束、矩阵 normalization 和验证项交叉核对；真正的 adoption gate 留给后续 prospective shadow / promotion review，不由本历史 backtest 自动触发。
