# TEAM-CREST-PRODUCTION-1

Implementation authority lives in Memory-Hub:
`PROJECTS/Football-Betting-OneShot/RESEARCH/2026-09-09-TEAM-CREST-PRODUCTION-DECISION.md`

Goal: persist stable Nowscore team IDs + English names through the existing prediction universe, maintain a verified crest registry, enrich unresolved teams through TheSportsDB official V1 API only, cache successful crest assets locally, and wire local crest paths into existing Dashboard/Detail `home_crest` / `away_crest` rendering.

Hard boundaries:
- UI/data-enrichment only; no model/market/trust/serving changes.
- No scraping websites, guessed CDN paths, or unofficial hotlinks.
- No third-party runtime image dependency in generated HTML.
- Ambiguous mapping must fail closed to existing neutral initial.
- Crest fetch/enrichment failure must never fail the production cycle.
- Do not redesign R4 UI.

Acceptance:
- provider team IDs survive Universe normalization;
- known team registry records render local real crests on Today + Detail;
- cached teams make no API call;
- invalid/ambiguous/unresolved teams remain initials;
- focused tests + public build + 1440/390/320 screenshots pass;
- screenshots contain at least one real crest pair from production-shaped fixture.
