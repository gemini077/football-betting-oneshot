# FE-SE-HIST-1 — Sweden Historical Completeness Closure

状态：`SEALED / ACCEPTANCE PASS`

基线：最新 `origin/main` `d1e6cd1aba80bbed059b5559db2869780a01dc30`。

PR #115 was merged; PR #114（FE-DC-1）保持 `OPEN`、不 merge；其独立验收结论是工程/研究实验 PASS，但 Dixon-Coles `NOT_PROMOTABLE`。本任务不修改 FE-DC-1 参数、Champion、production prediction 或 frozen prediction。

## 允许范围

允许读取：最新治理文件、现有 Football-Data/OpenFootball adapter、source manifest、identity evidence、historical samples、shared authoritative DuckDB，以及 Football-Data 当前 CSV 和 pinned OpenFootball 交叉样本。

允许修改：`scripts/football_data/fe_se_hist1.py`、FE-SE-HIST-1 focused test、`data/football_data/fe_se_hist1/`、Sweden 2025 normalized sample、historical dataset manifest、本文档和对应治理状态文件。不修改其他联赛数据、模型代码、Champion、production prediction、frozen prediction 或 raw provider 文件。

## 1. 先审计根因

### 1.1 Football-Data 当前来源

[Football-Data Sweden 页面](https://www.football-data.co.uk/sweden.php) 当前指向 [SWE.csv](https://www.football-data.co.uk/new/SWE.csv)。本轮捕获时间为 `2026-08-29T11:17:16Z`，HTTP `Last-Modified` 为 `Tue, 25 Aug 2026 09:19:54 GMT`，raw SHA256 为 `53c23a9908be1a0042d31ac481b175ec47da757dac4704f8a70ebe89807c8047`。

当前 CSV 的 Sweden Allsvenskan 结果为：

- 2025：240/240，16 队，`COMPLETE` / `SUPPORTED`；
- 2026：142 条已完成结果，但赛季仍在进行，未在本里程碑导入；
- 当前 adapter 只读取日期、时间、主客队和全场比分，不解释 odds/xG/lineup。

### 1.2 authoritative store 为什么只有 16 场

补齐前 shared authoritative store 为 `1,554` 条；其中 Sweden Allsvenskan：2025 为 `16` 条，且全部来自 OpenFootball；2026 为 `119` 条，全部来自 Football-Data。

根因不是 Football-Data 当前抓取缺失，也不是 dedup 误杀：

1. 旧 `football_data_uk/source_manifest.json` 已经记录 2025 `listed=240`、`parsed=240`、`COMPLETE`，但现有 pilot builder 的默认输出和 season wiring 只落到 2026，仓库没有 Football-Data 2025 normalized sample 或导入步骤。
2. OpenFootball pinned raw file 有 53 条 2025 Allsvenskan 结果，但旧 `openfootball_pilot.json` 只保存 16 条；authoritative 2025 的 16 条与这部分 OpenFootball 记录一致，说明这是 pilot 选择/导入范围问题，不是写入后被去重删除。
3. 旧 Football-Data identity evidence 只有 16 个、偏向 2026 队集，缺少 2025-only 的精确 provider 名称 `Norrkoping`、`Oster`、`Varnamo`。本轮仅增加它们的 reviewed exact mapping：分别对应 `team:sweden:ifk-norrkoping`、`team:sweden:osters-if`、`team:sweden:ifk-varnamo`；不使用 fuzzy、LLM 或猜测式映射。

## 2. 第二公开来源交叉核对

使用 pinned [OpenFootball Sweden 2025 source](https://raw.githubusercontent.com/openfootball/europe/e27eb01726f394ddf9fa68b15d37b900487b5903/sweden/2025_se1.txt)，commit 为 `e27eb01726f394ddf9fa68b15d37b900487b5903`，raw SHA256 为 `429273a6214a9f825735eaa590ebd623edbc2a2cc94fd1e6687f39d8ad40a9b6`：

- OpenFootball parsed：53；
- 两来源共享 fixture：53；
- 主客队 canonical identity / 日期 / 全场比分不一致：0；
- Football-Data 2025 相对该 partial secondary sample 多出：187；
- 该来源只作 bounded cross-check，不作为新的 provider 导入。

球队语境另与 [RSSSF Sweden 2025](https://www.rsssf.org/tablesz/zwed2025.html) 及 [Allsvenskan 2025 official results](https://www.fotbollsallsvenskan.se/en/results-allsvenskan2025.asp) 交叉核对；identity 仍以 exact reviewed evidence 为准。

## 3. 导入和 fail-closed 规则

- canonical competition 固定为 `competition:sweden-allsvenskan`；season 固定为 `season:sweden-allsvenskan:2025`；
- 复用 `FootballDataCoUkHistoricalAdapter` 和 `historical_match_result.v1`；raw capture 只存外部文件，Git 只保存 hash、manifest、normalized evidence；
- 先校验 raw SHA256、完整赛季 240 条、19 个合并 reviewed mappings 和每条 identity；
- candidate 内部 duplicate/conflict、已有 canonical match 的事实冲突、unresolved identity 均在 authoritative write 前阻断；
- 已有同事实比赛不重复写入；本轮 16 条旧 OpenFootball 记录被同事实 Football-Data 记录替换，并把旧 source confirmation 保留在 provenance；
- 使用 temporary DuckDB rebuild + atomic replace，并在替换前保留外部 rollback copy；第二次运行为 idempotent no-op；
- 2026 当前来源虽已看到 142 条，但本轮 authoritative 仍保持 119，不扩大本轮范围。

## 4. 数据审计结果

| 指标 | 补齐前 | 补齐后 |
|---|---:|---:|
| Sweden Allsvenskan 2025 | 16 | 240 |
| Sweden Allsvenskan 2026 | 119 | 119 |
| Sweden Allsvenskan 总场数 | 135 | 359 |
| 2025 队数 | 13（部分网络） | 16 |
| 2025 每队历史场数 min / median / max | 1 / 2 / 7 | 30 / 30 / 30 |
| 2025 unresolved identity | — | 0 |
| candidate duplicate collapsed | — | 0 |
| 与已有 16 场同事实 overlap | — | 16 |
| duplicate conflict | — | 0 |
| 2025 complete connected network | 否 | 是（240 场、120 条无向对手边） |

补齐后 2025+2026 authoritative Sweden scope：19 队；每队历史出场数 min / median / max 为 `15 / 45 / 45`；network `connected=true`；最早 kickoff `2025-03-29T14:00:00Z`，最晚 `2026-08-03T18:00:00Z`。

authoritative historical store：

- before digest：`710b0fdc8046d69aa86411b748d9c1966c45fabd0ac83678f58719b1f3bbfb5e`；
- after digest：`48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2`；
- after record count：`1,778`，全部 eligible；
- 非 Sweden 2025 记录 digest 集合保持不变；2026 仍为 119 条。

证据文件：

- `data/football_data/fe_se_hist1/source_manifest.json`
- `data/football_data/fe_se_hist1/identity_evidence.json`
- `data/football_data/fe_se_hist1/audit.json`
- `data/football_data/historical_result_samples/football_data_uk_sweden_2025.json`
- `data/football_data/manifests/historical_results.dataset.json`

## 5. 研究和生产边界

本里程碑只恢复已有历史结果能力。没有新增 provider、Elo、xG、lineup、regularization、rho/half-life/attack-defense 调参，也没有接 production、修改 Champion、修改 frozen prediction 或重写 FE-DC-1 研究结果。FE-DC-1 仍为 research evidence，`NOT_PROMOTABLE`。

## 6. 可重复构建

raw CSV 必须由调用方在外部 capture 目录提供，运行：

```powershell
python -m scripts.football_data.fe_se_hist1 PATH_TO_SWE.csv `
  --secondary-raw-path PATH_TO_OPENFOOTBALL_2025_SE1.txt `
  --db-path PATH_TO_FOOTBALL_DATA_HOME\historical_results.duckdb `
  --backup-path PATH_TO_ROLLBACK\historical_results.before-fe-se-hist-1.duckdb `
  --write-authoritative
```

脚本不联网、不提交 raw CSV；它依据 manifest hash、exact identity evidence、已有 authoritative records 和 deterministic dedup/rebuild 生成同一目标数据集，并可重复运行。

## 7. 状态

`READY_FOR_ACCEPTANCE`
