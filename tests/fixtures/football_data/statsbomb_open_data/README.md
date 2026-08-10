# Offline StatsBomb research fixture

This is a tiny synthetic fixture shaped like the official StatsBomb Open Data
`matches`, `events`, and `lineups` JSON resources. `matches.json` is a list and
the adapter must receive an exact `match_id`; it is used only for contract and
adapter tests. It is not a claim about current competition coverage and it is
not a production data redistribution.

`metadata.json` marks the observation as synthetic schema evidence. The
`statsbomb_fixture` provider namespace and test-only identity registries must
not be copied into production registries.
