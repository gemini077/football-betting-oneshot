# API-Football adoption plan

Status: `DEFER` / planning-only. No API key, runtime adapter, purchase, or network call is enabled by this Phase 2B.2 change.

## Why it is a candidate

The recovered project demand includes Champions League, Europa League, national-team fixtures, Korea, and other competitions that are not covered by the current Football-Data.co.uk league CSV boundary. API-Football is a possible broad-coverage supplement, not an authoritative identity source and not a reason to bypass the existing reviewed identity layer.

The official coverage page currently lists 1,239 leagues and cups and states that coverage may vary by season or fixture. It must be checked per competition and season before any adapter is enabled: <https://www.api-football.com/coverage>.

## Current commercial and terms observations

Checked 2026-08-10:

- The official pricing page lists a Free plan at 100 requests/day, Pro at $19/month and 7,500 requests/day, Ultra at $29/month and 75,000 requests/day, and Mega at $39/month and 150,000 requests/day. The page says free plans have limited season availability: <https://www.api-football.com/pricing>.
- The terms prohibit reselling the provider data without permission and state that availability can vary by competition; coverage must be checked rather than assumed: <https://www.api-football.com/terms>.
- A paid plan is not approved by this phase. Pricing, terms, data retention, and commercial-use review must be rechecked immediately before adoption.

## Future adapter boundary

If a later phase approves the source, the adapter must:

1. require `API_FOOTBALL_KEY` and fail closed when it is absent;
2. expose normalized result records only through the existing `HistoricalResultAdapter` boundary;
3. capture endpoint, league ID, season, request timestamp, response hash, parser version, and provider coverage response;
4. treat provider team IDs as evidence that still needs reviewed canonical team mappings;
5. preserve source conflicts and unresolved teams as ineligible;
6. enforce a local cache, request budget, and retry/rate-limit policy;
7. keep raw response redistribution disabled and internal analysis-only until legal review permits otherwise;
8. use offline fixtures in CI; no test may call the live API.

The first future pilot should target the highest-demand unresolved cup/national-team competition from the recovered P0/P1 ranking, one competition at a time. It must not introduce xG, lineups, injuries, odds, or a Challenger.

## Current decision

`NEXT_SOURCE_CANDIDATE = API-Football`.

`ADOPTION = DEFER` until project demand is confirmed, a specific competition/season coverage response is captured, key ownership and quota are approved, and commercial/redistribution terms are reviewed for the intended use.
