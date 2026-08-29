# DATA-PLANE-2 — Private Snapshot Production Bootstrap Contract

Last updated: 2026-08-30

Status: `BLOCKED_BY_OBJECT_STORE_CREDENTIAL`

This document records the provider-neutral contract and the one-time setup
required before implementation. It does not provision a provider, upload a
dataset, change a workflow, or change the production Champion.

## 1. Preflight result

The short credential preflight was run before any implementation work:

| Location | Result |
|---|---|
| Local process environment | `NOT_AVAILABLE` |
| Local root `.env*` names | `NOT_AVAILABLE` |
| GitHub workflow secret/variable references | `NOT_AVAILABLE` |
| GitHub repository secrets | `NOT_AVAILABLE` |
| GitHub repository variables | `NOT_AVAILABLE` |
| GitHub environment secrets | `NOT_AVAILABLE` |
| `OBJECT_STORE_CREDENTIAL` | `NOT_AVAILABLE` |

The check covered `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_ENDPOINT_URL`, `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`,
`S3_SECRET_ACCESS_KEY`, `R2_*`, `TIGRIS_*`, and `B2_*`. Secret values were not
printed. Since no usable credential pair exists, provider suitability,
publisher, bootstrap, workflow smoke, and production smoke remain pending.

## 2. Canonical credential contract

The implementation uses provider-neutral names. Provider-specific aliases are
not part of the runtime contract.

### Local publisher environment

The local publisher requires:

- `FOOTBALL_DATA_SNAPSHOT_PUBLISH_ACCESS_KEY_ID`
- `FOOTBALL_DATA_SNAPSHOT_PUBLISH_SECRET_ACCESS_KEY`
- `FOOTBALL_DATA_SNAPSHOT_ENDPOINT_URL`
- `FOOTBALL_DATA_SNAPSHOT_BUCKET`
- `FOOTBALL_DATA_SNAPSHOT_REGION`

The publisher pair is write-scoped and is used only on the machine that owns
the authoritative local snapshot.

### GitHub Actions runtime secrets and variables

Repository secrets, with read-only object permissions:

- `FOOTBALL_DATA_SNAPSHOT_RUNTIME_ACCESS_KEY_ID`
- `FOOTBALL_DATA_SNAPSHOT_RUNTIME_SECRET_ACCESS_KEY`

Repository variables, or repository secrets when the provider requires the
values to be hidden:

- `FOOTBALL_DATA_SNAPSHOT_ENDPOINT_URL`
- `FOOTBALL_DATA_SNAPSHOT_BUCKET`
- `FOOTBALL_DATA_SNAPSHOT_REGION`

The runtime pair receives `HeadObject` and `GetObject` access only for the
historical-results snapshot and manifest prefixes. It has no object write or
delete permission. The publisher pair receives `PutObject`, `HeadObject`, and
`GetObject` for the same prefixes; delete permission is not required.

## 3. One-time setup after credentials are available

1. Select one existing private S3-compatible provider. Do not register a new
   provider as part of this milestone.
2. Create a private bucket with public access disabled. Enable provider
   versioning or object-lock/retention when available; digest-based object keys
   remain the primary immutability control.
3. Create two least-privilege key pairs: a local publisher pair and a GitHub
   Actions read-only runtime pair.
4. Add the runtime pair without exposing values in workflow output:

   ```text
   gh secret set FOOTBALL_DATA_SNAPSHOT_RUNTIME_ACCESS_KEY_ID --repo TARGET
   gh secret set FOOTBALL_DATA_SNAPSHOT_RUNTIME_SECRET_ACCESS_KEY --repo TARGET
   ```

   Each command reads the value interactively. The values are never committed
   and never written to the runtime manifest.
5. Add the endpoint, bucket, and region as repository variables or secrets:

   ```text
   gh variable set FOOTBALL_DATA_SNAPSHOT_ENDPOINT_URL --repo TARGET --body OBJECT_STORE_ENDPOINT
   gh variable set FOOTBALL_DATA_SNAPSHOT_BUCKET --repo TARGET --body OBJECT_STORE_BUCKET
   gh variable set FOOTBALL_DATA_SNAPSHOT_REGION --repo TARGET --body OBJECT_STORE_REGION
   ```

6. Configure the local publisher process with the publisher pair and the same
   endpoint/bucket/region names. Keep these values in the local secret store or
   process environment; do not add them to Git.
7. Re-run the credential preflight. Implementation starts only when the
   runtime pair and publisher pair are both present and the provider access
   scope can be checked without printing secret values.

## 4. Dataset and manifest contract

The first accepted snapshot is pinned to the existing authoritative local
dataset:

- `record_count`: `1778`
- `dataset_sha256`:
  `48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2`
- `dataset_version`: `authoritative-1778`

The tracked runtime manifest path is:

`data/football_data/runtime_snapshot_manifest.json`

It contains only public-safe metadata. The required shape is:

```json
{
  "snapshot_version": "snapshot-YYYYMMDDTHHMMSSZ-<dataset_sha256>",
  "object_key": "football-data/historical-results/<dataset_sha256>/historical_results.duckdb",
  "artifact_sha256": "ARTIFACT_SHA256",
  "dataset_sha256": "48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2",
  "record_count": 1778,
  "dataset_version": "authoritative-1778",
  "contract_version": "data-plane-2.v1",
  "builder_version": "BUILDER_VERSION",
  "source_manifest_hashes": ["SOURCE_MANIFEST_SHA256"],
  "created_at": "ISO_8601_UTC",
  "previous_snapshot_version": null
}
```

The manifest contains no secret, access key, signed URL, or restricted raw
provider bytes. `previous_snapshot_version` is `null` for the first snapshot
and identifies the exact previous version thereafter.

## 5. Immutable object naming

The authoritative DuckDB object is immutable and digest-addressed:

```text
football-data/historical-results/<dataset_sha256>/historical_results.duckdb
```

The versioned safe manifest sidecar is:

```text
football-data/historical-results/manifests/<snapshot_version>.json
```

An optional safe pointer may be maintained at:

```text
football-data/historical-results/latest.json
```

The pointer is convenience metadata only. It is never the sole authority and
is not used in place of the Git-tracked exact object key. The following name is
not an authoritative object:

```text
latest.duckdb
```

## 6. Publisher contract

The future publisher is a small wrapper around the existing authoritative
local data home:

1. Run `verify_data_home` against the local `historical_results.duckdb`.
2. Require `record_count == 1778` and the exact logical dataset digest above.
3. Compute the byte-level `artifact_sha256`.
4. Upload the DuckDB to its digest-based immutable object key.
5. Upload the versioned safe manifest sidecar.
6. Re-`HEAD` and `GET` the object, verify the returned byte digest, and verify
   the downloaded DuckDB logical digest and count.
7. Only after all verification succeeds, update the Git-tracked runtime
   manifest pin atomically. A failed upload never advances the pin.

The publisher does not rebuild live sources and does not alter the local
authoritative database.

## 7. Runtime bootstrap contract

The future shared bootstrap command is:

`scripts/football_data/bootstrap_runtime_data.py`

Its sequence is:

1. Read the Git-tracked runtime manifest.
2. Download the exact `object_key` into an isolated temporary path under
   `$RUNNER_TEMP/football-data/`.
3. Verify `artifact_sha256` before opening the file for use.
4. Open the temporary DuckDB read-only and verify `record_count`.
5. Compute and verify the logical `dataset_sha256`.
6. Atomically move the verified file into the isolated runtime data home.
7. Export `FOOTBALL_DATA_HOME` through the shared command/composite action,
   never by overwriting an in-use database.
8. Run `automation_cycle.py` only after the verified data home is present.

No empty data home is a successful bootstrap state.

## 8. Last-known-good and fail-closed behavior

Failure handling is explicit:

| Failure | Action |
|---|---|
| Current snapshot download/HEAD fails | Try the exact previous snapshot version |
| Current artifact checksum fails | Reject it; try the exact previous version |
| Current logical dataset digest fails | Reject it; try the exact previous version |
| Current row count differs | Reject it; try the exact previous version |
| Previous snapshot also fails any verification | Emit `DATA_PLANE_BOOTSTRAP_FAILED` and fail the production cycle |

When the previous exact snapshot is used, the runtime health evidence reports
`DEGRADED_DATA_SNAPSHOT`, and the internal health object records
`runtime_data_snapshot.status = DEGRADED_LAST_KNOWN_GOOD`. The current snapshot
is reported as `READY` only after current-object verification. A completely
failed bootstrap never silently rebuilds live sources and never falls back to
an empty historical database.

The health evidence records:

- `runtime_data_snapshot.status`: `READY`, `DEGRADED_LAST_KNOWN_GOOD`, or
  `FAILED`
- `snapshot_version`
- `dataset_sha256`
- `record_count`
- `bootstrap_at`

These fields stay in internal health/evidence; normal user pages do not expose
engineering identifiers.

## 9. Workflow reuse and acceptance proof

The implementation plan uses one shared command/composite action for every
production path that reads the historical store. The first audited workflow is
`.github/workflows/deploy-pages.yml`, which invokes
`scripts/automation_cycle.py`. `.github/workflows/core-auto-analysis.yml` is
included in the dependency audit before it is changed; it receives the shared
bootstrap only if its execution path directly reads the historical store.

Cloud-equivalent acceptance must run in a fresh temporary Linux-like runner or
an actual `workflow_dispatch` run with no developer `FOOTBALL_DATA_HOME`, local
Windows database, or local cache. With only Git checkout, the exact manifest,
and object-store credentials, it must prove:

- downloaded artifact SHA equals the publisher proof;
- logical dataset SHA equals
  `48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2`;
- row count equals `1778`;
- `500-1364199` resolves through `authoritative_historical_results`;
- recent-form records are at least the Champion minimum and all have kickoff
  earlier than the target kickoff;
- current and previous snapshot rollback behavior are both exercised;
- protected frozen prediction state is unchanged.

Only after this proof may DATA-PLANE-2 move to `READY_FOR_ACCEPTANCE`.

## 10. Licensing boundary

The DATA-PLANE-1 boundary remains active:

- `raw_redistribution=false`
- `internal_analysis_only=true`
- `commercial_use_review=required`
- `LICENSING_REVIEW_REQUIRED`

A private snapshot validates internal production operation; it does not grant
public redistribution or commercial rights.

## 11. Implementation file plan

No implementation file below is started while the credential gate is blocked.

| File | Planned responsibility |
|---|---|
| `data/football_data/runtime_snapshot_manifest.json` | Git-tracked current pin and previous version metadata |
| `scripts/football_data/runtime_snapshot.py` | S3-compatible client boundary, manifest schema, artifact/logical verification, atomic install helpers |
| `scripts/football_data/publish_runtime_snapshot.py` | Authoritative local preflight, immutable upload, post-upload GET/HEAD verification, manifest emission |
| `scripts/football_data/bootstrap_runtime_data.py` | Exact download, checksum/dataset/count verification, last-known-good fallback, isolated `FOOTBALL_DATA_HOME` install |
| `.github/actions/bootstrap-football-data/action.yml` | One reusable Actions bootstrap/export step |
| `.github/workflows/deploy-pages.yml` | Invoke the shared bootstrap before the production cycle |
| `.github/workflows/core-auto-analysis.yml` | Add the same action only if the dependency audit confirms direct historical-store use |
| `scripts/production_health_watch.py` | Add internal `runtime_data_snapshot` evidence and degraded/failed reporting |
| `tests/test_runtime_snapshot.py` | Manifest, object naming, digest, count, and checksum behavior |
| `tests/test_publish_runtime_snapshot.py` | Publisher verification order and pin immutability on failure |
| `tests/test_bootstrap_runtime_data.py` | Clean-runner bootstrap, fallback, fail-closed, and atomic install behavior |
| `tests/test_production_health_watch.py` | Health status propagation and protected-state behavior |

The next implementation turn begins only after the canonical credential names
above are configured and preflight returns `AVAILABLE`.
