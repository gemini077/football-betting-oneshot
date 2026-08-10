# Current Football Data Capability Audit

检查范围严格限制为：`scripts/` 下相关 provider/identity/model input 文件、`schemas/`、`data/provider_match_crosswalk.json`、`data/model_benchmarks/` 与相关测试。没有扫描整个历史 `data/` 目录。

审计基线：PR #64 合并后的 `origin/main` merge SHA `a16e3c40f581ba749fa107f94280460ce6dee435`。本审计只描述现状，不把任何新 Phase 2A contract 当作已经可供 Champion 使用的 feature。

## 现有字段与来源

| Capability / field | Current evidence | Source(s) | Current status | Champion deterministic input? |
| --- | --- | --- | --- | --- |
| `canonical_match_id` | `scripts/match_identity.py` 生成 `FBOS-...` 形式 ID；provider ID 另存 | Nowscore/500 match identity helpers | 已有最小 match identity；禁止重写 | 作为已有 match/workspace identity 使用，非新 feature |
| Provider match crosswalk | `data/provider_match_crosswalk.json` schema v1，当前 `matches` 为空 | provider match registry | 已有容器，当前无持久化绑定 | 否 |
| Team name / alias | `scripts/team_identity.py` + `data/team_aliases.json` | 主要是 Nowscore/500/报告输入中的名称 | 有旧的名称归一化；没有统一 `canonical_team_id`、provider team ID、国家/性别/队伍层级 | 旧 helper 会参与已有赛事/球队选择；Phase 2A 不改它 |
| Competition / season text | snapshots、报告和 schedule context 中存在字符串 | Nowscore/500/ESPN | 没有统一 `canonical_competition_id` / `canonical_season_id` | 仅作为已有 context，不是新标准化 feature |
| Results | `shuju.recent_form`、ESPN `lastFiveGames` 和 postmatch 数据 | 500.com、ESPN | 部分可用，窗口和 provenance 不统一 | 是；Champion 使用 recent form 的实际进球/失球路径 |
| GF / GA | recent-form rows and postmatch facts | 500.com、ESPN、Nowscore context | 部分可用；没有统一 per90/窗口合同 | 是，以 Champion 现有 form 输入路径为限 |
| xG | `parser.py`/risk/report 中有 `expected_goals` 等模型或叙事字段 | 主要是内部计算/报告语义；未发现 provider-specific normalized xG snapshot | 没有经定义、可追溯的 provider xG 层 | 否；任何新 xG 都不得自动进入 Champion |
| Shots / shots on target | postmatch/report parsing keys may exist | provider/report payloads | 未验证为稳定、逐队、可复现 snapshot | 否 |
| Lineup | `scripts/prematch_fundamentals.py` 可从 ESPN summary 提取 roster count/部分展示文本 | ESPN summary | 不是 `projected/confirmed/unavailable` lineup contract；无 canonical player identity | 否 |
| Injuries / availability | ESPN summary 在有结构化名单时可计数；无名单时保留叙事/unknown 语义 | ESPN summary；报告 narrative | 没有状态枚举、证据、冲突保留和 source timestamp 的 normalized snapshot | 否 |
| Player identity | roster/player names may appear in report payloads | ESPN and raw provider payloads | 没有 canonical player registry；DOB/nationality 不稳定 | 否 |
| Nowscore market data | deep snapshot merge and market reference path | Nowscore | 当前正式 market input；不是 Phase 2A feature | 是，Champion existing market path |
| Nowscore recent form | `scripts/automatic_model_core.py` / `prematch_fundamentals.py` | Nowscore `recent_form` when present | source-labeled but not the new versioned foundation contract | 是，Champion existing form path |
| 500 deep snapshot | fallback/non-market form path | 500.com | source-labeled fallback; no new identity or xG contract | 是，Champion existing fallback path |
| ESPN scoreboard/summary | timed-event selection, venue, roster/injury narrative | ESPN | context/enrichment only; not a broad foundation | No for new fields |
| Report narrative | `prematch_fundamentals.items`, `nowscore_context`, postmatch dashboard | Nowscore/500/ESPN parsed text | presentation/report evidence; not equivalent to a validated feature | 否 |
| Deterministic model input | governance input projection and fixed fixture tests | existing model governance code/tests | existing path is governed; Phase 2A files are outside model source fingerprint | 是，仅现有 governed fields |

## Raw / normalized / validated separation

当前代码已经有 provider payload、report parsing 和 deterministic input 的不同路径，但没有一个完整、versioned football data foundation。Phase 2A 补齐的目标边界是：

```text
Raw Evidence
  provider payload, source record id, source timestamps, raw digest

Normalized Football Data
  versioned contracts, canonical identities, provider-specific xG, lineup and availability records

Validated Features
  quality/freshness assessed records; not yet model-validated

Future Model
  current Champion only; no Phase 2A dependency
```

## Deterministic input audit

`automatic_model_core.py` 的当前 Champion 使用已有 recent-form/market paths。`model_source_fingerprint` 只对治理定义的 deterministic source components 计算 fingerprint，Phase 2A 新增的 contracts、registries、fixtures 和 docs 不在其中。Phase 2A 的 isolation test 将修改这些新文件后再次比较：Champion core SHA、fixed fixture digest、source fingerprint 和 prediction ID。

因此本阶段的正确结论不是“已经有 xG/lineup/injury 能力”，而是：已有 Nowscore/500 results/form 和 market 输入可审计地继续运行；xG、shots、lineup、availability、player identity、competition identity 仍需通过新合同逐步建立。

## Existing match identity reuse decision

复用：

- `scripts/match_identity.py` 的 `canonical_match_id` 语义；
- `scripts/provider_match_registry.py` 的 provider match crosswalk 容器；
- `data/provider_match_crosswalk.json` 的现有文件位置。

不修改：

- `scripts/team_identity.py` 旧选择器；
- `data/team_aliases.json` 旧模型/报告别名表；
- 现有 `automatic_model_core.py`、benchmark 定义和固定 fixture。

Phase 2A 的 `canonical_team_id` 和 alias registry 是隔离的新身份层；不能把字符串相似度结果当作已有 canonical match identity 的替代物。
