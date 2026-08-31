# PRED-NOWSCORE-BIND-1 — Nowscore Source-Present / Binding-Failed Closure

状态：`READY_FOR_ACCEPTANCE`

审计业务日：`2026-08-31`

本文件只固化上一轮 `PRED-NOWSCORE-BIND-1` 只读审计结果，不实现修复，不改变生产状态。

## 1. 结论摘要

### 1.1 12 场结论

- 历史 schedule intake：`0/12` binding success，12 场均为 `NO_EXACT_MATCH`。
- 当前复核的 `bf1.js`：`12/12 SOURCE_PRESENT`。
- 当前 resolver 只读重算：`8/12 EXACT_MATCH`，`4/12 BINDING_FAILED`。
- 当前公开 Nowscore market page：`12/12` 可取得。
- 当前公开 Nowscore analysis page：`12/12` 可取得。
- 12 场实际开球时间均为 `2026-09-01 00:00–03:30 +08:00`，而竞彩 business date 是 `2026-08-31`。

### 1.2 根因分类

总体分类：`MULTI_CAUSE`

`0/12` intake binding 的 primary blocker：

```text
NOWSCORE_SCHEDULE_HORIZON_GAP
```

其具体表现为 business date 与实际 calendar kickoff date 跨日，
而当前 intake 只抓滚动的 `bf1.js`，没有可靠的 future-fixture date scope。
这同时表现为：

```text
NOWSCORE_DATE_SCOPE_OR_TIMEZONE_GAP
```

现有证据不支持把它归因为 Asia/Shanghai 的算术转换错误：当前 12 场 provider kickoff 与目标 kickoff 全部相差 `0` 分钟。

在目标比赛出现在当前 `bf1.js` 后，仍有 4 场因名称差异被 exact-only matcher 拒绝，归类为：

```text
NOWSCORE_NAME_NORMALIZATION_GAP
```

### 1.3 最小 next remedy category

唯一 next remedy category：

```text
NOWSCORE_SCHEDULE_HORIZON_GAP
```

边界是 future-fixture intake surface 与 deterministic ID propagation 的审计/修复类别；本交付不实现它，也不修改 resolver、endpoint、alias、parser、provider 或 source order。

## 2. 证据边界与可重放性

用户指定的历史文件：

```text
D:\MyProject\football-betting-oneshot-main\data\schedule_updates\20260831_002646\20260831_002646_sporttery_2026-08-31.json
```

不在当前 checkout 中，历史 753 条 `bf1.js` raw 也没有持久化。因此本报告不把“当时逐行 source missing”写成已证明事实。

最近的可复核持久化 intake 是：

```text
D:\MyProject\football-betting-oneshot-main\data\schedule_updates\20260830_164007\20260830_164007_sporttery_2026-08-31.json
```

其中为 `schedule_count=750`、12 场、`bound=0`、`ambiguous=0`、`missing=12`，12 场全部 `NO_EXACT_MATCH`。用户给出的 `753` 作为 intake 聚合事实保留，但没有被伪装成当前 checkout 可重放的 raw。

当前复核 raw 临时保存在：

```text
C:\Users\Administrator\AppData\Local\Temp\football-betting-nowscore-audit\bf1_current.js
```

当前 `bf1.js` 复核结果为 366/367 条滚动变化；一次稳定复核为 367 条，12 个目标 ID 全部出现。当前 raw 的日期范围为：

- `2026-08-31 09:00–23:45 +08:00`
- `2026-09-01 00:00–10:00 +08:00`

## 3. 12 场 source-present vs binding-success 矩阵

说明：

- `current bf1` 是当前 raw 的 `SOURCE_PRESENT` 状态，不等同于历史 00:26 intake raw 的逐行证明。
- `当前只读重算` 没有调用 `prebind_match()`，没有写入 `provider_match_crosswalk.json`；`would bind` 表示相同 resolver 在当前 raw 上会返回 `EXACT_MATCH`。
- 对 4 个 `NO_EXACT_MATCH`，resolver 最终 confidence 是 `null`；表中的 `0.60` 是单侧名称被过滤前的候选 confidence。

| # | 500 比赛 | 目标开球 | current `bf1.js` | Nowscore ID | provider home → away | provider 开球 | H/A similarity | Δ kickoff | confidence | 当前只读重算 | 历史 intake |
|---:|---|---|---|---:|---|---|---:|---:|---|---|---|
| 1 | `500-1363834` 国际图尔库 – 库奥皮奥 | 09-01 00:00 | `SOURCE_PRESENT` | 2913703 | 图尔库国际 (`Inter Turku`) → 古比斯 (`KuPs`) | 00:00 | 0 / 1 | 0m | `null`；候选 0.60 | `BINDING_FAILED`：home `<0.75` | `BINDING_FAILED`：`NO_EXACT_MATCH` |
| 2 | `500-1363823` 赫尔辛基火花 – TPS图尔库 | 09-01 00:00 | `SOURCE_PRESENT` | 2913701 | 格尼斯坦 (`Gnistan Helsinki`) → TPS土尔库 (`TPS Turku`) | 00:00 | 1 / 0 | 0m | `null`；候选 0.60 | `BINDING_FAILED`：away `<0.75` | `BINDING_FAILED`：`NO_EXACT_MATCH` |
| 3 | `500-1414254` 莱切 – 罗马 | 09-01 00:30 | `SOURCE_PRESENT` | 2993771 | 莱切 (`Lecce`) → 罗马 (`AS Roma`) | 00:30 | 1 / 1 | 0m | 1.00 | `EXACT_MATCH`，would bind | `BINDING_FAILED`：`NO_EXACT_MATCH` |
| 4 | `500-1362753` 佐加顿斯 – 米亚尔比 | 09-01 01:00 | `SOURCE_PRESENT` | 2912252 | 尤尔加登 (`Djurgardens`) → 米亚尔比 (`Mjallby AIF`) | 01:00 | 0 / 1 | 0m | `null`；候选 0.60 | `BINDING_FAILED`：home `<0.75` | `BINDING_FAILED`：`NO_EXACT_MATCH` |
| 5 | `500-1362759` 天狼星 – 马尔默 | 09-01 01:00 | `SOURCE_PRESENT` | 2912258 | 天狼星 (`IK Sirius FK`) → 马尔默 (`Malmo FF`) | 01:00 | 1 / 1 | 0m | 1.00 | `EXACT_MATCH`，would bind | `BINDING_FAILED`：`NO_EXACT_MATCH` |
| 6 | `500-1427969` 奥萨苏纳 – 赫塔费 | 09-01 01:30 | `SOURCE_PRESENT` | 3013667 | 奥萨苏纳 (`Osasuna`) → 赫塔菲 (`Getafe`) | 01:30 | 1 / 0 | 0m | `null`；候选 0.60 | `BINDING_FAILED`：away `<0.75` | `BINDING_FAILED`：`NO_EXACT_MATCH` |
| 7 | `500-1414155` 亚特兰大 – 博洛尼亚 | 09-01 02:45 | `SOURCE_PRESENT` | 2993766 | 亚特兰大 (`Atalanta`) → 博洛尼亚 (`Bologna`) | 02:45 | 1 / 1 | 0m | 1.00 | `EXACT_MATCH`，would bind | `BINDING_FAILED`：`NO_EXACT_MATCH` |
| 8 | `500-1416881` 第戎 – 圣埃蒂安 | 09-01 02:45 | `SOURCE_PRESENT` | 2997701 | 第戎 (`Dijon`) → 圣埃蒂安 (`Saint Etienne`) | 02:45 | 1 / 1 | 0m | 1.00 | `EXACT_MATCH`，would bind | `BINDING_FAILED`：`NO_EXACT_MATCH` |
| 9 | `500-1420346` 阿斯顿维拉 – 阿森纳 | 09-01 03:00 | `SOURCE_PRESENT` | 3003860 | 阿斯顿维拉 (`Aston Villa`) → 阿森纳 (`Arsenal`) | 03:00 | 1 / 1 | 0m | 1.00 | `EXACT_MATCH`，would bind | `BINDING_FAILED`：`NO_EXACT_MATCH` |
| 10 | `500-1438077` 本菲卡 – 埃斯托里尔 | 09-01 03:15 | `SOURCE_PRESENT` | 3023461 | 本菲卡 (`Benfica`) → 埃斯托里尔 (`Estoril`) | 03:15 | 1 / 1 | 0m | 1.00 | `EXACT_MATCH`，would bind | `BINDING_FAILED`：`NO_EXACT_MATCH` |
| 11 | `500-1438078` 布拉加 – 吉马良斯 | 09-01 03:15 | `SOURCE_PRESENT` | 3023462 | 布拉加 (`Sporting Braga`) → 吉马良斯 (`Vitoria Guimaraes`) | 03:15 | 1 / 1 | 0m | 1.00 | `EXACT_MATCH`，would bind | `BINDING_FAILED`：`NO_EXACT_MATCH` |
| 12 | `500-1427965` 巴塞罗那 – 巴列卡诺 | 09-01 03:30 | `SOURCE_PRESENT` | 3013665 | 巴塞罗那 (`FC Barcelona`) → 巴列卡诺 (`Rayo Vallecano`) | 03:30 | 1 / 1 | 0m | 1.00 | `EXACT_MATCH`，would bind | `BINDING_FAILED`：`NO_EXACT_MATCH` |

机器可读矩阵：

```text
D:\MyProject\football-betting-oneshot-main\data\football_data\pred_nowscore_bind_1\root_cause_matrix_2026-08-31.json
```

## 4. `bf1.js` intake surface 判断

`D:\MyProject\football-betting-oneshot-main\scripts\nowscore_markets.py` 当前将 `https://live.nowscore.com/data/bf1.js` 作为唯一 schedule surface，并只添加 cache-buster；没有传入 business date 的可靠选择器。

结论：

```text
对 2026-08-31 business-date 的 future fixture binding：bf1.js 是不足且错误的唯一 intake surface。
对实时滚动赛程本身：bf1.js 仍是可用 live feed。
```

官方页面存在按日期的“近日赛程”入口，包括 `2026-09-01`：[Nowscore 近日赛程页面](https://live.nowscore.com/schedule.aspx?f=sc1)。对应 `data/sc1.js` 使用 `09-01` 日期形态，并暴露 match ID/team ID；但现有 `parse_schedule_js()` 只接受完整的 `YYYY,M,D,h,m,s` 形态。本轮没有改 parser，也没有把 sc1 宣布为可用替代方案。

## 5. Deterministic provider-ID route

结论：

```text
存在 Nowscore 内部 deterministic provider-ID route；没有发现 500 shujuId 到 Nowscore ID 的直接确定性映射。
```

已确认的 Nowscore route：

```text
bf1.js row[0]                         → Nowscore match ID
/odds/match/{nowscore_id}.htm         → 比赛 market page
/analysisJs/data{nowscore_id}.js      → 比赛 analysis data
```

market page 还暴露 `hide_scheduleId`、`hide_matchTime` 和双方身份，可作为 ID 后的同场验证。当前 `D:\MyProject\football-betting-oneshot-main\data\provider_match_crosswalk.json` 的 `matches` 为空，因此本批次没有现成 stored provider binding 可以复用。

## 6. Stored binding 与 source routing

- `provider_match_registry.py` 具备 lookup/record 能力，但本批次 registry 为 0 条。
- `prebind_match()` 只有 `EXACT_MATCH` 才记录 Nowscore binding；历史 0/12 没有产生 `nowscoreId`。
- `fetch_match_markets()` 在 schedule fetch 抛异常时才会尝试 stored binding；partial/empty schedule 本身不会自动走 stored binding。
- `base_prediction_runner.py` 已经在存在有效 `nowscoreId` 时优先尝试 Nowscore；本批次因状态为 `NO_EXACT_MATCH`，Nowscore 被跳过，500 deep 才成为后续 fallback。

因此，本问题是 binding/intake 问题，不是 source migration 问题。

## 7. 反证检查

### 7.1 “Nowscore 真 source missing”

不成立为当前样本结论：当前 `bf1.js`、12 个 market page、12 个 analysis page 均存在。历史 00:26 raw 不在仓库，所以历史时点的逐行 source presence 仍是 `NOT_PROVEN`，不能反写成 source missing。

### 7.2 “页面有数据，但程序字段不可稳定获取”

已观察到：

- `bf1.js` 条数随抓取时点变化，且混合两个 calendar date。
- `sc1.js` 的 `09-01` 日期字段不符合当前 parser 的输入形态。
- Nowscore market page 字段不完全一致；例如 `3023461` 的 Asian market 在当前解析结果中没有有效 `yazhi`。
- Nowscore 页面存在不等于全部玩法字段完整。

### 7.3 Fetch reliability

- Nowscore `bf1.js`：本轮已取得 3/3 成功样本，稳定样本解析 367 条，12 个目标 ID 全部出现。
- Nowscore market/analysis：12/12 route 可取得。
- 500 canonical schedule：持久化 intake 已给出 12 场、`shujuId`、business date、kickoff、官方 SPF/RQSPF。
- 500 deep：既有状态记录过 runtime unavailable；此前有限代表样本可取得并解析，但不足以证明长期 SLA。

### 7.4 500 是否在关键字段上更稳定

是，至少在本样本的 canonical schedule identity 上更稳定：500 直接提供竞彩 business date、`shujuId`、目标 kickoff 和官方竞彩字段；Nowscore 的优势是在已取得 match ID 后提供结构化 market/analysis 数据。

这不足以支持把 Nowscore 提升为唯一 schedule source，也不足以支持调整 source order。

### 7.5 Rights / licensing / maintenance

Nowscore 官方页面提供数据接口合作信息，但公开可访问不等于已经具备生产抓取、再分发许可或 SLA。授权边界、商业使用条款、长期维护承诺仍未证明：[Nowscore 官方数据接口页面](https://www.nowscore.com/diaoyong.htm)。

## 8. Provisional source role

```text
500 canonical schedule：暂定 canonical schedule/business-date anchor。
Nowscore：暂定 secondary market/analysis enrichment，前提是已有 deterministic match ID。
500 deep：保留 fallback/secondary role；当前证据不足以升级为唯一深度 source。
```

本结论不改变现有 source order、provider、Champion 或 production。

## 9. UNKNOWN / NOT PROVEN

1. 指定 `20260831_002646` 的 753 条历史 `bf1.js` raw 不在当前仓库，无法直接证明当时每个目标 ID 的逐行缺失。
2. `sc1.js` 是否覆盖全部 12 场 future fixture，当前仅有有限响应证据，未证明完整覆盖。
3. Nowscore future fixture route 的发布时间、完整性、稳定性和 SLA 未证明。
4. Nowscore 自动抓取与生产再分发的授权边界未证明。
5. 500 deep 全部页面的长期可用性、字段完整性和 per-fixture outage attribution 未证明。
6. 500 `shujuId` 到 Nowscore match ID 的 deterministic cross-provider mapping 未发现。

## 10. Scope guard 与 STOP

本交付没有：

- 修改 resolver、endpoint、alias、parser、source order、provider、Champion 或 production；
- 修改 frozen history、prospective ledger 或 PR #134；
- 实现 future fixture remedy；
- 新增依赖或数据库结构。

交付状态：

```text
PRED-NOWSCORE-BIND-1 = READY_FOR_ACCEPTANCE
```

STOP：根因已足够明确，停在研究结果固化与远端交付。
