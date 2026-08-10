# Football Data Coverage Matrix

检查日期：2026-08-10。状态只描述当前可复现能力，不代表 provider 对所有赛事、赛季或当前比赛都有覆盖。

状态含义：

- `SUPPORTED`：当前有稳定、可定位的字段和 provenance，可在本 contract 范围内验证。
- `PARTIAL`：有部分字段、部分赛事/窗口或部分结构，但不能声称完整覆盖。
- `MISSING`：当前没有可复用的 normalized capability。
- `UNVERIFIED`：原始 payload 可能出现，但 schema、覆盖或语义尚未验证。

| Competition / provider | Team identity | Results | GF/GA | xG | Shots | Lineup | Injuries | Player identity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Nowscore current snapshots | PARTIAL | PARTIAL | PARTIAL | MISSING | UNVERIFIED | MISSING | MISSING | MISSING |
| 500.com deep snapshots | PARTIAL | PARTIAL | PARTIAL | MISSING | UNVERIFIED | MISSING | MISSING | MISSING |
| ESPN scoreboard / summary | PARTIAL | PARTIAL | PARTIAL | MISSING | UNVERIFIED | PARTIAL | PARTIAL | PARTIAL |
| `data/provider_match_crosswalk.json` | MISSING for team IDs; existing match crosswalk container is empty at baseline | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING |
| StatsBomb Open Data selected research fixtures | PARTIAL; provider IDs preserved and resolver-gated | SUPPORTED for fixture records | SUPPORTED for fixture records | PARTIAL; provider-specific shot xG only | PARTIAL; event-derived fixture fields | PARTIAL; available post-match lineups | MISSING | PARTIAL; provider player IDs preserved |
| openfootball historical results | PARTIAL | PARTIAL | PARTIAL | MISSING | MISSING | MISSING | MISSING | MISSING |
| `schochastics/football-data` historical research dataset | PARTIAL; project warns about identity merge/split issues | PARTIAL | PARTIAL | MISSING | MISSING | PARTIAL where files exist | MISSING | PARTIAL where files exist |

## Provider/competition caveats

### Nowscore / 500

这些是当前系统已有的实际输入边界：market、recent form、部分比赛上下文。它们没有被假定成 xG、lineup 或 injury provider。未出现字段与“没有伤停”不是同义词；source、captured time 和 missing reason 必须保留。

### ESPN

ESPN summary 可提供 roster/availability 相关的部分结构化事实和叙事，但当前实现没有把它们映射成 canonical player、confirmed lineup 或 availability conflict records。因此覆盖只能记为 `PARTIAL`，不得升级为正式 deterministic feature。

### StatsBomb Open Data

StatsBomb fixture adapter 的 coverage 被明确限制为本地离线 research fixture。它可以验证 event、lineup、player 和 provider-specific xG 的 schema，但不能代表当前所有国内联赛、国际比赛或实时数据。原始公开数据的 attribution、User Agreement 和商业使用边界保存在 provenance metadata 中。

## Gaps that remain intentionally open

- 多 provider team/competition/player crosswalk 仍需逐项人工验证；
- provider-specific xG 还没有 normalization/calibration contract；
- opponent adjustment 只有结构，不训练 coefficient；
- red-card event/minutes 只在原始或 adapter 有来源时保存，Phase 2A 不决定降权；
- lineup 与 availability 尚未连接到 Champion；
- Parquet/DuckDB 只做 storage decision memo，不迁移现有 JSON snapshots。
