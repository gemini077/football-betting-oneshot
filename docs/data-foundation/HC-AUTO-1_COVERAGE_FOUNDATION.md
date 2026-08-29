# HC-AUTO-1 — League-Agnostic Historical Coverage Foundation

Status: `SEALED / ACCEPTANCE PASS`

Independent acceptance: `HC-AUTO-1 = ACCEPTANCE PASS`; PR #117 was merged to
`main` at merge commit `7680c57475c907ba87cf40c9c1a3d1d48543edb1` after
preserving the latest automated-run state.

Generated evidence date: `2026-08-29` (Asia/Shanghai)

## What changed

HC-AUTO-1 adds one versioned, data-driven coverage contract:

- `config/football_data_coverage.json` — exact competition aliases, coverage
  policy, adapter/source capabilities and use restrictions.
- `schemas/football_data/coverage_registry.v1.schema.json` — stable registry
  field contract.
- `scripts/football_data/coverage_registry.py` — manifest discovery,
  deduplicated source aggregation and authoritative historical-store inventory.
- `scripts/football_data/coverage_gate.py` — exact-only competition/team
  resolution and `SUPPORTED` / `DEGRADED` / `UNSUPPORTED` gate.
- `scripts/football_data/build_coverage_registry.py` — reproducible CLI for
  registry generation and batch audit of existing Prediction Universe snapshots.
- `scripts/base_prediction_jobs.py` — attaches coverage status/reason metadata
  before BASE jobs are handed to the existing Champion runner. No fixture is
  filtered because of historical coverage.

The gate is provider- and league-agnostic in executable code. Provider
capabilities are manifest data; no `if Sweden`, `if England`, or other
country-specific adapter branch was added.

## Reused sources and build-vs-buy boundary

This milestone reuses the repository's already reviewed, free, reproducible
sources and adapters only:

| Source | Existing adapter/manifest surface | HC-AUTO-1 use |
| --- | --- | --- |
| `football-data.co.uk` | `football_data_uk` adapter and source manifests | historical results and refresh capability metadata |
| `OpenFootball` | `openfootball` adapter and source manifests | bounded historical results and source license metadata |
| local DuckDB historical store | `HistoricalResultStore` | authoritative counts, team identity and freshness |
| reviewed crosswalk/evidence | `verified_project_provider_crosswalk.json`, `current_match_identity_evidence.json` | exact current fixture identity only |

No new provider, paid API, scraper dependency or Python dependency was added.
The existing open-source discovery matrix remains the landscape record; this
task adopts the existing adapters instead of adding another scraper family.

## Global inventory (A–D)

The committed registry was generated with:

```text
python -m scripts.football_data.build_coverage_registry \
  --date 2026-08-29 --date 2026-08-30 --date 2026-08-31 \
  --date 2026-08-14 --date 2026-08-16 --date 2026-08-23 \
  --now 2026-08-29T12:00:00Z
```

### A. Can today's real fixtures map to authoritative history?

The current real Prediction Universe sample contains 66 fixtures across
2026-08-29, 2026-08-30 and 2026-08-31.

| Gate result | Fixtures | Interpretation |
| --- | ---: | --- |
| `SUPPORTED` | 1 | exact competition/team identity, at least five eligible pre-kickoff matches per team, and current history freshness |
| `DEGRADED` | 0 | no current row reached this state in this snapshot; the gate is covered by focused tests |
| `UNSUPPORTED` | 65 | exact current team identity was unavailable; no history was invented or fuzzy-mapped |

All 66 rows still have `champion_prediction_allowed=true` and
`blocked_count=0`. This is an audit of the captured snapshots, not a request to
repair the 65 identity gaps in this milestone.

The supplemental real Prediction Universe identity sample (2026-08-14,
2026-08-16 and 2026-08-23) has one exact `SUPPORTED` row on each date. It is
retained only to exercise the existing reviewed crosswalk against real stored
fixture IDs; it is not relabeled as current prospective evidence.

### B. Current blocker classification

For the three current dates, the gate reports:

| Reason code | Count | Meaning |
| --- | ---: | --- |
| `COMPETITION_UNSUPPORTED` | 0 | all observed current league labels are now exact catalog entries |
| `IDENTITY_UNAVAILABLE` | 65 | no deterministic reviewed pair of canonical team IDs |
| `HISTORY_INSUFFICIENT` | 0 | identity fails before history is used for those rows |
| `SOURCE_STALE` | 0 | no fixture with resolved identity failed the freshness gate |
| `SOURCE_UNAVAILABLE` | 0 | no resolved-identity fixture reached a source-availability failure |
| `CURRENT_SEASON_PARTIAL` | 1 warning | one supported current-season row has an in-progress source season; history remains usable |

The registry also records backlog-level gaps independently of fixture status:
39 catalog competitions exist, 7 have authoritative historical records, 9
have source-manifest evidence, and 30 have no current source row. These are
coverage backlog facts, not silent pipeline failures.

### C. What the existing sources cover

- 7 source-manifest files were discovered, with 30 duplicate-collapsed source
  rows and no manifest load failure.
- Source rows are provided by `football-data.co.uk` (19) and `openfootball`
  (11).
- The authoritative historical store contains 1,778 results. Existing
  registry rows with history are Brazil Serie A (290), Finland Veikkausliiga
  (251), Norway Eliteserien (319), Portugal Primeira Liga (370), Sweden
  Allsvenskan (359), Sweden Superettan (5), and USA MLS (184).
- Source-manifest evidence also names Japan J1 and Spain La Liga, but their
  current authoritative history count is zero; the registry records these as
  backlog/insufficient-history rows rather than implying imported coverage.
- The historical store is read-only for this task; the existing dataset count
  and digest remain governed by the prior manifests.

### D. History already exists but was not automatically routed before

The current daily input contains 15 fixtures from competitions that already
have authoritative history: Sweden Allsvenskan (4), Portugal Primeira Liga
(4), Norway Eliteserien (2), USA MLS (2), Finland Veikkausliiga (2), and
Brazil Serie A (1). Only one has enough exact current identity evidence to be
`SUPPORTED`; the others are now visible as deterministic identity gaps rather
than being silently omitted from a history workflow.

This is the important routing change: the next fixture from any catalog entry
uses the same registry and gate. A new unsupported competition produces an
auditable `COMPETITION_UNSUPPORTED` row and does not stop other fixtures.

## Daily integration contract

```text
daily schedule intake
  -> Prediction Universe snapshot
  -> BASE job sync
       -> coverage registry + exact identity/history gate
       -> attach status/reason codes to every job
  -> existing Champion runner
```

`SUPPORTED` enables the historical team-strength challenger metadata only.
`DEGRADED` records why the challenger is not eligible while retaining the
current Champion/market job. `UNSUPPORTED` records the exact missing
competition or identity evidence and also retains the current Champion job.

## Evidence files

- `data/football_data/hc_auto_1/coverage_registry.json`
- `data/football_data/hc_auto_1/daily_fixture_audit.json`
- `tests/test_hc_auto_1_coverage_registry.py`
- `tests/test_hc_auto_1_coverage_gate.py`
- `tests/test_hc_auto_1_daily_integration.py`

Known limits intentionally left as backlog: deterministic current team
crosswalk expansion, 30 source-less catalog entries, and any provider that
would require a new scraper. They do not block other fixtures and are not
implemented in HC-AUTO-1.
