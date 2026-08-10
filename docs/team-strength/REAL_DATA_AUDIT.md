# Real historical data audit

Bounded audit capture: `2026-08-10T11:56:08Z`. Scope is current workspace metadata, provider snapshots, pinned source manifests and normalized samples; the full report history was not scanned.

## Existing current providers

The existing bounded provider audit found aggregate recent_form snapshots but zero explicit match-level result records. recent_form has aggregate overall/home/away matches, wins, draws, losses, goals for and goals against; it has no reliable per-match date, opponent ID or score. It cannot be expanded into a historical ledger without inventing history.

## Historical result sources

OpenFootball pinned capture: `openfootball/europe@e27eb01726f394ddf9fa68b15d37b900487b5903`; listed/parsed source totals are `240/53`, `240/45`, and `306/306`, for `404` parsed rows. The two completed Swedish files are PARTIAL; Portugal is COMPLETE.
Football-Data.co.uk capture: `https://www.football-data.co.uk/new/SWE.csv`; raw SHA256 `56b5f00a253a223f7eb546a80c4f3b3201b9a9fd976ae37e1dcee5f12a104ebf`; the normalized Sweden 2026 sample has `119` records and `119` eligible records. The CSV is not committed.

## Current buildability

Current bounded schedule: `3` matches; both history available `3`; both current-strength ready `2`; bridge-only `0`; stale `1`; source conflicts `0`; identity unresolved `0`.

The ledger preserves old results as valid historical evidence. Team-strength recency is calculated from the latest match kickoff, not source capture time. The data layer remains shadow-only and `validated_for_model=false`.
