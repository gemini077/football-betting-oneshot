# PA-2-R1-ID3 Identity Architecture Review

Date: 2026-08-24
Review scope: competition/season identity for the future Challenger bridge and
the user-facing Champion workbench.  This review does not change the model,
frozen predictions, results, ledgers, production state, or `main`.

## Decision in one sentence

The current bar is appropriate for **canonical research identity**, but too
strict if it is also used as the single gate for the product surface.  Use a
three-state identity contract: **A** reviewed canonical competition/season
identity, **B** provider-scoped research context, and **C** explicit unresolved;
only A plus reviewed team identities may enter Challenger/Prospective formal
eligibility.

This is an architecture decision, not a registry write.  No production
competition registry row is added by this review.

## Scope and invariants

### Read boundary

The review read only the following bounded surfaces:

- `14_PRODUCT_BLUEPRINT_产品全貌.md`, `15_PROJECT_STATUS_项目状态.md`,
  `16_ROADMAP_项目路线图.md`, `17_NEXT_WORK_后续工作.md`,
  `18_ACCEPTANCE_验收标准.md`, `19_DECISIONS_关键决策.md`,
  `00_PROJECT_INSTRUCTIONS_粘贴到项目指令.md`, and `WORK_MANIFEST.json`;
- `scripts/nowscore_markets.py`;
  `scripts/target_team_identity_bridge.py`;
  `scripts/football_data/competition_resolution.py`;
  `scripts/football_data/project_identity.py`;
  `scripts/base_prediction_runner.py`;
  `scripts/prospective_challenger_runner.py`; and
  `scripts/prospective_pair_capture.py`;
- the related focused tests;
- `data/football_data/competition_registry.json` and
  `data/football_data/verified_project_provider_crosswalk.json`.

### Non-negotiable invariants

1. `recent_form_market_calibrated_poisson_v2` remains the user-visible
   Champion.
2. A provider-scoped identity is never copied into
   `canonical_team_identity`, never used to join historical results, and never
   makes a row formally eligible for Challenger/Prospective evaluation.
3. Formal paired evaluation continues to require the same canonical match and
   canonical team identities for Current, Challenger, Market-only, and Uniform.
4. Existing frozen rows, input snapshots, results, prospective ledgers,
   production configuration, model math, and `main` are immutable for this
   task.
5. Missing or contradictory identity remains visible as a reasoned state; it
   is not silently converted into a guessed mapping.

## Evidence reviewed

### Existing implementation

- `parse_schedule_js` obtains the Nowscore `SclassID` from the structured
  schedule relationship `B[A[i][1]][0]`, not from the array index.
- The acquisition path verifies the target match ID, captures the provider
  league page and season script, checks returned `SclassID`, `selectSeason`,
  and (when present) the season list, and stores source references, timestamps,
  and raw SHA-256 digests.
- `CompetitionEntityResolver` already fails closed unless the exact provider,
  provider competition ID, and provider season ID match one reviewed registry
  row.  Names are consistency checks, not identity evidence.
- `resolve_target_team_identity` correctly rejects absent evidence, post-cutoff
  evidence, ambiguous crosswalks, and missing reviewed provider team mappings.
- Champion freeze does not require `canonical_team_identity`; the identity
  bridge is attached as audit metadata when available.  Challenger capture
  does require canonical competition and both canonical team IDs.

### Current coverage facts

The current-state notes record the following bounded facts:

- the latest proof exposed five provider competition IDs (`11`, `23`, `31`,
  `34`, `36`) and five matching provider season keys (`2026-2027`);
- the reviewed competition registry currently has four reviewed season rows
  for `openfootball` / `football-data.co.uk` and no reviewed Nowscore/Nowgoal
  competition rows;
- the 24 target provider team IDs have no reviewed crosswalk coverage;
- the 12 future formal Champion rows therefore produced zero canonical
  competition/season resolutions and zero Challenger/pair artifacts in the
  read-only dry run.

The external evidence supplied for this review independently confirms the
following provider-level facts:

| provider machine ID | provider league URL | provider competition |
|---:|---|---|
| `36` | `/league/36` | English Premier League |
| `34` | `/league/34` | Italy Serie A |
| `31` | `/league/31` | Spanish La Liga |
| `11` | `/league/11` | France Ligue 1 |

It also confirms that the Nowgoal/iSports structured surface exposes
`leagueId`, `currentSeason`, and `countryId`.  These facts are strong
candidate evidence for a reviewed **competition** mapping.  They do not, by
themselves, review a team crosswalk, prove historical strength coverage, or
prove that a Nowgoal response and a Nowscore response share a provider
namespace.  The namespace distinction must be explicit in any registry row.

## Options

Scores are relative to this product and current phase: High / Medium / Low.

| Criterion | A. Exact reviewed provider-ID → canonical registry | B. Provider-scoped research identity fallback | C. Keep unresolved |
|---|---|---|---|
| Auditability | **High** when the row contains provider namespace, machine ID, season key, canonical open-source entity, reviewer, source refs, cutoff, and raw hashes. | **Medium**: auditable as provider evidence, but not proof of a portable canonical entity. | **High**: safest because no assertion is made. |
| User-visible coverage | **High at competition/season label level**; team/research coverage still depends on team crosswalk and history. | **High for a provider-native evidence/workbench view**; can show the provider’s own teams and season without calling them canonical. | **Low**; users see missing context even when the provider has usable structured data. |
| Empty-workbench risk | **Low for Champion and competition filters; Medium for Challenger** until team/history gates pass. | **Low for a research/context view**, while formal Challenger stays empty by design. | **High**; the current 0/12 research capture is the visible failure mode. |
| Latency | Low steady-state: local exact lookup; acquisition is already cached and bounded to provider calls per league. | Lowest: reuse captured provider IDs; no registry lookup or canonical join. | Lowest. |
| Cost | Low runtime cost; moderate one-time review and per-season maintenance cost. | Low runtime cost; recurring provider-specific maintenance and eventual migration cost. | Low runtime cost; high product opportunity cost. |
| Maintenance | Registry rows need season rollover/review and namespace discipline. | Provider schema changes and duplicate provider adapters accumulate. | Minimal code maintenance, but unresolved queues grow. |
| Cross-source portability | **High for the competition/season layer**; only canonical team IDs make team-level joins portable. | Low by design; provider IDs must never cross providers. | None. |
| Governance risk | Controlled if it resolves only exact reviewed competition/season identity and does not imply team/history eligibility. | Controlled only with a separate contract and hard formal gate. | Safest but product-hostile if used as the only surface. |

## Product reading of the trade-off

The current acceptance bar is not wrong; it is being asked to answer two
different user questions:

1. **“Can I see and understand today’s match?”** Champion already answers this
   without canonical team identity.  A missing research mapping must not hide a
   usable Champion card or make the whole workbench look empty.
2. **“Can this match be used in a portable, prospective Challenger benchmark?”**
   This still requires the strict A path for competition/season plus reviewed
   canonical team identities and history availability.  B must not lower this
   bar.

Therefore the right product behavior is not “accept every provider ID as
canonical” and not “hide every match until every research join is solved.”
It is to render the Champion normally, expose a plain-language data state in
secondary detail, and keep the Challenger state separately labelled as
research readiness.

## Direct user-impact answers

### 1. Does competition/season context unlock the current team bridge?

No. Adding reviewed competition/season rows would clear only the competition
resolver gate.  `target_team_identity_bridge` then still requires one reviewed
crosswalk row for each of the two target provider team IDs in the match.  The
current target set is **24 provider team IDs with 0/24 reviewed mappings**:
**12/12 target pairs remain incomplete**, so the next blocker is team
crosswalk review, not competition context.  The resulting bridge state remains
`TARGET_IDENTITY_UNRESOLVED` with a missing reviewed provider-team mapping.

The existing exact team-resolution route is therefore reusable, but only for a
pair whose two provider IDs already have reviewed mappings in the same reviewed
competition context.  Competition context does not create or infer those
mappings.  Even after all four candidate competition rows are reviewed, the
current evidence supports **0/12 Challenger-ready pairs**; history readiness is
the next gate after team identity, not a reason to promote a provider ID.

### 2. Does the Champion workbench retain matches without research identity?

Yes.  `base_prediction_runner` freezes Champion output without requiring
`canonical_team_identity`, and `prediction_dashboard` / match analysis project
cards from the frozen job and prediction record rather than filtering on the
research join.  The focused dashboard fixture already proves that a frozen
Champion card with no canonical identity remains visible.  No visibility
change is needed.

The smallest user-facing split is a secondary, display-only research status:

| Display status | Use when |
|---|---|
| `赛事身份待确认` | provider competition/season evidence, namespace, or reviewed team crosswalk is missing, ambiguous, contradictory, or unreviewed; do not call this a history failure. |
| `研究历史数据不足` | canonical competition, season, and both canonical teams are resolved, but the historical prior/coverage gate is below the research threshold. |

Keep the existing Champion prediction status and visible match card unchanged;
show this research status beside the research/Challenger section.  In
particular, do not label a missing team crosswalk as `研究历史数据不足`, and do
not hide the Champion card while either status is present.

## Recommendation

Adopt **A + B + C**, with strict separation:

### A — canonical competition/season identity

Use A for the four independently confirmed IDs (`36`, `34`, `31`, `11`) only
after a bounded review package records:

- the exact provider namespace (`nowscore` versus `nowgoal`/`iSports` must not
  be silently merged);
- the provider machine ID and target-linked pre-kickoff evidence;
- `currentSeason` / provider season key and `countryId`;
- the canonical open-source competition entity and the project’s stable
  `canonical_competition_id` / `canonical_season_id`;
- source URLs, raw hashes, capture time, reviewer, and the mapping’s intended
  validity window.

The existing resolver can consume such rows; no fuzzy or name-only resolver is
needed.  ID `23` remains C until equivalent evidence is reviewed.  A resolved
competition is **not** a resolved team and is **not** evidence that the
historical strength store contains useful priors.

### B — provider-scoped research context

Add a separate, optional context object for a target that has a verified
provider match ID, provider team IDs, provider league ID, season key, and
country ID but lacks a reviewed canonical team crosswalk.  The object should
be explicitly namespaced, for example:

```json
{
  "contract_version": "provider_research_identity.v1",
  "status": "PROVIDER_SCOPED_ONLY",
  "provider": "nowgoal",
  "provider_match_id": "TARGET_PROVIDER_MATCH_ID",
  "provider_competition_id": "36",
  "provider_season_id": "2026-2027",
  "provider_country_id": "TARGET_PROVIDER_COUNTRY_ID",
  "provider_home_team_id": "TARGET_PROVIDER_HOME_TEAM_ID",
  "provider_away_team_id": "TARGET_PROVIDER_AWAY_TEAM_ID",
  "portable": false,
  "formal_challenger_eligible": false
}
```

This is suitable for a provider-native research/context panel and for an
explicit “canonical research mapping pending” explanation.  It is not suitable
for canonical team IDs, historical joins, model parameters, paired metrics,
promotion, or production Champion inputs.

### C — unresolved

Keep C for missing, ambiguous, contradictory, post-kickoff, post-cutoff, or
namespace-unverified evidence.  C must carry a machine-readable reason such as
`PROVIDER_NAMESPACE_UNVERIFIED`, `PROVIDER_COMPETITION_SEASON_UNREVIEWED`, or
`CANONICAL_TEAM_CROSSWALK_MISSING`; it must not be silently dropped.

## Smallest follow-up implementation

This review does not make the registry write.  The four supplied league IDs
are enough to justify a bounded Route-A follow-up, but not enough to write the
current registry: the checkout's acquisition contract is `nowscore`, while the
new evidence is explicitly `nowgoal`/`iSports`, and the canonical open-source
entity references plus raw, target-linked hashes are not present in this
checkout.  Writing rows now would silently merge namespaces and would fail the
project's reviewed-evidence bar.  After that evidence package is reviewed, the
smallest safe slice is:

1. Add only four exact provider competition/season rows to
   `data/football_data/competition_registry.json`; leave `23` unresolved.
2. Keep `CompetitionEntityResolver` exact and unchanged unless a test exposes
   a missing field.  Add a source namespace assertion so a `nowgoal` row cannot
   satisfy a `nowscore` request (or vice versa).
3. Add a read-only `provider_research_identity` projection to the target
   evidence path.  Do not place it in `canonical_team_identity`.
4. Keep `prospective_challenger_runner._target` unchanged: B must still raise
   `CANONICAL_RESEARCH_IDENTITY_MISSING` when canonical team IDs are absent.
5. Do not re-run or rewrite any frozen historical artifact.  Validate the new
   mapping only against future/read-only capture inputs.

### Minimum tests for that follow-up

- exact provider + league ID + season key resolves the intended canonical
  competition and canonical season;
- wrong provider namespace, wrong season, missing ID, or duplicate mapping
  fails closed;
- provider name mismatch is a diagnostic, not a name-based fallback;
- provider-scoped context is emitted with `portable=false` and
  `formal_challenger_eligible=false`;
- a provider-scoped context without canonical team crosswalk still causes
  Challenger capture to reject with
  `CANONICAL_RESEARCH_IDENTITY_MISSING`;
- missing/ambiguous/post-cutoff/post-kickoff evidence remains unresolved with
  an explicit reason;
- read-only dry-run proves no changes to Champion predictions, input
  snapshots, prospective ledger, calibration, dashboard, results, or pair
  artifacts when the team crosswalk is absent.

## Review conclusion

The product should keep “no canonical research join” separate from “no useful
match.”  Route A is justified for reviewed competition/season identity; Route B
is justified as a clearly non-portable provider context; Route C remains the
default failure state.  The current Champion workbench already retains the
match, so the immediate product requirement is the two-label research status
split rather than a visibility workaround.  This preserves the prospective
governance bar without claiming Challenger coverage beyond team and history
readiness.

No registry row, frozen row, result, ledger, model calculation, or `main`
branch was modified by this review.
