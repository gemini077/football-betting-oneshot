# Phase 2B source gap plan

## Adopted source

OpenFootball is adopted as an offline historical result adapter for the explicitly captured files. Current supported historical competition contexts are: Portuguese Primeira Liga, Sweden Allsvenskan, Sweden Superettan.
Official references: [openfootball/europe](https://github.com/openfootball/europe), [football.json schema/examples](https://github.com/openfootball/football.json), and [OpenFootball CC0 license](https://github.com/openfootball/europe/blob/master/LICENSE.md).
The upstream `openfootball/europe` repository uses native Football.TXT files in this capture. The adapter records repository, commit SHA, source file, raw SHA256, capture time, license, parser version, and team verification evidence.

OpenFootball does not solve current all-competition coverage, stable provider team IDs, xG, lineups, injuries, or live schedules. Its public-domain/CC0 data is useful for reproducible result history only.

## Next source candidate

`NEXT_SOURCE_CANDIDATE = football-data.org API` — DEFER.
Reference: [football-data.org quickstart](https://www.football-data.org/documentation/quickstart), [API reference](https://www.football-data.org/documentation/api), and [API policies](https://docs.football-data.org/general/v4/policies.html).
It exposes structured competition, season, team, match, UTC date, status, and score resources, but the project has no approved token/plan or completed terms/commercial-use review in this phase. CI must remain offline.

`football-data.co.uk` was also reviewed as a candidate. Its [downloadable historical results](https://www.football-data.co.uk/data) are simple and broad, but [terms/help](https://www.football-data.co.uk/help_footballdata.php), lack of stable provider IDs, and name-only identity make it a later review candidate rather than an automatic second adapter.

## Gap policy

No scraper fleet is enabled. Unknown competitions and names remain unresolved; source conflicts remain ineligible; result history is not synthesized from recent-form aggregates, odds, Champion lambda, or LLM text.

Discovery note: `grill-me unavailable in current Codex environment` and `agent-reach unavailable in current Codex environment`; official source pages were checked directly as a fallback and the adapter remains offline in CI.
