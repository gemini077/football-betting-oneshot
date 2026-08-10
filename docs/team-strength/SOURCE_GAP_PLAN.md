# Phase 2B source gap plan

## Current source boundary

OpenFootball remains an offline historical result adapter for pinned native Football.TXT files. The Swedish 2025 Allsvenskan and Superettan captures are PARTIAL (53/240 and 45/240), so their source manifests do not claim complete coverage. The Portuguese 2025/26 capture is COMPLETE.

Football-Data.co.uk is now an offline historical-result adapter for captured CSV. The Sweden 2026 file has 119/240 completed rows and is IN_PROGRESS; it supplies current Swedish history but not a complete-season claim. The project stores source URL, capture time, raw SHA256, parser version and reviewed identity evidence. Raw redistribution is false and internal analysis only is true.

References: [OpenFootball Europe](https://github.com/openfootball/europe), [Football-Data downloads](https://www.football-data.co.uk/data), [Football-Data Sweden page](https://www.football-data.co.uk/sweden.php), and [Football-Data help/terms](https://www.football-data.co.uk/help_footballdata.php).

## Next source

`NEXT_SOURCE_CANDIDATE = API-Football` is planning-only. No API key, network adapter or fake response is enabled in this phase. See [API_FOOTBALL_ADOPTION_PLAN.md](API_FOOTBALL_ADOPTION_PLAN.md).

No source fleet is enabled. Unknown names remain unresolved, conflicts remain ineligible, and result history is never synthesized from recent-form aggregates, odds, Champion lambda or LLM text.

Discovery note: `agent-reach unavailable in current Codex environment`; official source pages were checked directly as the fallback. `grill-me unavailable in current Codex environment` was also recorded by the earlier Phase 2A review.
