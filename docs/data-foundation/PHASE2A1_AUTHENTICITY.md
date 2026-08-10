# Phase 2A.1 Data Authenticity Hardening

This note records the final pre-merge hardening boundary for Phase 2A. It
does not promote a football feature into the Champion and it does not change
the Champion formula, inputs, calibration, market contracts, or benchmark
definitions.

## StatsBomb boundary

`StatsBombOpenDataProvider` is an offline, official-schema-compatible research
adapter. It reads the raw `list[match]` shape and selects an exact `match_id`;
missing IDs and duplicate IDs are errors. Team, competition, season, event,
and lineup fields are read from the official nested keys. The adapter does not
use `statsbombpy`, credentials, or network access, and it does not claim
current-match or all-competition production coverage.

The synthetic fixture has the same relevant official field structure but is
not a StatsBomb observation. Its provenance separates:

```text
observation_origin = synthetic_schema_fixture
source = synthetic_statsbomb_schema_fixture
synthetic = true
provider_schema = statsbomb
```

Real Open Data input uses `observation_origin=provider_open_data`,
`synthetic=false`, and `source=statsbomb_open_data` only when the input really
comes from that source. License, attribution, and commercial-use review remain
provenance metadata and are not inferred from GitHub visibility.

## Competition and team identity

Raw provider competition/season IDs and names are preserved separately from
`canonical_competition_id` and `canonical_season_id`. `CompetitionEntityResolver`
returns a canonical pair only for a reviewed exact provider + competition ID +
season ID mapping. It performs no fuzzy confirmation. `TeamEntityResolver`
receives only the canonical competition context; an unresolved provider name
cannot silently become a canonical filter.

The production competition registry has no synthetic fixture mapping. The
reviewed test mapping lives under the test-only StatsBomb fixture directory.
The production player registry is empty because no real player mapping is
currently verified. Synthetic player identities use the `statsbomb_fixture`
namespace in test-only fixtures and cannot resolve through the production
`statsbomb` namespace.

## Lineup semantics

The existing `lineup_snapshot.v1` contract remains the version because nullable
source semantics are a backward-compatible extension: `starter`, `bench`,
`captain`, and `goalkeeper` may be `null` when the source does not establish a
fact. `Starting XI` yields `starter=true, bench=false`; a proven substitute
entry yields `starter=false, bench=true`. Unknown position semantics remain
both `null`. Captain is not inferred, and goalkeeper is true only when the
source position establishes it. Each lineup records resolved-player coverage
without imposing a future model threshold.

## Freshness and quality

`captured_at` is ingestion time. `source_as_of_at` and `source_timestamp` are
source fact time. Fast-changing lineup and availability records require source
fact time; capture time cannot make them fresh. Availability prioritizes
`source_timestamp`, confirmed/projected lineups use `source_as_of_at`, and
future fact times beyond the documented five-minute clock-skew tolerance are
`unknown` with `timestamp_conflict=true`. Only the explicit slow-changing
policy permits capture-time fallback.

Providers initialize records through the central quality/freshness evaluator;
they do not claim `B` or `fresh` by construction. Material completeness is
record-type-specific, synthetic observations are never A/B, and the stored
record quality is the same result returned by `evaluate_record`.

All feature-registry entries remain `validated_for_model=false`. The Champion
continues to read none of these new records.
