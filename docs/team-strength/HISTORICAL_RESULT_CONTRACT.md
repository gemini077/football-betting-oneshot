# Historical match result contract v1

`historical_match_result.v1` is an immutable provider-evidence record. It
preserves raw team/competition/season values alongside canonical IDs and
resolution status.

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

The target match and any future match are excluded. A pre-match snapshot is
stored by stable identity and cannot be overwritten by a later post-match
rebuild.
