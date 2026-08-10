# Phase 2A Open-Source Discovery

检查日期：2026-08-10（Asia/Shanghai；仓库事实以本地 checkout 和上游公开仓库为准）

## 目的与边界

本次 discovery 的目标是识别可复用的 schema、离线 fixture、provider adapter 参考和未来研究依赖。它不是把任何一个 scraper、第三方评级数据库或事件分析库直接接入 Champion。Phase 2A 的数据流保持：

```text
Raw Evidence -> Normalized Football Data -> Validated Features -> Future Model
```

本阶段不改变正式 Champion、正式 benchmark 定义、prospective boundary 或 deterministic model input。

发现流程先使用 Agent-Reach skill；当前环境未安装 `agent-reach` CLI，`agent-reach doctor --json` 不可执行，因此使用 `gh` 公共仓库 API、各项目官方 README/docs/license 和官方站点作为可审计 fallback。当前环境没有 `grill-me` skill，已按要求记录：

```text
grill-me unavailable in current Codex environment
```

“Active”表示在检查日仍有近期有意义的提交且未归档，不代表生产 SLA。许可证字段记录公开仓库所能确认的 license；ToS、数据源协议和商业再分发权另行判断。

## OSS Discovery Matrix

| Project | Role | Active | License | Useful for us | Production-safe? | Decision |
| ------- | ---- | -----: | ------- | ------------- | ---------------- | -------- |
| [probberechts/soccerdata](https://github.com/probberechts/soccerdata) | 多 provider scraper、schema mapping、research ingestion helper | Yes; latest meaningful repository activity before check date | Apache-2.0 | 可参考 provider 边界、缓存和 DataFrame mapping；能覆盖若干结果、统计和 xG source | No as a blanket dependency; source-specific ToS、scraping fragility and schema drift remain | REFERENCE |
| [statsbomb/open-data](https://github.com/statsbomb/open-data) → [hudl/open-data](https://github.com/hudl/open-data) | 公开研究数据、event/lineup/xG fixture | Yes; maintained redirect target | `LICENSE.pdf`; repository API does not assert a standard SPDX license | 高价值离线 schema、研究 fixture 和测试输入；覆盖是选定比赛/赛事，不是当前全赛事 | Not for unrestricted production/commercial redistribution; attribution and User Agreement review required | ADAPT |
| [statsbomb/statsbombpy](https://github.com/statsbomb/statsbombpy) → [hudl/statsbombpy](https://github.com/hudl/statsbombpy) | StatsBomb API/open-data Python client | Yes; active upstream | Repository license declaration not confirmed in the inspected root metadata | 可参考 API/open-data boundary 和 response shape | No new runtime dependency in Phase 2A; credentials, paid API and agreement boundary are unnecessary here | REFERENCE |
| [PySport/kloppy](https://github.com/PySport/kloppy) | vendor-independent event/tracking schema | Yes; BSD-3-Clause | BSD-3-Clause | 未来多个 event provider 时可作为 schema reference | Not needed as a current dependency; current phase has no multiple real event providers | DEFER |
| [ML-KULeuven/socceraction](https://github.com/ML-KULeuven/socceraction) | SPADL/atomic-SPADL、xT、VAEP、research conversion | Maintained enough for research; README says not actively developed | MIT | 未来 xT/VAEP/SPADL research reference | No as a key production dependency; reproducibility research scope and dependency weight exceed current need | REFERENCE |
| [withqwerty/reep](https://github.com/withqwerty/reep) | football entity register/cross-provider identity concept | Public v1 snapshots; engine is commercially maintained | CC0-1.0 for published snapshots | 可参考 canonical entity、provider crosswalk 和 dated snapshot 设计 | Do not rely on the closed registry builder or silently copy external mappings; provenance review required | DEFER |
| [openfootball/football.json](https://github.com/openfootball/football.json) | 历史赛程与结果 fixture | Active; CC0-1.0 | CC0-1.0 | 离线历史结果 fixture；可帮助测试结果合同 | No xG/lineup/injury/provider IDs；不作为身份事实源 | REFERENCE |
| [schochastics/football-data](https://github.com/schochastics/football-data) | 大规模历史结果与 Parquet research dataset | Public data updates, but latest coverage has a historical cutoff | ODC Attribution License per project README | coverage 和 analytical-store 研究参考 | No as canonical identity or production source; README warns about merge/split/dissolve identity issues and attribution | REFERENCE |
| [Club Elo](https://clubelo.com/Data) | 公开球队 rating source and algorithm reference | Site available; machine-readable redistribution license not clearly stated on inspected pages | Not confirmed for redistribution | 可研究 source/algorithm separation、coverage exclusions和 Elo contract | Do not copy database or expose ratings as normalized fact without rights review | DEFER |
| [Victor-DS/Soccer-Elo-Ratings](https://github.com/Victor-DS/Soccer-Elo-Ratings) | Python Elo algorithm implementation | Public implementation; maintenance/SLA not relied upon | Repository has a license; exact production compatibility not established | 仅可对比 Elo algorithm contract | No key dependency and no rating data redistribution | REFERENCE |
| [DuckDB Parquet documentation](https://duckdb.org/docs/stable/data/parquet/overview) | historical analytical store option | Active official documentation | DuckDB project license; separate from data licenses | filter/projection pushdown、columnar snapshots值得评估 | Not introduced in Phase 2A; JSON immutable snapshots remain the source of truth | DEFER |

本矩阵没有将任何第三方数据库或 scraper 标记为 `ADOPT`。`statsbomb/open-data` 的 `ADAPT` 只表示本仓库会在自己的 provider interface 后面读取离线公开 JSON 作为 research adapter，不等于采纳其商业数据覆盖或把原始数据重新分发为生产数据。

## 重点项目判断

### soccerdata：REFERENCE，不整体引入

[`soccerdata` 官方文档](https://soccerdata.readthedocs.io/en/latest/) 和 README 显示它通过不同 scraper/provider 读取 Club Elo、ESPN、FBref、Football-Data.co.uk、Sofascore、SoFIFA、Understat、WhoScored 等 source，并返回 pandas DataFrame、带缓存。项目是 Apache-2.0，但代码许可证不会替代被抓站点的 ToS、robots/访问限制、数据版权或商业使用条件；其文档也明确要求使用者遵守各网站 ToS，并提醒网站变化会使 scraper 失效。

Phase 2A 对每个 source 单独判断：

| soccerdata source | Acquisition / useful surface | ToS / fragility | Phase 2A decision |
| --- | --- | --- | --- |
| Club Elo | rating page；可参考 Elo source/algorithm boundary | 站点再分发权未确认；coverage 有排除项 | REFERENCE |
| ESPN | schedule、scoreboard、summary、部分 roster/injury facts | 页面/API shape 可能变化；公开 endpoint 不自动等于稳定许可 | REFERENCE |
| FBref | results、tables、部分 player/team statistics | 网页抓取和访问政策需逐项复核；schema 会随页面变化 | REFERENCE |
| Football-Data.co.uk | downloadable historical results/odds | 文件格式稳定性和数据许可需随文件核验 | REFERENCE |
| Sofascore | 丰富赛事/球队/球员页面 | 未确认通用商业抓取许可；网页/API 漂移和限流风险 | DEFER |
| SoFIFA | FIFA game ratings，不是现实比赛事实 | 游戏数据语义不适合作为当前足球事实层 | REJECT |
| Understat | provider-specific xG research input | xG 定义、网页抓取和 ToS 必须单独处理；不得与其他 provider 混均值 | REFERENCE |
| WhoScored | match/team/player statistics | scraping/API stability、ToS 和商业再分发未确认 | DEFER |

结论是参考其 adapter mapping 和缓存思路，逐 source 评估，绝不一次启用全部 scraper；Phase 2A 不增加 `soccerdata` 依赖。

### StatsBomb Open Data / statsbombpy：研究边界

原 `statsbomb/open-data` URL 在检查时指向 `hudl/open-data`。官方 README 描述了 `competitions.json`、`matches`、`events`、`lineups` 和选定的 `three-sixty` JSON；可用赛事/比赛是公开研究数据的一个选择集，不应宣称覆盖全部当前赛事。官方 README 还要求公开研究/分析注明 StatsBomb source 并使用相应 attribution/logo；`LICENSE.pdf` 和 User Agreement 是用途边界，不能因为 GitHub 可见就推断无条件商业使用。

本阶段采用自己的标准化 contract 和离线 fixture adapter：保留 provider、metric definition、source id、captured time、license/attribution metadata；不安装 `statsbombpy`，不访问付费 API，不让 CI 依赖实时外网。

### kloppy / socceraction

[`kloppy` 文档](https://kloppy.pysport.org/user-guide/loading-data/) 的 vendor-independent event/tracking model 对未来多 provider 很有价值，但当前 Phase 2A 没有两个真实 event provider，因此 `DEFER`，避免先引入重量依赖。[`socceraction` README](https://github.com/ML-KULeuven/socceraction) 明确说明项目不再积极开发，主要价值是研究复现；本阶段将它保留为 SPADL、xT、VAEP 的 `REFERENCE`，不成为关键生产依赖。

### Entity resolution、Elo 与 analytical storage

`reep` 的公开 snapshots 说明了跨 Transfermarkt、FBref、UEFA、Sofascore 等 provider 的实体 register/crosswalk 思路，但其构建 engine 不是本仓库可直接审计的开源生产组件，因此只 `DEFER`。`openfootball/football.json` 和 `football-data` 可作为历史结果/覆盖研究 fixture，不能替代 canonical team identity。

Club Elo 的 [`Data`](https://clubelo.com/Data) 和 [`System`](https://clubelo.com/System) 页面分别体现了 rating data 和 Elo algorithm 的区别；Phase 2A 只建立未来 adapter contract，不复制第三方数据库，也不给联赛拍人工系数。DuckDB 官方 Parquet 文档确认了读取、写入和 predicate pushdown 等 analytical-store 能力，但当前 JSON content-addressed snapshot 已满足本阶段规模，数据库迁移留作 decision memo。

## Implementation decision

- Production OSS dependency adopted：0。
- In-house adaptation：1 个 StatsBomb Open Data research adapter；它只适配离线 JSON schema，不改变 Champion。
- Phase 2A.1 hardens that decision to an official-schema-compatible offline
  research adapter: exact match-list selection, nested team/competition/season
  parsing, and official lineup semantics are tested without adding `statsbombpy`
  or a network CI dependency. It is not a current all-competition production
  feed.
- Existing Nowscore/500 data：保留在自己的 provider boundary 内，以 normalized adapter prototype 表达，不把 scraper 依赖带入生产。
- Raw evidence、normalized records 和 future validated features 分层保存；任何新 feature 的 `validated_for_model` 都是 `false`。
- 所有 xG 只保存 provider-specific observation 和定义，不跨 provider 求平均；opponent adjustment 字段先保留 `null`。
- 所有身份无法确认的记录保持 `unresolved`，不会通过字符串相似度自动串队。
