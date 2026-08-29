# DATA-PLANE-2 — Preflight Evidence

Date: 2026-08-30

`DATA-PLANE-2 = BLOCKED_BY_OBJECT_STORE_CREDENTIAL`

## Credential-family check

The recovered local preflight checked local environment names, GitHub Actions
configuration/references, repository secrets/variables, and GitHub environment
secrets. Secret values were not read into evidence and are not recorded here.

| Credential family | Result |
|---|---|
| R2 | `NOT_AVAILABLE` |
| Tigris | `NOT_AVAILABLE` |
| B2 | `NOT_AVAILABLE` |
| AWS/S3 | `NOT_AVAILABLE` |
| Generic S3-compatible | `NOT_AVAILABLE` |

The checked names included `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_ENDPOINT_URL`, `S3_ENDPOINT`, `S3_BUCKET`, `R2_*`, `TIGRIS_*`, and
`B2_*`. No provider is selected by this evidence.

## One-time configuration contract

Configure these provider-neutral field names outside Git-tracked files:

- `OBJECT_STORE_ENDPOINT`
- `OBJECT_STORE_BUCKET`
- `OBJECT_STORE_ACCESS_KEY_ID`
- `OBJECT_STORE_SECRET_ACCESS_KEY`
- `OBJECT_STORE_REGION` (optional)

The access key and secret key values stay in the local secret store and GitHub
Actions secret store. Only the field names belong in documentation or workflow
references; secret values never belong in the runtime manifest, commit, PR, or
logs.

## Immutable object convention

The authoritative object key is digest/version based:

```text
football-data/historical-results/<DATASET_SHA256>/historical_results.duckdb
```

`latest.duckdb` is not an authoritative object. A safe manifest pointer may be
used for convenience, but the runtime pin must name the exact immutable object.

## Live-validation boundary

The following items remain `NOT_LIVE_VALIDATED`:

- private object upload;
- runtime bootstrap;
- workflow integration;
- `record_count = 1778` from cloud/runtime;
- dataset SHA-256
  `48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2` from
  cloud/runtime;
- rollback and last-known-good execution;
- production smoke.

The known local authoritative fact remains 1,778 rows with the digest above;
it is not a GitHub-native or production bootstrap proof. No publisher,
bootstrap implementation, runtime snapshot manifest, or workflow integration
was recovered in the local delivery commit. The next implementation turn
requires a new preflight after the fields above are configured.
