# DATA-PLANE-1 — Cloud Production Football Data Architecture Decision

Last updated: 2026-08-30
Status: `READY_FOR_ACCEPTANCE`
Decision: **B. `PRIVATE_SNAPSHOT_STORE`**

## 1. Decision boundary

This milestone is a data-supply architecture decision only. It does not
provision an object store, change GitHub Actions, migrate the DuckDB files,
change the Champion, add a provider, or start PRED-AVAIL-3.

The selected architecture is vendor-neutral: a private, versioned,
content-addressed object snapshot is the durable runtime source. R2, S3 and
other S3-compatible services remain implementation candidates, not a vendor
selection in this milestone. GitHub Actions cache and workflow artifacts are
auxiliary acceleration/diagnostic channels only.

The existing DuckDB format remains the runtime read model. Local and cloud
must install the same snapshot version and verify both:

- `artifact_sha256`: byte-level integrity of the downloaded object;
- `dataset_sha256`: the existing logical digest of normalized records;
- `record_count`: the expected row count;
- `dataset_version`, contract version, builder/parser versions and source
  manifest hashes.

The Git-tracked manifest carries these pins and the private object reference;
raw restricted provider files and the DuckDB snapshot stay outside the public
repository.

## 2. Current truth

### 2.1 Local data plane

The local authoritative store was verified with
`python -m scripts.football_data.verify_data_home`:

| Dataset | Location | Records | Logical digest | Role |
| --- | --- | ---: | --- | --- |
| historical results | `C:\Users\Administrator\.football-betting-oneshot\football_data\historical_results.duckdb` | 1778 | `48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2` | authoritative recent-form input |
| team-strength snapshots | same `FOOTBALL_DATA_HOME` | 160 | `3fcd494b0cbe20f65f6f8407f471ca2d8e034010789b6ebec85d0e4becd9a8a6` | research/shadow snapshot |

The resolver in `scripts/football_data/data_home.py` uses
`FOOTBALL_DATA_HOME`, otherwise
`Path.home()/.football-betting-oneshot/football_data`. The store is therefore
a local analytical artifact, not a repository file.

### 2.2 Cloud production data plane as it exists today

The latest checked `origin/main` is
`9d792b35275045d7e62a02d2edd949b2b253686e`. Its production projection for
`business_date=2026-08-30` is 25 fixtures, 1 frozen and 24
`INSUFFICIENT_DATA`.

The current workflow is:

```text
ubuntu-latest
  -> checkout
  -> pip install
  -> git pull --rebase origin main
  -> automation_cycle.py
  -> source/cache attempts
  -> BASE runner
  -> HistoricalResultStore() at the runner's empty default data home
  -> MISSING_RECENT_FORM when the historical file is absent
  -> public runtime/dashboard/Pages artifacts
```

`.github/workflows/deploy-pages.yml` does not restore
`historical_results.duckdb`, download a versioned historical dataset, call
`rebuild_historical_store.py`, or set `FOOTBALL_DATA_HOME`. The same gap is
present in the core analysis workflow. This is the production/local data-plane
split that explains why isolated local replay is 2/25 while online main is
still 1/25.

PR #120 remains OPEN and is not merged. Its independent result is
`ENGINEERING_ACCEPTANCE PASS / PRODUCT_AVAILABILITY BLOCKED` with
`LIVE_VALIDATION_BLOCKED_BY_CREDENTIAL`; `CALL_COUNT=0` and
`CACHE_HIT_COUNT=0`. No live coverage improvement is used as evidence here.

## 3. Audited data flows

### 3.1 Local path

```text
approved raw capture or pinned public source
  -> provider adapter
  -> contract validation and normalization
  -> exact canonical identity registry/resolver
  -> historical_results.duckdb under FOOTBALL_DATA_HOME
  -> load_authoritative_recent_form(...)
  -> four-block recent-form eligibility
  -> existing Champion input path
```

`HistoricalResultStore` only reads the resolved local DuckDB in the recent-form
loader. The loader applies exact competition/team identity, eligible rows,
strict `kickoff < target kickoff`, source reliability, duplicate/conflict and
freshness checks before returning the existing four-block contract.

The current historical store is a mixed-source result: mainly
Football-Data.co.uk normalized results plus a smaller OpenFootball contribution.
The Football-Data.co.uk raw CSV capture is deliberately outside Git and its
manifest records `raw_redistribution=false`, `internal_analysis_only=true` and
`commercial_use_review=required`.

### 3.2 Proposed cloud path after a later implementation milestone

```text
Git-tracked runtime manifest
  -> exact private object key/version
  -> download to temporary runner path
  -> verify artifact_sha256, dataset_sha256, record_count and contract
  -> atomic materialization under FOOTBALL_DATA_HOME
  -> read-only HistoricalResultStore
  -> automation_cycle.py
  -> existing recent-form route and Champion
```

Source refresh is a separate publisher operation. A prediction run never
rebuilds from an unpinned live URL. A failed source refresh leaves the last
verified snapshot in place; a failed initial bootstrap is explicit and
fail-closed rather than silently producing a second data truth.

## 4. Asset classification

The following classification is the current state, not a claim that every
asset is already available on a clean runner.

| Asset | A. In repo | B. Only local data home | C. Rebuildable from external source | D. Manifest/evidence only | E. Licensing boundary | F. Production-required | G. Research-only |
| --- | --- | --- | --- | --- | --- | --- | --- |
| adapter, contract, normalization and store code | Yes | No | Yes | No | code licenses/dependencies | Yes | No |
| source manifests, raw URLs, source commits, hashes and terms | Yes | No | No | Yes | terms are metadata, not redistribution permission | Yes for provenance | No |
| exact identity registry/crosswalk | Yes | No | No | No | reviewed evidence references | Yes for exact historical routing | No |
| tracked legacy historical ledger | 206 JSON records | No | No | No | provider-derived rows retain source restrictions | Partial only | No |
| tracked normalized sample evidence | 3 files / 446 record occurrences | No | No | Yes | evidence samples are not the full dataset | No | Yes |
| authoritative historical DuckDB | No | Yes, 1778 rows | Only if all raw captures are available and unchanged | Its manifest is in repo | Football-Data.co.uk terms review required | **Yes** for authoritative recent form | No |
| team-strength DuckDB | No | Yes, 160 rows | Builder can rerun if historical input exists | Its manifest is in repo | same source restrictions | No for current Champion bootstrap | **Yes** |
| Football-Data.co.uk raw CSV captures | No | Outside repo/capture storage | URL can be fetched, but bytes can drift | Hashes only | `raw_redistribution=false`, internal analysis only, commercial review required | Input to publisher only | Yes until policy permits runtime use |
| OpenFootball raw source | No | No | Yes from pinned public commits | Commit and hashes tracked | CC0 in the reviewed manifest | Partial fallback/reference only | Yes for the current research route |
| football-data.org live API | No | No | Potentially per credential and quota | PR/provider manifests only | live validation not completed | Candidate only | No production claim |
| GitHub Actions cache/artifact | Platform state | No | Not deterministic/durable | No | GitHub retention/eviction applies | Auxiliary only | No |

## 5. Clean-runner reproducibility audit

The audit used a scoped temporary checkout of the latest checked `origin/main`
and did not read the developer `FOOTBALL_DATA_HOME`, Windows caches or the
local DuckDB. It supplied only tracked code, manifests, legacy ledger and
snapshot inputs.

The clean runner ran the existing offline command twice with the same fixed
`generated_at`:

```text
python -m scripts.football_data.rebuild_historical_store \
  --legacy-ledger-root data/football_data/historical_result_ledger \
  --legacy-snapshot-root data/football_data/team_strength_snapshots \
  --output-root TEMP/runtime-N \
  --manifest-root TEMP/manifest-N \
  --generated-at 2026-08-30T00:00:00Z
```

Measured result:

| Output | Run 1 | Run 2 | Authority comparison |
| --- | ---: | ---: | --- |
| historical record count | 206 | 206 | expected 1778 — mismatch |
| historical logical digest | `0a1183aa11ae3c27c8b2081cae2f8776dfc50fbb35371ef48374e6f798d01a74` | same | expected `48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2` — mismatch |
| team-strength snapshot count | 48 | 48 | local authority has 160 — mismatch |
| team-strength logical digest | `ccad0920100f082f45fa79a9993eb3e5a4baf09efe0cb9112b80caf2a535234a` | same | manifest/local authority differs |

The two clean runs are byte/logically repeatable for the inputs they contain,
but the 1778-row authoritative dataset is absent. The classification is

```text
PARTIALLY_REPRODUCIBLE
```

not `FULLY_REPRODUCIBLE` and not `NOT_REPRODUCIBLE`.

The tracked source manifests do not contain the missing raw third-party files.
The current `rebuild_historical_store.py` explicitly does not download them;
it only migrates the tracked legacy JSON input when present. The tracked
legacy ledger has 206 files (about 622 KB); the separate three sample files
are evidence samples and are not consumed by that rebuild command.

There is also source drift evidence. The demand manifest pins an older
`NOR.csv` hash `aa649e866b03d2ead83f89937fcb09a9ca9edcbc459c83dba68cfa567c01e6b4`,
while the bounded current capture used for the target proof was 409,808 bytes
with hash
`22edff434a6b32daf94d6644e21c0281f44935a2e069e8c70ae6475b36e07a6b`. A URL
alone therefore cannot reproduce the old dataset digest.

## 6. Minimum reality proof

A clean temporary environment used the tracked adapter, contract, exact
identity registry and a temporary DuckDB, with no developer data home. It
captured the approved Norway source before the target kickoff, created a
temporary versioned manifest, and loaded the result through the existing
authoritative recent-form function.

```text
source: https://www.football-data.co.uk/new/NOR.csv
capture_at: 2026-08-29T19:06:03Z
raw_bytes: 409808
raw_sha256: 22edff434a6b32daf94d6644e21c0281f44935a2e069e8c70ae6475b36e07a6b
dataset_version: football-data.co.uk:NOR.csv@sha256:22edff434a6b32daf94d6644e21c0281f44935a2e069e8c70ae6475b36e07a6b
temporary_record_count: 328
temporary_dataset_sha256: 59cf75eaba2ab5e15800375a8cbe9eaac7691dc39e30c102e8562281a38ba8ec
```

For `500-1364199` (`博德闪耀` vs `罗森博格`), the proof returned:

```text
input_eligible: true
form_source: authoritative_historical_results
form_record_count: 10
latest home: 2026-08-08T13:00:00Z
latest away: 2026-08-14T18:00:00Z
target cutoff: 2026-08-30T12:30:00Z
```

This proves that a versioned source rebuild can supply authoritative recent
form in a clean environment. It does not prove that the current tracked
manifests can rebuild all 1778 rows, and it is not a deployment claim.

## 7. Architecture comparison

### Option A — `REBUILD_ON_RUNNER`

**Assessment:** useful as a publisher/update/recovery builder, not sufficient as
the sole production authority today.

- Build cost is low for the current scale; the bounded Norway proof is a small
  parse-and-build job. Full build time is network-bound and was not established
  as a CI SLA.
- It requires repeated downloads, source availability, exact bytes, identity
  resolution and provider terms on every clean runner.
- The current tracked-input run produces 206/1778, and the live URL changed
  its hash, so it cannot guarantee the required 1778-row digest.
- A source outage during the daily prediction run would directly remove the
  only bootstrap path unless another durable snapshot already exists.

### Option B — `PRIVATE_SNAPSHOT_STORE`

**Assessment:** selected.

- One verified object download is on the production critical path; source
  refresh is off the prediction critical path.
- Immutable content-addressed keys provide exact rollback and prevent silent
  replacement. The existing DuckDB remains an efficient local read-only model.
- Storage/transfer cost is near zero at the current scale. Cloudflare R2 is a
  cost benchmark, not a selected vendor: its official pricing currently lists
  10 GB-month, 1 million Class A operations, 10 million Class B operations and
  free egress per month for Standard storage ([R2 pricing](https://developers.cloudflare.com/r2/pricing/)).
- Maintenance is moderate once: publisher, manifest pin, secret, checksum and
  atomic bootstrap. Routine prediction runs do not redownload raw sources.

### Option C — `PRIVATE_DATABASE`

**Assessment:** not justified for the current read-only 1778-row artifact.

- It adds network latency, connection/credential management, migrations,
  backup policy and a second query service without a current multi-writer or
  interactive-query requirement.
- A free Supabase project has 500 MB database size but pauses after one week of
  inactivity and does not include automatic backups; Pro starts at $25/month
  ([Supabase pricing](https://supabase.com/pricing)). That is operationally
  disproportionate to this read-only snapshot.
- Reconsider only when the product needs online writes, concurrent consumers,
  user-facing ad hoc queries, or database-native recovery/replication that an
  object snapshot cannot provide.

### Option D — `REPO_RUNTIME_DATASET`

**Assessment:** not permitted by the current source boundary.

- The current local DuckDB is about 4.2 MB for 1778 rows, so raw size alone is
  not the blocker. Public visibility, daily Git churn and the restricted
  Football-Data.co.uk terms are the blockers.
- The manifest explicitly records `raw_redistribution=false`,
  `internal_analysis_only=true` and `commercial_use_review=required`. A
  normalized derived file must not be treated as public redistribution
  permission.
- Git rollback is easy, but removing a later commit does not remove public
  exposure or licensing history. A public repo also becomes a second data
  distribution channel.

### Cache and artifact exclusion

GitHub cache is evictable: the official documentation says entries not accessed
for more than seven days are removed by default and cache storage is subject
to repository limits ([dependency caching](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching)).
Workflow artifacts expire by default after 90 days and the retention period is
configurable, not permanent ([artifact retention](https://docs.github.com/en/organizations/managing-organization-settings/configuring-the-retention-period-for-github-actions-artifacts-and-logs-in-your-organization)).
Neither can be the single durable source of truth.

## 8. Runtime contract for the later implementation milestone

The implementation milestone must use the following contract without changing
the model:

1. Publisher acquires approved raw sources in a private temporary workspace.
2. Adapter, contract validation and exact identity gate run offline from the
   captured bytes.
3. Publisher builds DuckDB and computes `record_count`, existing
   `dataset_sha256`, and byte-level `artifact_sha256`.
4. Publisher uploads an immutable object under a digest/version key and
   verifies it by a fresh download or provider checksum response.
5. Only after object verification does a small Git manifest change pin the
   object key, version, digest, count, source hashes, licensing metadata and
   previous last-known-good version.
6. GitHub Actions downloads the pinned object into a temporary path, verifies
   it, then atomically installs it under `FOOTBALL_DATA_HOME` and opens it
   read-only.
7. If source refresh fails, the previous verified snapshot remains current. If
   the current object is unavailable, the pinned last-known-good object may be
   used with an explicit degraded health reason; an unpinned live rebuild is
   never substituted.
8. Rollback is a manifest pin revert to the previous immutable object. No
   mutation of frozen predictions, prospective history or the Champion is part
   of rollback.

DuckDB already supports read-only file access for multiple readers and no
 writers, which matches this runtime role ([DuckDB concurrency](https://duckdb.org/docs/stable/connect/concurrency.html)).
Tools such as DVC can later automate the manifest/remote workflow, but their
own documentation still requires remote storage for sharing artifacts
([DVC command reference](https://dvc.org/doc/command-reference/)); adding DVC
now would not remove the need to choose and govern the private store.

## 9. Operational decision

| Item | Decision |
| --- | --- |
| Recommended architecture | **B. `PRIVATE_SNAPSHOT_STORE`** |
| Recommended fallback | **A. `REBUILD_ON_RUNNER`** only as an offline publisher/recovery path when all pinned raw inputs are present |
| Vendor | Not selected; R2/S3-compatible candidates require a separate bounded implementation and licensing check |
| Long-term cost | Near zero at current artifact size; storage/operations depend on the selected private provider and number of retained versions |
| Maintenance complexity | Medium one-time implementation, low routine prediction-run maintenance |
| Failure recovery | Immutable versions, manifest pin rollback, last-known-good fallback, fail-closed bootstrap if no verified snapshot exists |
| Update frequency | Separate source-refresh publisher; daily for active-season source changes when needed, weekly/on-demand for completed-history refresh; never rebuild during every prediction cycle |
| Production bootstrap | checkout manifest -> private object download -> artifact/logical digest + count verification -> atomic `FOOTBALL_DATA_HOME` install -> read-only store -> existing automation |
| Public repository growth | Manifest and provenance only; no raw restricted files or full DuckDB |
| Model impact | None; Champion, lambda, selector, calibration and prediction artifacts are outside this milestone |

## 10. Acceptance result and stop line

`DATA-PLANE-1 = READY_FOR_ACCEPTANCE`.

The architecture decision is complete when independent acceptance confirms the
clean-runner result, source-drift evidence, target proof, option comparison,
licensing boundary and no-migration stop line in this document. No object
store, database, runtime dataset migration, workflow bootstrap or provider
change is started by this milestone.
