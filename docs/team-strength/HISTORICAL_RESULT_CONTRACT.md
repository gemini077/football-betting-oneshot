# Historical match result contract v1

`historical_match_result.v1` is an immutable provider-evidence record. It
preserves raw team/competition/season values alongside canonical IDs and
resolution status.

Every result also carries `entity_type` (`club` or `national_team`) and a
non-inferred `match_type` such as `league`, `domestic_cup`, `continental_club`,
`world_cup_qualifier`, `nations_league`, or `friendly`. Club and national-team
records are never mixed by the Team Strength builder.

An unresolved record may be stored for later review, but it must have:

```text
resolution_status = unresolved
resolution_method = unresolved
eligible_for_team_strength = false
```

An eligible record additionally requires a reviewed resolution method,
kickoff, both canonical team IDs, both final goals, source fact time, reliable
provenance, and quality A/B. The contract never turns a team name or provider
ID into a canonical identity by itself.

Team Strength uses only records with:

```text
kickoff_at < target_kickoff
duplicate_status in {unique, duplicate_same}
eligible_for_team_strength = true
```

`last_5`, `last_10`, and `last_20` use the most recent eligible competitive
matches before the target across competitions and seasons. `season_to_date`
is the exception: it requires the same canonical competition and season.

If multiple sources identify one match, the ledger keeps source confirmations
and counts the match once. A score/date/team disagreement sets
`source_conflict=true`, quality `D`, and eligibility false.

OpenFootball source records preserve repository, commit SHA, source file, raw
file SHA256, capture time, license, and parser version. The full upstream
dataset is not copied into the repository.

The target match and any future match are excluded. A pre-match snapshot is
stored by stable identity and cannot be overwritten by a later post-match
rebuild.
