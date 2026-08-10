# API-Football adoption plan

Status: `DEFER` — planning only; no API key, network adapter, production call, or fake response is enabled in Phase 2B.

## Why it is a candidate

The official coverage page currently advertises 1,237 leagues and cups, while also warning that detailed availability can vary by season or fixture. The official documentation exposes a `/leagues` coverage object that should be checked before any competition is accepted. See [official coverage](https://www.api-football.com/coverage) and [official documentation](https://www.api-football.com/documentation).

The candidate is relevant for gaps that the two offline result sources do not cover reliably: Champions League, Europa League, Conference League, World Cup, qualifiers, continental championships, national teams, Japan, Brazil, MLS and other long-tail competitions. Those are future hypotheses, not current coverage claims.

## Required review before adoption

- Verify competition and season coverage for each P0/P1 gap through the official `/leagues` coverage response.
- Verify historical season availability and result completeness for the exact competition/season.
- Verify API limits, caching, retry and reproducibility policy against the selected plan.
- Complete legal/commercial review for internal analysis, redistribution, betting use and third-party rights.
- Preserve provider IDs, response capture time, source-as-of time, endpoint, request parameters, raw hash and parser version.
- Keep the adapter behind `HistoricalResultAdapter`; unresolved identity and source conflicts remain ineligible.

## Cost and rate-limit facts checked 2026-08-10

The official pricing page lists Free at 100 requests/day, Pro at 7,500/day, Ultra at 75,000/day and Mega at 150,000/day; the page says free plans have limited season availability. The official rate-limit guidance lists per-minute limits of 10, 300, 450 and 900 respectively. These figures are volatile and must be rechecked before purchase. See [pricing](https://www.api-football.com/pricing) and [rate-limit guidance](https://www.api-football.com/news/post/how-ratelimit-works).

The terms state that data may be subject to third-party restrictions, that the service does not grant commercial rights to publish the data, and that resale is prohibited without permission. The project therefore requires a separate legal/commercial approval before any production use; an API key alone is not sufficient. See [official terms](https://www.api-football.com/terms).

## Decision

`DEFER`. Revisit only after the project usage registry produces a verified P0/P1 gap that cannot be covered by a stable, permitted offline source, and after the exact competition/season coverage and commercial boundary are approved.
