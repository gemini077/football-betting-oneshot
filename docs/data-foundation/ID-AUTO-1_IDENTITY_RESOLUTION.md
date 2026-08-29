# ID-AUTO-1 — League-Agnostic Deterministic Team Identity Resolution

Status: `SEALED / ACCEPTANCE PASS`

Independent acceptance: `ID-AUTO-1 = ACCEPTANCE PASS`. PR #118 was safely
merged to `main` at `04a548416513865e4af4771603fb4369074ecd57` without
reverting the latest automatic prediction, market, prospective, dashboard, or
runtime state. `IDENTITY_BACKLOG = NON_BLOCKING / ON_DEMAND`; ID-AUTO-2 is not
started.

Audit cohort: `2026-08-29` through `2026-08-31`, Asia/Shanghai, exactly 66
Prediction Universe fixtures.

## Product result

The daily identity path now uses one reusable registry and one exact resolver.
It is not a league adapter and it does not add fixture-specific aliases. A
reviewed `(provider, provider_team_id)` mapping is stored once and is reused by
future fixtures. A missing or conflicting identity remains visible and
fail-closed for the historical challenger while the existing Champion route
continues.

## Landscape and build-vs-buy decision

The local landscape review included the existing Football-Data/OpenFootball
adapters and reviewed project evidence, plus open-source candidates such as
[openfootball/football.json](https://github.com/openfootball/football.json),
[soccerdata](https://github.com/probberechts/soccerdata), and
[Hudl Open Data](https://github.com/hudl/open-data). These projects provide
source/adaptor capabilities, not the durable provider-ID/canonical-team
contract required here. The existing free, reproducible adapters and local
evidence remain the adopted path; no dependency, paid provider, or scraper
family was added.

## Registry contract

`data/football_data/id_auto_1/identity_registry.json` is
`identity_registry.v1`. Each canonical team records:

- `canonical_team_id`, `canonical_name`, competition scope and country;
- canonical source names and reviewed aliases;
- provider, provider team ID, provider exact name;
- evidence source/timestamp, resolution method, confidence class and
  ambiguity state.

The registry is built only from the existing authoritative historical store,
`verified_project_provider_crosswalk.json`, `verified_identity_crosswalk.json`,
the existing team alias registries, current reviewed identity evidence, and
reviewed Football-Data/OpenFootball identity evidence. Its normalization is
NFKC + casefold + Unicode-alphanumeric exact matching. Transliteration, fuzzy
similarity, LLM guessing, kickoff proximity, and score-based candidate choice
are disabled.

## Deterministic resolution ladder

The implementation in `scripts/football_data/identity_registry.py` applies the
same order for every competition:

1. existing stable provider-ID crosswalk;
2. existing reviewed canonical/provider crosswalk;
3. exact canonical team ID carried by the fixture;
4. competition-constrained exact normalized canonical/source name;
5. competition-constrained reviewed alias.

Only one candidate is `AUTO_RESOLVED`. Multiple candidates become
`AMBIGUOUS`; no lower-strength fallback is used after an ambiguous stronger
level. The daily coverage gate in `scripts/football_data/coverage_gate.py`
loads this registry without changing the Champion calculation.

## Identity-chain audit A–E

Counts are explicitly separated into fixture rows, fixture sides, and registry
rows:

| Question | Evidence result |
| --- | ---: |
| A. Current direct 500 provider team IDs | 4 fixtures / 8 sides observed; 0 sides directly aligned because no reviewed 500 team-ID crosswalk exists for these IDs; 8 remain unmapped |
| B. Current Level-4 exact normalized unique names | 2 sides across 2 fixtures |
| C. Existing evidence absent from the HC-AUTO-1 legacy daily path | 152 verified crosswalk rows, 22 reviewed alias groups, 10 existing team-registry rows; provider match crosswalk has 0 rows |
| D. Same provider ID bridging multiple names to one team | 3 Nowscore IDs / 6 exact provider names: Bodo Glimt, Fredrikstad, Valerenga bridges |
| E. Current truly ambiguous identity | 0 fixtures / 0 sides; registry alias backlog has 0 ambiguous groups |

The registry contains 37 stable provider-ID mapping rows across 34 unique
provider IDs. All 37 replay checks resolve to the expected canonical team.
The same provider ID is therefore reused rather than re-reviewed per fixture.

## Exact 66-fixture BEFORE / AFTER

| Measure | BEFORE HC-AUTO-1 | AFTER ID-AUTO-1 |
| --- | ---: | ---: |
| `AUTO_RESOLVED` fixtures | 1 | 2 |
| Partial identity fixtures | 4 | 7 |
| `AMBIGUOUS` fixtures | 0 | 0 |
| `UNRESOLVED` fixtures | 61 | 57 |
| `SUPPORTED` | 1 | 2 |
| `DEGRADED` | 0 | 0 |
| `UNSUPPORTED` | 65 | 64 |
| `IDENTITY_UNAVAILABLE` | 65 | 64 |
| `HISTORY_INSUFFICIENT` | 0 | 0 |
| `COMPETITION_UNSUPPORTED` | 0 | 0 |
| Champion jobs allowed | 66 | 66 |
| Blocked Champion jobs | 0 | 0 |

The improved rows are deterministic evidence, not manually filled aliases.
Eleven sides now resolve (six existing crosswalk sides plus five sides from
the consolidated reviewed identity chain), including two full fixtures.

### Existing-history validation group (15 fixtures)

| Competition | Fixtures | AFTER auto | AFTER partial | AFTER unresolved | AFTER `SUPPORTED` |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sweden Allsvenskan | 4 | 1 | 2 | 1 | 1 |
| Portugal Primeira Liga | 4 | 0 | 0 | 4 | 0 |
| Norway Eliteserien | 2 | 1 | 1 | 0 | 1 |
| USA MLS | 2 | 0 | 0 | 2 | 0 |
| Finland Veikkausliiga | 2 | 0 | 2 | 0 | 0 |
| Brazil Serie A | 1 | 0 | 1 | 0 | 0 |

The exact historical store remains read-only at 1,778 records with dataset
digest `48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2`.
No historical result, frozen prediction, prospective record, market/fetch
record, or Champion math was rewritten.

## Remaining backlog and generic import notes

`data/football_data/id_auto_1/identity_resolution_backlog.json` records seven
partial/reviewable fixtures and 57 fully unresolved fixtures. It contains no
manual per-fixture alias additions. The unresolved rows lack a unique reviewed
provider ID, canonical ID, exact competition name, or reviewed alias; they are
not guessed.

Japan J1 is recorded as `READY_FOR_GENERIC_IMPORT` through the existing
Football-Data adapter because the captured 2025 source has 380 completed
results. Spain La Liga is recorded as `READY_FOR_GENERIC_IMPORT` through the
existing OpenFootball adapter and reviewed identity evidence. Neither import
was executed here, and no Japan/Spain-specific importer was added.

## Evidence and verification

- `scripts/football_data/identity_registry.py`
- `scripts/football_data/run_id_auto_1.py`
- `data/football_data/id_auto_1/identity_registry.json`
- `data/football_data/id_auto_1/daily_fixture_audit.json`
- `data/football_data/id_auto_1/identity_resolution_backlog.json`
- `data/football_data/id_auto_1/provider_id_reuse_evidence.json`
- `tests/test_id_auto_1_identity_registry.py`
- `tests/test_id_auto_1_audit_artifact.py`
- `tests/test_hc_auto_1_coverage_gate.py`

Focused resolver, registry, gate, Champion fail-open, audit-artifact, and
existing HC integration tests pass. ID-AUTO-1 is now `SEALED / ACCEPTANCE PASS`
after independent acceptance; ID-AUTO-2 is not started automatically.
