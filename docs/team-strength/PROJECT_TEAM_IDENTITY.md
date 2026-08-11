# Phase 2B.4 Project Team Identity

Generated at `2026-08-11T00:00:00Z` from existing project demand metadata and the shared historical result store.

This is a shadow data-layer identity audit. It does not modify the Champion, create predictions, or validate any feature for model use.

Starting identity-missing fixtures: `78`; fixtures with both project sides resolved by this sprint: `6`.

Verified project mappings: `49`; review required `1`; conflicts `0`; unresolved `143`.

Reviewed alias groups used: `19`; alias-derived verified project mappings: `9`. Alias evidence is still scoped by the current competition/country context and never bypasses conflict or review gates.

P0/P1 demand remains `152`. Strict ready `19`; verified bridge `1`; identity-missing `72`; source-missing `60`.

500 match IDs are not treated as 500 team IDs. Nowscore team IDs remain in the Nowscore namespace; an exact bound capture may provide cross-provider context, but its ID is never copied into a 500 mapping.

Detailed candidate evidence and the stable pre-sprint baseline are local-only under `${FOOTBALL_DATA_HOME}/identity/`; Git retains only compact verified truth and a compact review queue.

All new mappings remain `validated_for_model=false`.
