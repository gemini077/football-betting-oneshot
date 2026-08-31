# PRED-COVERAGE-TRUTH-1 — 当前日预测可用性根因审计

状态：`READY_FOR_ACCEPTANCE`

审计业务日：`2026-08-31`
当前 Universe：12 场
FROZEN：1
INSUFFICIENT_DATA：11
11 场共同 `last_error`：`MISSING_RECENT_FORM`

本轮只固化事实、根因矩阵和路线判断；没有刷新生产数据、重跑生产预测、补 alias、修改 Champion、修改模型/health rule、增加 provider、启动 ID-AUTO-2/PRED-AVAIL-3 或修改 frontend。

## 1. 证据权威与读取边界

以 `origin/main=8d5c4910bb102f3ce37a7e0a241e5d46c2ff346d` 的可验证生产快照为本轮基线。使用的主要证据：

- `D:\MyProject\football-betting-oneshot-main\data\base_prediction_jobs\2026-08-31.json`
- `D:\MyProject\football-betting-oneshot-main\data\prediction_dashboard\latest.json`
- `D:\MyProject\football-betting-oneshot-main\data\prediction_universe\2026-08-31.json`
- `D:\MyProject\football-betting-oneshot-main\data\product_runtime\latest_cycle.json`
- `D:\MyProject\football-betting-oneshot-main\data\football_data\hc_auto_1\coverage_registry.json`
- `D:\MyProject\football-betting-oneshot-main\data\football_data\hc_auto_1\daily_fixture_audit.json`
- `D:\MyProject\football-betting-oneshot-main\data\football_data\id_auto_1\daily_fixture_audit.json`
- `D:\MyProject\football-betting-oneshot-main\data\football_data\id_auto_1\identity_registry.json`
- `D:\MyProject\football-betting-oneshot-main\data\football_data\id_auto_1\identity_resolution_backlog.json`
- `D:\MyProject\football-betting-oneshot-main\data\football_data\team_alias_registry.json`
- `D:\MyProject\football-betting-oneshot-main\data\football_data\verified_identity_crosswalk.json`
- `D:\MyProject\football-betting-oneshot-main\data\football_data\verified_project_provider_crosswalk.json`
- `D:\MyProject\football-betting-oneshot-main\data\football_data\current_match_identity_evidence.json`
- `D:\MyProject\football-betting-oneshot-main\data\football_data\manifests\historical_results.dataset.json`
- `D:\MyProject\football-betting-oneshot-main\data\product_runtime\openfootball_recent_form.json`
- `D:\MyProject\football-betting-oneshot-main\config\team_strength_recency.json`
- `D:\MyProject\football-betting-oneshot-main\scripts\recent_form_cache.py`
- `D:\MyProject\football-betting-oneshot-main\scripts\base_prediction_runner.py`
- `D:\MyProject\football-betting-oneshot-main\scripts\daily_schedule_workspace.py`
- `D:\MyProject\football-betting-oneshot-main\scripts\fetch_sporttery.py`
- `D:\MyProject\football-betting-oneshot-main\scripts\fetch_trade_matches.py`

权威历史库使用只读模式：`C:\Users\Administrator\.football-betting-oneshot\football_data\historical_results.duckdb`，1778 条记录；本轮前后文件大小、mtime、SHA-256 均保持不变。完整逐场 JSON 矩阵见：

`D:\MyProject\football-betting-oneshot-main\data\football_data\pred_coverage_truth_1\root_cause_matrix_2026-08-31.json`

## 2. Rolling availability truth

定义：

- formal availability = `FROZEN / fixtures`
- availability after missed window = `FROZEN / (FROZEN + INSUFFICIENT_DATA)`，单独排除 `MISSED_PREMATCH_WINDOW`

| business date | fixtures | FROZEN | INSUFFICIENT_DATA | MISSED_PREMATCH_WINDOW | PREDICTION_FAILED | 非成功状态分布 |
|---|---:|---:|---:|---:|---:|---|
| 2026-08-18 | 4 | 2 | 0 | 2 | 0 | MISSED 2 |
| 2026-08-19 | 8 | 7 | 0 | 1 | 0 | MISSED 1 |
| 2026-08-20 | 9 | 8 | 0 | 1 | 0 | MISSED 1 |
| 2026-08-21 | 11 | 8 | 0 | 3 | 0 | MISSED 3 |
| 2026-08-22 | 28 | 26 | 0 | 2 | 0 | MISSED 2 |
| 2026-08-23 | 27 | 12 | 0 | 15 | 0 | MISSED 15 |
| 2026-08-24 | 11 | 7 | 0 | 4 | 0 | MISSED 4 |
| 2026-08-25 | 9 | 8 | 0 | 1 | 0 | MISSED 1 |
| 2026-08-26 | 12 | 11 | 0 | 1 | 0 | MISSED 1 |
| 2026-08-27 | 9 | 9 | 0 | 0 | 0 | — |
| 2026-08-28 | 14 | 8 | 0 | 6 | 0 | MISSED 6 |
| 2026-08-29 | 29 | 24 | 1 | 4 | 0 | MISSED 4；其中 1 场 `MISSING_RECENT_FORM` |
| 2026-08-30 | 25 | 23 | 0 | 2 | 0 | MISSED 2 |
| 2026-08-31 | 12 | 1 | 11 | 0 | 0 | `MISSING_RECENT_FORM` 11 |

聚合结果：

| 窗口 | fixtures | FROZEN | INSUFFICIENT_DATA | MISSED | formal availability | after missed window |
|---|---:|---:|---:|---:|---:|---:|
| 14 日：08-18..08-31 | 208 | 154 | 12 | 42 | 74.04% | 92.77% |
| 7 日：08-25..08-31 | 110 | 84 | 12 | 14 | 76.36% | 87.50% |
| 3 日：08-29..08-31 | 66 | 48 | 12 | 6 | 72.73% | 80.00% |

判断：

1. `1/12` 不是历史上每天稳定为 `1/12` 的长期结果；在 14 日和 7 日正式 FROZEN 率仍分别为 74.04% 和 76.36%。
2. 但 identity/历史覆盖风险是结构性的：最近 ID-AUTO-1 的 66 场 cohort 在 AFTER 只有 2 场 `SUPPORTED`、64 场 `UNSUPPORTED`；57 场 fixture 完全 unresolved、7 场 partial、2 场 auto-resolved，132 个 side 中仅 11 个有 resolved identity。
3. `coverage UNSUPPORTED` 本身没有阻断 Champion：当前快照仍记录 `champion_prediction_allowed=12`、`blocked=0`。08-29/08-30 的大量 FROZEN 说明已有 source/snapshot 路径可以掩盖 identity 缺口；08-31 恰好在这些替代路径没有形成可用 recent form 时暴露为 11 场缺失。
4. 结论是：**可用性 1/12 是急性端到端坍塌；exact identity coverage gap 是长期结构性 primary blocker；两者不是同一个统计事实。**

## 3. 当前 11 场的共同 acquisition path

`D:\MyProject\football-betting-oneshot-main\scripts\base_prediction_runner.py` 的 recent-form 路径按既有顺序检查：

1. existing prematch snapshot；
2. Nowscore exact schedule binding；
3. 500 deep source；
4. exact recent-form cache；
5. `load_authoritative_recent_form()`；
6. 仍无可用四块 recent form 时输出 `MISSING_RECENT_FORM`。

当前 11 场的逐层事实：

- current universe 12/12 的 `nowscoreMatchStatus=NO_EXACT_MATCH`，`nowscoreId` 为 0/12；
- 当前 `base_prediction` 运行摘要记录 19 条 `[FETCH]`，19 条均为 `Connection refused`，覆盖 `touzhu / ouzhi / yazhi / rangqiu / daxiao / shuju` 六类 500 deep endpoint；生产快照没有保存按 fixture 分组的 deep error envelope，因此逐场 deep outage attribution 标为 `UNKNOWN`，不把 run-level error 伪装成逐场证据；
- `openfootball_recent_form.json` 只有 5 个 fixture entry，11 个目标 exact `match_id` 均为 cache miss；
- 11 个目标没有 existing prematch snapshot；
- 11 个目标均有至少一条 market/odds row，但 market-only 不满足 recent-form contract；
- historical store 可用且只读，但 `load_authoritative_recent_form()` 先要求 resolved competition、home exact canonical team ID、away exact canonical team ID；任一 side 缺 ID 时 pair-level history query 在 identity gate 前停止。

因此，当前 11 场的共同端到端分类为 `MULTI_CAUSE`：`IDENTITY_UNAVAILABLE + Nowscore_NO_EXACT_MATCH + exact cache miss`，并叠加 run-level 500 deep source error signal；最后一项的逐场 attribution 保留 `UNKNOWN`。

## 4. 当前 11 场逐场根因矩阵

表内 `历史` 只把已有 canonical ID 的 store query 当作正式 exact query。`条件 store signal` 仅用于展示同一 competition 下已有 canonical 历史的 recency/coverage，**未将当前 500 display name 提升为 identity，也未写 alias**。

| fixture | competition resolution | home / away exact identity | historical store / recency | cache | live source | authoritative gate category |
|---|---|---|---|---|---|---|
| `500-1363834` 国际图尔库 vs 库奥皮奥 | `competition:finland-veikkausliiga`，exact registry；251 条，CURRENT | home unresolved；away `team:finland:kuopion-ps`，`reviewed_canonical_provider_crosswalk` | away exact 48，latest 08-01，约 30 日；条件 signal `team:finland:inter-turku` 48，latest 08-02，约 29 日 | exact entry ABSENT | Nowscore NO_EXACT；500 deep 为 run-level error，逐场 UNKNOWN | `CURRENT_SOURCE_NAME_MISMATCH` |
| `500-1363823` 赫尔辛基火花 vs TPS图尔库 | 同上 | home `team:finland:gnistan`，reviewed crosswalk；away unresolved | home exact 47，latest 08-01，约 30 日；Finland history team list 没有可 exact 查询的 TPS row | ABSENT | 同上 | `MULTI_CAUSE`：identity + TPS history coverage evidence |
| `500-1414254` 莱切 vs 罗马 | `competition:italy-serie-a`，exact registry；历史 0 | home/away 双 unresolved | competition eligible history 0；pair query blocked before IDs | ABSENT | 同上 | `MULTI_CAUSE`：identity + historical coverage |
| `500-1362759` 天狼星 vs 马尔默 | `competition:sweden-allsvenskan`，exact registry；359 条，CURRENT | home `team:ik-sirius`，competition exact name；away unresolved | home exact 45，latest 08-03，约 28 日；条件 signal `team:sweden:malmo-ff` 45，latest 08-02，约 29 日 | ABSENT | 同上 | `CURRENT_SOURCE_NAME_MISMATCH` |
| `500-1427969` 奥萨苏纳 vs 赫塔费 | `competition:spain-la-liga`，exact registry；历史 0 | 双 unresolved | competition eligible history 0，当前 season source 仍未导入成 eligible rows | ABSENT | 同上 | `MULTI_CAUSE`：identity + historical coverage |
| `500-1414155` 亚特兰大 vs 博洛尼亚 | `competition:italy-serie-a`，exact registry；历史 0 | 双 unresolved | competition eligible history 0 | ABSENT | 同上 | `MULTI_CAUSE`：identity + historical coverage |
| `500-1416881` 第戎 vs 圣埃蒂安 | `competition:france-ligue-2`，exact registry；历史 0 | 双 unresolved | competition eligible history 0 | ABSENT | 同上 | `MULTI_CAUSE`：identity + historical coverage |
| `500-1420346` 阿斯顿维拉 vs 阿森纳 | `competition:england-premier-league`，exact registry；历史 0 | 双 unresolved | competition eligible history 0 | ABSENT | 同上 | `MULTI_CAUSE`：identity + historical coverage |
| `500-1438077` 本菲卡 vs 埃斯托里尔 | `competition:portugal-primeira-liga`，exact registry；370 条但 STALE | 双 unresolved | 条件 signal：`sport-lisboa-e-benfica` 34、`gd-estoril-praia` 38，均 latest 05-16，至比赛约 107 日，超过 60 日 | ABSENT | 同上 | `MULTI_CAUSE`：identity + history recency |
| `500-1438078` 布拉加 vs 吉马良斯 | 同上 | 双 unresolved | 条件 signal：`team:portugal:braga` 4 条且 latest 04-26；`sporting-de-braga` 34 条、`vitoria-guimaraes` 38 条，均 latest 05-16；均不满足 current 60 日 freshness，且一个候选低于 minimum 5 | ABSENT | 同上 | `MULTI_CAUSE`：identity + history recency/quantity |
| `500-1427965` 巴塞罗那 vs 巴列卡诺 | `competition:spain-la-liga`，exact registry；历史 0 | 双 unresolved；registry 有 Barcelona canonical row，但当前 500 名称没有 exact reviewed provider row | competition eligible history 0 | ABSENT | 同上 | `MULTI_CAUSE`：identity + historical coverage |

逐场 identity evidence 的原始 side 结果均保留在 JSON 矩阵；共同状态为：

- 3 场 `PARTIAL`：`500-1363834`、`500-1363823`、`500-1362759`；3 个已解析 side 分别是 KuPS、Gnistan、Sirius；
- 8 场 `UNRESOLVED`；
- 11 场 `reason_codes=[IDENTITY_UNAVAILABLE]`；
- 11 场均无 `structured_500_provider_team_ids`；
- 11 场均不在 `current_match_identity_evidence.json` 的 3 条已审计 current fixture 中；
- 11 场均没有 `verified_project_provider_crosswalk` 的 exact current-name row；
- 11 场均没有 exact recent-form cache entry。

## 5. 根因分类与 primary blocker

为避免把不同层级混成一个数字，本轮保留两个分布：

### 5.1 端到端 availability 分类

| category | fixture count |
|---|---:|
| `MULTI_CAUSE` | 11 |

每一场都同时缺少 exact identity 和可用的 current recent-form acquisition path；run-level 500 error 没有逐场 envelope，因此不将 `LIVE_RECENT_FORM_SOURCE_OUTAGE` 单独归为 11 个 fixture-level root。

### 5.2 authoritative history gate attribution

| category | fixture count | fixtures |
|---|---:|---|
| `CURRENT_SOURCE_NAME_MISMATCH` | 2 | `500-1363834`、`500-1362759` |
| `MULTI_CAUSE` | 9 | `500-1363823`、意甲 2 场、西甲 2 场、法乙 1 场、英超 1 场、葡超 2 场 |

这里的 2 场表示：competition history 处于 CURRENT，另一 side 已有 exact historical evidence，当前失败点集中在一个 500 display name 没有 reviewed exact mapping。9 场还叠加了 competition-level history coverage、side history 缺失、或 60 日 freshness/最低样本量问题。

### 5.3 分类为 0 的纯根因

- `IDENTITY_RESOLVER_GAP`：**作为实现 defect 未被证据确认**。resolver 按 exact ladder fail-closed 返回 `UNRESOLVED`；系统层 primary blocker 仍归入 `IDENTITY_RESOLVER_GAP`，含义是 current-source-to-canonical evidence coverage gap，不等于 resolver 代码错误。
- `COMPETITION_MAPPING_GAP`：0。当前 11 场涉及的 7 个 competition ID 全部存在于 coverage registry。
- `HISTORICAL_COVERAGE_GAP`：0 个纯案例；历史缺口只作为 `MULTI_CAUSE` 的独立 co-blocker。
- `HISTORY_RECENCY_GAP`：0 个纯案例；葡超是 identity + recency/quantity 的 `MULTI_CAUSE`。
- `CACHE_COVERAGE_GAP`：0 个纯案例；cache miss 是 11 场共同暴露条件，不足以单独解释 gate 分布。
- `LIVE_RECENT_FORM_SOURCE_OUTAGE`：0 个纯案例；当前只保留 run-level `Connection refused`，逐 fixture attribution 为 `UNKNOWN`。

### 5.4 项目级决策

**primary blocker：**

`IDENTITY_RESOLVER_GAP / EXACT_CANONICAL_TEAM_ID_COVERAGE`

具体指：当前 500 schedule 只提供 display names；11 场中的一方或双方没有 reviewed exact evidence 映射到 canonical `team:*` ID。由于 Nowscore 没有 exact match、500 deep 当前运行有 source error、recent-form cache 没有目标 entry，identity gate 直接转化成当前端到端 availability loss。

**最小 remedy category：**

`IDENTITY_EVIDENCE_COVERAGE_CLOSURE`：未来只做 bounded、可审计的 provider-ID 或 reviewed crosswalk evidence closure，并继续使用现有 fail-closed exact ladder；同时把 `NEXT_DAY_SOURCE_OBSERVABILITY` 作为独立的 CYCLE_DEGRADED 诊断项。当前 milestone 不实现这两个 remedy。

**证据否决路线：**

- 手工为这 11 场补 alias；
- 启动 ID-AUTO-2；
- 启动 PRED-AVAIL-3 provider hopping；
- 新增 provider 或把低价 API 直接接入 production；
- fuzzy、LLM、transliteration、kickoff proximity 猜 identity；
- 用 market-only 生成 recent form 或解除 `MISSING_RECENT_FORM`；
- 改 Champion、model、health rule、frozen history、prospective ledger 或 frontend；
- 把 `coverage UNSUPPORTED` 解释成 Champion blocked；
- 把 2026-09-01 的 zero universe 当成合法“无赛程”。

## 6. CYCLE_DEGRADED：2026-09-01 单独判断

证据：`D:\MyProject\football-betting-oneshot-main\data\product_runtime\latest_cycle.json` 与 `D:\MyProject\football-betting-oneshot-main\data\prediction_universe\2026-09-01.json`。

- 运行窗口：2026-08-31 00:40:07..00:43:23（Asia/Shanghai）；
- `next_universe`：`DEGRADED`、return code 1、`match_count=0`、`refresh_status=failed_kept_previous_workspace`；
- 9/1 persisted universe：`status=FETCH_FAILED`、`fixture_count=0`、`source=sporttery.cn`、`error=FULL_SCHEDULE_FETCH_FAILED`；
- 下游 `next_base_jobs`：`BLOCKED_UNIVERSE`；
- 下游 `next_base_prediction`：`failure_reasons={BLOCKED_UNIVERSE:1}`；
- `daily_schedule_workspace.py` 的代码路径是先试 Sporttery，再试 trade.500 fallback；该次运行没有形成 usable payload。

**结论：**

- 已观察到的是 `NEXT_UNIVERSE_FETCH_FAILURE`，属于 source/pipeline failure state；
- “赛程发布时间尚早”标记为 `UNKNOWN`：当前持久证据没有 raw upstream response/status、HTTP detail 或 release SLA；
- `next_universe=0` 不是已验证的合法空赛程；
- 该问题与 2026-08-31 当前 11 场的 identity/recent-form availability 分开计数、分开处理，不纳入当前 11 场 root distribution。

## 7. Provider / identity landscape（只用于路线判断）

由于 primary blocker 会影响 identity architecture、future data source 和成本，本轮在推荐前完成了 `landscape → shortlist → compare → bounded validation → reuse/adopt` 的外部横向研究。Agent-Reach 通过 `uvx` doctor；网页通过 Jina Reader；GitHub 通过 `gh`；中文社区通过公开 V2EX API/网页；Reddit backend 当前 doctor 为 `off`，因此 Reddit 只使用公开可读搜索结果，不写入或登录平台。

外部复核入口：

- 开源/历史数据：[OpenFootball](https://github.com/openfootball)、[Football-Data](https://www.football-data.co.uk/data)、[Football-Data usage terms](https://www.football-data.co.uk/help_footballdata.php)、[StatsBomb Open Data](https://github.com/statsbomb/open-data)。
- identity/crosswalk：[Reep identity register](https://github.com/withqwerty/reep)。
- 聚合与失败案例：[soccerdata 文档](https://github.com/probberechts/soccerdata/blob/master/docs/intro.rst)、[soccerdata issue #884](https://github.com/probberechts/soccerdata/issues/884)。
- API 与成本：[football-data.org pricing](https://www.football-data.org/pricing)、[API-Football pricing](https://www.api-football.com/pricing)、[Sportmonks Football API](https://www.sportmonks.com/football-api/)、[TheSportsDB API guide](https://www.thesportsdb.com/docs_api_guide)。
- 专业 feed：[Sportradar Soccer API overview](https://developer.sportradar.com/soccer/reference/soccer-overview)、[Stats Perform developer portal](https://developer.statsperform.com/)。
- 独立实践、失败记录与中文社区：[Reddit sports analytics API discussion](https://www.reddit.com/r/sportsanalytics/comments/1tibvri/football_api_for_analytic_dashboard/)、[V2EX 足球 API 讨论](https://www.v2ex.com/t/887548)、[TRAE 社区数据抓取实践](https://forum.trae.cn/t/topic/18760)、[football-data.io incident history](https://footballdata.io/status/incidents/)、[EntitySport missing-data practice](https://www.entitysport.com/blog/handling-missing-match-data/)。

| 路线 | 公开证据与优势 | 对本项目的缺口 | 本轮决定 |
|---|---|---|---|
| 现有 500/Sporttery + Football-Data/OpenFootball | Football-Data 提供免费历史结果/赔率并宣称至少每周两次更新；OpenFootball 的 `football.json`/欧洲仓库为 CC0/open public-domain 数据；适合低成本历史层 | current fixture live stability、跨 source exact ID、season freshness 仍需项目自建 evidence gate；Football-Data terms/attribution 仍需按项目 manifest 审核 | **保留现有路线；不新增 provider** |
| 开源 identity register / crosswalk | Reep 提供跨 Transfermarkt、FBref、UEFA、Sofascore 等 30+ provider 的稳定 ID crosswalk，并强调 verified evidence | 它是 identity layer，不是当前赛程/recent-form feed；需要单独验证 coverage、版本和许可边界 | 作为未来研究输入；本轮不接入 production |
| 开源 scraper 聚合 | `soccerdata` 提供统一接口、cache 和多个站点 reader | 官方文档明确 built-in leagues 有限、custom league 没有正确性保证；WhoScored/FBref 反爬与 rate-limit 使 scraper 具有维护和 CI 风险；GitHub issue #884 记录多个主流联赛 scraper 失效 | 作为失败案例观察；不作为 current-day fallback |
| 低价 API：football-data.org / API-Football / TheSportsDB | 有免费或低价方案；官方公开限额/价格，例如 football-data.org Free 12 competitions、API-Football Free 100 req/day、TheSportsDB Free 30 req/min | coverage/season depth、commercial terms、provider ID crosswalk 和 exact current fixture validation 仍需 bounded validation；低价不等于覆盖本项目 7 个 competition | 不启动 provider hopping；不新增 |
| 中端统一 API：Sportmonks | 官方公开 Starter €29/月、5 leagues、full feature access，提供 fixture/team/history/odds 等统一 JSON | 仍是 provider dependency、按 league 计价；单凭产品页尚不足以证明当前 500 names 到本项目 canonical IDs 的 exact bridge | shortlist only；当前不采购、不接入 |
| 专业/企业 feed：Sportradar / Stats Perform | 官方资料强调大范围足球/多运动覆盖、coverage matrix、赛事与实时 feed | 公开页面没有适合本 milestone 的自助成本；合同、权利和 procurement 成本显著高于当前 bounded audit | 记录为长期 benchmark；当前不改变架构 |
| 研究/事件数据：StatsBomb Open Data | GitHub 明确提供有限 competition 的研究数据，要求来源声明/Logo；适合研究和回放 | 不是 current-day fixture/recent-form feed，且覆盖有限、许可边界不同 | 只作 research input，不解除生产 gate |

外部失败/实践信号：

- GitHub `soccerdata` issue tracker 持续存在 FBref/WhoScored/league scraper failure 与 unsupported league 问题；
- V2EX 关于足球 API 的讨论提醒 current API 需要核验覆盖，另有动态页面/反爬导致“页面可见但直抓为空”的实践；
- Reddit 的 sports analytics/webdev 讨论反复提到 API free tier、ID 稳定性、历史数据为空和多源 reconciliation 的成本；这些是独立实践信号，不作为本项目生产事实。

本轮横向研究的结论不是“选某个新 provider”，而是：**没有证据表明 provider hopping 能比 identity evidence closure 更小、更快、更可审计地解决当前 11 场；免费/开源路线同样需要处理 canonical identity、history recency 和许可边界。** 任何未来 provider/identity architecture 变更仍需单独 milestone、全景比较和 bounded validation。

## 8. Current-state fusion 与 STOP

按用户指定的最小 current-state fusion：

- `PROD-WRITE-1 = SEALED / ACCEPTANCE PASS`；对应远端 PR #131/#133 已合并，PR #133 记录 post-merge production verification run `33322458082`；
- `CURRENT = PRED-COVERAGE-TRUTH-1`；
- `PARALLEL RESEARCH = GLOBAL-MARKET-0`；
- 本 milestone 的实现范围只有根因审计、矩阵、项目级路线判断和证据固化；
- 本 milestone 结束状态：`PRED-COVERAGE-TRUTH-1 = READY_FOR_ACCEPTANCE`；等待独立验收，不标记 SEALED。

STOP。
