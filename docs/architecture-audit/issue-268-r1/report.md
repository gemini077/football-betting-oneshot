# FBOS whole-code architecture, ownership and maintenance audit — Issue #268 R1

## Decision: `ARCHITECTURE_CONSOLIDATION_REQUIRED`

`ARCHITECTURE_CONSOLIDATION_REQUIRED` is an audit conclusion about future maintenance/regression cost. It is not authorization to refactor, delete, rename, migrate, change provider/model/UI/Serving behavior, or open a follow-up Issue.

## Scope and method

- Exact code/config surface: `scripts/**/*.py`, `tests/**/*.py`, `.github/workflows/**`, `.github/actions/**`, `schemas/**`, and `config/**`.
- AST inventory: LOC, functions/classes, imports, local dependency edges, cycles, sys.path mutation, direct/package fallback, responsibility tags, data access signals and module roles.
- Workflow inventory: triggers, permissions, git write commands, namespaces written, concurrency declaration and classification for every workflow/action.
- Data policy: `data/**` was enumerated by tracked path for namespace counts and ownership references only. No historical data file contents were bulk-read, parsed or hashed.

## Mechanical evidence

- Python modules: `397`; parse errors: `0`.
- JSON schema/config files: `31`; parse errors: `0`.
- Local dependency edges: `772`; cycles: `1`.
- sys.path mutations: `82`; direct/package fallback sites: `43`; cross-layer local edges: `119`.
- Tracked data files counted by catalog: `39055`; namespace rows: `37`.
- Workflows/actions: `18`; main-write overlap rows: `14`.

## Test-system evidence

- Command: `python -m pytest --collect-only -q`
- Status: `FAILED_DURING_COLLECTION`
- Collected before failure: `1269`
- Error files: `tests/test_live_ev_profile.py`
- Import errors: `ImportError: cannot import name 'PUBLIC_DATA_DIRS' from 'build_public_site' (<repo>\scripts\build_public_site.py)`
- Per Issue #268, collection failure is recorded as baseline evidence and was not patched. Existing architecture/ownership and bounded characterization tests were run separately.

## Ranked findings

### P0-TIME-001 — Multiple live naive-time semantics
- Evidence: AST/symbol scan finds parse_kickoff, _parse_timestamp, parse_datetime, parse_kickoff_local and runtime timestamp parsers in separate modules; R12 records UTC interpretation, Shanghai interpretation, and rejection.
- Actual current consequence: The same naive timestamp can select a different current/future record, chronology gate, or postmatch join depending on caller.
- Future maintenance/regression consequence: Every new workflow/provider must choose among incompatible semantics and can create silent cross-day regression.
- Smallest candidate consolidation boundary (not authorized): Candidate: one explicit timezone/naive-input contract at module boundaries, with compatibility adapters characterized before any move.

### P0-IDENTITY-001 — Identity authority is distributed across canonical, provider, and presentation joins
- Evidence: AST/import and symbol scan shows canonical_match_id consumers plus provider-specific identity, postmatch report_key fallbacks, workspace SequenceMatcher joins, and State Memory/registry paths.
- Actual current consequence: A match can be accepted by one consumer and remain unresolved or attach to another report in a different consumer; PR #267 is retained as a counterexample only.
- Future maintenance/regression consequence: Provider/team naming changes require repeated edits and can alter evaluation/report joins without a single contract test.
- Smallest candidate consolidation boundary (not authorized): Candidate: deterministic identity boundary with explicit presentation-only compatibility matching kept outside truth selection; no alias/mapping change is authorized here.

### P0-RUNTIME-001 — Root runtime state and product runtime are both reachable
- Evidence: Static references show 05_RUNTIME_STATE.json in fetch_football_data, live_odds_bridge, match_workspace, postmatch_dashboard, postmatch_queue and report defaults, while automation/dashboard/health use data/product_runtime.
- Actual current consequence: Health/current-state consumers can observe different state surfaces and a stale root file can remain operationally relevant.
- Future maintenance/regression consequence: Runtime changes need dual-path compatibility and race analysis; deleting either path without reachability proof risks silent stale state.
- Smallest candidate consolidation boundary (not authorized): Candidate: establish one current runtime owner and an explicit read-only compatibility adapter after reachability inventory; no data migration is authorized.

### P1-IMPORT-001 — Import architecture has path mutation and dual import modes
- Evidence: AST scan enumerates sys.path mutations and try/except ImportError direct-versus-package imports; high fan-in/fan-out modules connect provider, governance, report and runtime layers.
- Actual current consequence: The same module can execute under different import identities, and dependency direction is harder to enforce in tests and workflows.
- Future maintenance/regression consequence: Refactors need repeated compatibility edits and can hide cycles or import-order-only behavior.
- Smallest candidate consolidation boundary (not authorized): Candidate: package/import boundary characterization and incremental removal of only proven duplicate import paths.

### P1-ORCH-001 — Several orchestration modules combine acquisition, domain policy, persistence, and projection
- Evidence: Responsibility inventory marks mixed-layer coupling in nowscore_markets.py, base_prediction_runner.py, match_workspace.py, automatic_postmatch_review.py and generate_analysis_report.py from actual calls/imports/data writes.
- Actual current consequence: A local behavior change crosses more contracts than its public function suggests.
- Future maintenance/regression consequence: Repeated-change cost and regression surface grow even where kernel owners are healthy.
- Smallest candidate consolidation boundary (not authorized): Candidate: behavior-preserving vertical slices around existing owner contracts; file size alone is not a finding and no extraction is authorized here.

### P1-DATA-001 — Repository data is a durable operational store with overlapping workflow writers
- Evidence: Workflow map identifies contents:write plus git add/commit/push in production workflows; overlapping main-write namespaces include workspace, market history, reports, postmatch and crosswalk paths, while the same durable writer surface also touches runtime, universe, model-governance and prospective paths.
- Actual current consequence: Concurrent/manual/scheduled runs can contend over adjacent state even where concurrency groups exist only in some workflows.
- Future maintenance/regression consequence: Every new artifact needs a write owner, serialization rule, and immutable/derived classification before CI can safely persist it.
- Smallest candidate consolidation boundary (not authorized): Candidate: namespace-level write ownership and one serialization contract, preserving immutable history and current projections separately.

### P1-CI-001 — Global collection safety net is broken while focused gates remain green
- Evidence: Required collection command fails at tests/test_live_ev_profile.py importing missing build_public_site.PUBLIC_DATA_DIRS; existing ownership guards cover selected kernel/evaluation/generated-state domains only.
- Actual current consequence: A repository-wide test run cannot currently establish a green baseline, and new architecture boundaries outside guarded zones can regress unnoticed.
- Future maintenance/regression consequence: Teams may over-trust focused checks and spend repeated effort diagnosing environment/test-surface drift.
- Smallest candidate consolidation boundary (not authorized): Candidate: restore collection contract in a separately authorized change, then expand architecture fitness coverage; this audit does not patch it.

### P2-LEGACY-001 — Legacy and milestone workflows remain resident
- Evidence: Workflow classification lists research/probe, historical milestone, contract gate, and production workflows together; compatibility modules and legacy fixtures remain reachable.
- Actual current consequence: It is harder to tell which path is a current owner versus historical evidence or a compatibility surface.
- Future maintenance/regression consequence: Cleanup/deprecation work can accidentally remove a still-reachable path or preserve obsolete validation indefinitely.
- Smallest candidate consolidation boundary (not authorized): Candidate: explicit lifecycle labels and reachability tests before any deletion; no workflow or legacy removal is authorized here.

## Candidate consolidation sequence — hypothesis only

1. Characterize and lock timestamp/naive-time semantics at current consumer boundaries.
2. Characterize deterministic identity precedence versus presentation-only compatibility joins, without changing alias/mapping truth.
3. Establish root runtime versus product runtime reachability and write ownership before any migration.
4. Separate provider transport/parsing from orchestration only through behavior-preserving owner contracts.
5. Restore global collection, then extend architecture guards to the uncovered identity/time/runtime/projection boundaries.

Each item is a candidate boundary derived from this audit, not an implementation instruction. Independent acceptance and a separately authorized Issue are required before any slice.

## Explicit non-actions

- No production source/provider/model/Champion/Serving/UI behavior changed.
- No identity alias or mapping changed; PR #267 was not repaired.
- No workflow behavior, runtime data, frozen/history/prospective truth, or dependency changed.
- No raw data/page content was added to the artifacts.
