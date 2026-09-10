#!/usr/bin/env python3
"""Generate a compact, read-only ownership and maintenance audit for FBOS.

The audit intentionally scans source/configuration paths only.  It enumerates
data paths for ownership counts but never opens, hashes, or copies historical
data files.  The output is evidence for Issue #268, not a refactor tool.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


CONTRACT_VERSION = "whole_code_architecture_ownership_audit.r1"
ALLOWED_DECISIONS = frozenset(
    {"ARCHITECTURE_CONSOLIDATION_REQUIRED", "BOUNDED_DEBT_ONLY", "FAIL_CLOSED"}
)
AUDIT_OUTPUT_RELATIVE = Path("docs/architecture-audit/issue-268-r1")
AUDIT_TOOL_PATHS = {
    "scripts/architecture_audit.py",
    "tests/test_architecture_audit.py",
}


DATA_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "namespace": "05_RUNTIME_STATE.json",
        "classification": "legacy root runtime state",
        "canonical_or_derived": "legacy/compatibility",
        "ownership_boundary": "legacy runtime consumers remain reachable; no single current-state owner is established",
        "concurrency_write_risk": "HIGH: root file is a mutable operational surface outside data/product_runtime",
    },
    {
        "namespace": "data/product_runtime",
        "classification": "current product runtime projection",
        "canonical_or_derived": "derived/current",
        "ownership_boundary": "automation_cycle and production_health_watch produce/read current-cycle health; dashboard/build projection consumes it",
        "concurrency_write_risk": "HIGH: durable workflows stage and write the namespace",
    },
    {
        "namespace": "data/prediction_universe",
        "classification": "legal current/future fixture input",
        "canonical_or_derived": "canonical input snapshot",
        "ownership_boundary": "prediction_universe and schedule intake define the accepted fixture surface",
        "concurrency_write_risk": "HIGH: current and next publication state must remain chronology-safe",
    },
    {
        "namespace": "data/base_prediction_jobs",
        "classification": "base prediction job ledger",
        "canonical_or_derived": "derived operational ledger",
        "ownership_boundary": "base_prediction_jobs synchronizes jobs from the accepted prediction universe",
        "concurrency_write_risk": "MEDIUM: repeat sync and workflow serialization are required",
    },
    {
        "namespace": "data/model_governance/predictions",
        "classification": "governed prediction records",
        "canonical_or_derived": "immutable/generated truth",
        "ownership_boundary": "model_governance and base_prediction_runner own freeze and governance writes",
        "concurrency_write_risk": "HIGH: frozen records must not be rewritten or backfilled",
    },
    {
        "namespace": "data/model_governance/input_snapshots",
        "classification": "prediction-time input snapshots",
        "canonical_or_derived": "immutable evidence",
        "ownership_boundary": "model_governance/base runner freeze boundary owns point-in-time inputs",
        "concurrency_write_risk": "HIGH: source cutoff and content identity must remain immutable",
    },
    {
        "namespace": "data/model_governance/prediction_exclusions",
        "classification": "governance exclusion ledger",
        "canonical_or_derived": "derived governance state",
        "ownership_boundary": "model governance exclusion paths",
        "concurrency_write_risk": "MEDIUM: exclusion updates can alter downstream coverage",
    },
    {
        "namespace": "data/match_workspace",
        "classification": "match workspace projection",
        "canonical_or_derived": "derived/current and historical projection",
        "ownership_boundary": "match_workspace owns workspace/report attachment and rendering compatibility",
        "concurrency_write_risk": "HIGH: workspace joins runtime state, reports, reviews, and identity fallbacks",
    },
    {
        "namespace": "data/match_analysis",
        "classification": "match analysis artifacts",
        "canonical_or_derived": "derived report input/output",
        "ownership_boundary": "match_analysis and report generation paths",
        "concurrency_write_risk": "MEDIUM: report identity and current/latest selection are coupled",
    },
    {
        "namespace": "data/match_archive",
        "classification": "archived match artifacts",
        "canonical_or_derived": "historical/derived archive",
        "ownership_boundary": "archive and compatibility readers",
        "concurrency_write_risk": "MEDIUM: archive identity must not be confused with current serving state",
    },
    {
        "namespace": "data/analysis_reports",
        "classification": "analysis report artifacts",
        "canonical_or_derived": "derived historical/report output",
        "ownership_boundary": "generate_analysis_report and analysis workflow paths",
        "concurrency_write_risk": "MEDIUM: report generation and workspace projections share joins",
    },
    {
        "namespace": "data/analysis_inputs",
        "classification": "analysis inputs",
        "canonical_or_derived": "derived/acquisition input",
        "ownership_boundary": "analysis acquisition and selected-match workflow paths",
        "concurrency_write_risk": "MEDIUM: input freshness and report identity are not one owner",
    },
    {
        "namespace": "data/fetch_runs",
        "classification": "provider fetch run manifests",
        "canonical_or_derived": "acquisition evidence/operational ledger",
        "ownership_boundary": "fetch and parser run bookkeeping",
        "concurrency_write_risk": "HIGH: run provenance and source cutoff must remain append-safe",
    },
    {
        "namespace": "data/analysis_jobs",
        "classification": "analysis job state",
        "canonical_or_derived": "derived operational state",
        "ownership_boundary": "core automatic analysis orchestration",
        "concurrency_write_risk": "HIGH: scheduled and manual workflows can touch adjacent job state",
    },
    {
        "namespace": "data/postmatch_automation",
        "classification": "postmatch queue/result automation",
        "canonical_or_derived": "derived operational state",
        "ownership_boundary": "postmatch queue, schedule, and one-shot workflow paths",
        "concurrency_write_risk": "HIGH: result lifecycle and legacy runtime state are coupled",
    },
    {
        "namespace": "data/postmatch_dashboard",
        "classification": "postmatch dashboard projection",
        "canonical_or_derived": "derived/public projection",
        "ownership_boundary": "postmatch dashboard builder and public projection readers",
        "concurrency_write_risk": "MEDIUM: projection refresh must not mutate review truth",
    },
    {
        "namespace": "data/postmatch_results",
        "classification": "postmatch result truth",
        "canonical_or_derived": "verified result input",
        "ownership_boundary": "postmatch result/evaluation paths",
        "concurrency_write_risk": "HIGH: regulation-90m and identity joins must remain immutable",
    },
    {
        "namespace": "data/postmatch_reviews",
        "classification": "postmatch review/evaluation artifacts",
        "canonical_or_derived": "derived evaluation output",
        "ownership_boundary": "automatic_postmatch_review and settlement consumers",
        "concurrency_write_risk": "HIGH: evaluation must consume frozen prematch truth only",
    },
    {
        "namespace": "data/postmatch_reports",
        "classification": "postmatch report projection",
        "canonical_or_derived": "derived public/report output",
        "ownership_boundary": "postmatch report and dashboard projection paths",
        "concurrency_write_risk": "MEDIUM: report rendering and evaluation data are coupled",
    },
    {
        "namespace": "data/market_history",
        "classification": "market timeline/history",
        "canonical_or_derived": "evidence/history",
        "ownership_boundary": "market history capture and report/postmatch readers",
        "concurrency_write_risk": "HIGH: point-in-time ordering and append/write serialization matter",
    },
    {
        "namespace": "data/prediction_quality/market_side_shadow_1",
        "classification": "Market-Side immutable pairs and compact index",
        "canonical_or_derived": "research evidence plus derived current index",
        "ownership_boundary": "market_side_shadow persistence/index and Challenger review consumers",
        "concurrency_write_risk": "HIGH: pair files are immutable; compact view is derived",
    },
    {
        "namespace": "data/prospective/football_evidence",
        "classification": "prospective football evidence",
        "canonical_or_derived": "prospective evidence",
        "ownership_boundary": "base runner/evidence sidecar and prospective readers",
        "concurrency_write_risk": "HIGH: frozen/prematch chronology and one-match observation rules",
    },
    {
        "namespace": "data/prospective",
        "classification": "prospective ledgers and summaries",
        "canonical_or_derived": "derived/prospective evaluation",
        "ownership_boundary": "prospective evidence, settlement ledger, and summary projections",
        "concurrency_write_risk": "HIGH: prospective truth must remain separate from pilot/legacy evidence",
    },
    {
        "namespace": "data/football_data",
        "classification": "football data runtime and catalogs",
        "canonical_or_derived": "mixed canonical runtime/legacy research",
        "ownership_boundary": "football_data package contracts, storage, providers, and migration paths",
        "concurrency_write_risk": "HIGH: isolated runtime home versus tracked catalogs/cache compatibility",
    },
    {
        "namespace": "data/provider_match_crosswalk.json",
        "classification": "provider match crosswalk",
        "canonical_or_derived": "identity evidence",
        "ownership_boundary": "provider identity/crosswalk paths",
        "concurrency_write_risk": "HIGH: verified identity must not be overwritten by fuzzy suggestions",
    },
    {
        "namespace": "data/team_aliases.json",
        "classification": "team alias registry",
        "canonical_or_derived": "identity compatibility evidence",
        "ownership_boundary": "team identity and reviewed alias consumers",
        "concurrency_write_risk": "HIGH: alias propagation can change cross-provider identity joins",
    },
    {
        "namespace": "data/live_ev_profiles",
        "classification": "live EV profile artifacts",
        "canonical_or_derived": "derived/research or legacy",
        "ownership_boundary": "live odds bridge/profile paths",
        "concurrency_write_risk": "MEDIUM: runtime state and profile joins remain compatibility-coupled",
    },
    {
        "namespace": "data/schedule_updates",
        "classification": "schedule acquisition updates",
        "canonical_or_derived": "acquisition evidence",
        "ownership_boundary": "schedule and current-universe intake paths",
        "concurrency_write_risk": "HIGH: current/future publication and source chronology",
    },
    {
        "namespace": "data/live_odds_bridge",
        "classification": "live odds bridge artifacts",
        "canonical_or_derived": "derived/live compatibility",
        "ownership_boundary": "live_odds_bridge capture and profile consumers",
        "concurrency_write_risk": "MEDIUM: live quote snapshots must remain separated from prematch truth",
    },
    {
        "namespace": "data/market_audits",
        "classification": "market audit artifacts",
        "canonical_or_derived": "derived/audit evidence",
        "ownership_boundary": "market audit scripts and historical review paths",
        "concurrency_write_risk": "MEDIUM: audit output must not become a market source of truth",
    },
    {
        "namespace": "data/model_benchmarks",
        "classification": "model benchmark artifacts",
        "canonical_or_derived": "research/benchmark evidence",
        "ownership_boundary": "benchmark, replay, and settlement comparison paths",
        "concurrency_write_risk": "MEDIUM: benchmark output must remain outside Champion promotion state",
    },
    {
        "namespace": "data/model_calibration",
        "classification": "model calibration artifacts",
        "canonical_or_derived": "governed calibration evidence",
        "ownership_boundary": "calibration build and model input consumers",
        "concurrency_write_risk": "HIGH: calibration changes must not rewrite frozen predictions",
    },
    {
        "namespace": "data/paper_ledger",
        "classification": "paper ledger artifacts",
        "canonical_or_derived": "derived/operational ledger",
        "ownership_boundary": "paper/real-bet recording and postmatch review paths",
        "concurrency_write_risk": "HIGH: ledger append and settlement joins require serialization",
    },
    {
        "namespace": "data/prediction_dashboard",
        "classification": "prediction dashboard projection",
        "canonical_or_derived": "derived/public projection",
        "ownership_boundary": "prediction dashboard builder and public projection readers",
        "concurrency_write_risk": "MEDIUM: projection refresh must not mutate prediction truth",
    },
    {
        "namespace": "data/prediction_quality",
        "classification": "prediction quality and shadow evidence",
        "canonical_or_derived": "derived/evaluation and research evidence",
        "ownership_boundary": "quality audits, Market-Side shadow, and challenger review paths",
        "concurrency_write_risk": "HIGH: immutable pairs and derived indexes need separate write contracts",
    },
    {
        "namespace": "data/risk_audits",
        "classification": "risk audit artifacts",
        "canonical_or_derived": "derived/audit evidence",
        "ownership_boundary": "risk_engine and risk audit/report paths",
        "concurrency_write_risk": "MEDIUM: risk evidence must remain distinguishable from settlement truth",
    },
    {
        "namespace": "data/source_cache",
        "classification": "provider/source cache",
        "canonical_or_derived": "acquisition cache/legacy",
        "ownership_boundary": "fetch/parser cache compatibility paths",
        "concurrency_write_risk": "HIGH: cache freshness and raw-source retention must not enter formal evidence without provenance",
    },
)


DOMAIN_ROWS = (
    {
        "domain": "match/team/provider identity",
        "owners": "scripts/match_identity.py; scripts/team_identity.py; scripts/football_data/entity_resolution.py; provider-specific parsers",
        "callers": "prediction_universe.py, base_prediction_jobs.py, postmatch_queue.py, match_workspace.py, provider registries, State Memory",
        "collision": "canonical_match_id, provider-ID precedence, local fallbacks, reviewed aliases, and SequenceMatcher workspace joins coexist; differences are not all equivalent",
        "clarity": "MIXED / consolidation candidate",
    },
    {
        "domain": "kickoff/timezone/chronology",
        "owners": "match_identity.parse_kickoff; current_serving_state._parse_timestamp; postmatch_queue.parse_datetime; match_workspace.parse_kickoff_local; prematch_versioning._parse_timestamp; football_data runtime parsers",
        "callers": "serving, job sync, workspace, postmatch, provenance and snapshot paths",
        "collision": "naive timestamps are interpreted as UTC, Shanghai, or rejected by different live consumers",
        "clarity": "P0 MULTIPLE SEMANTIC AUTHORITIES",
    },
    {
        "domain": "provider HTTP/retry/cache/parsing",
        "owners": "scripts/nowscore_markets.py; scripts/fetch_and_parse.py; scripts/fetch_sporttery.py; scripts/football_data/providers/*; scripts/live_odds_bridge.py",
        "callers": "prematch monitor, prediction runner, selected analysis, State Memory, provider adapters and probes",
        "collision": "Nowscore transport, cache, market/analysis parsing and identity are combined; football_data has a separate provider protocol and runtime transport",
        "clarity": "MIXED / high coupling",
    },
    {
        "domain": "competition/season resolution",
        "owners": "scripts/football_data/competition_resolution.py; competition_demand.py; coverage_registry.py; parser-local labels",
        "callers": "football_data catalogs, prediction universe, recent-form and coverage paths",
        "collision": "canonical football_data resolution exists alongside provider/page label handling and legacy report labels",
        "clarity": "BOUNDED WITH COMPATIBILITY EDGES",
    },
    {
        "domain": "evidence provenance / point-in-time safety",
        "owners": "scripts/model_governance.py; prematch_versioning.py; base_prediction_runner.py; football_data contracts/runtime snapshot; football_state_memory.py",
        "callers": "freeze, serving, reports, prospective evaluation and production health",
        "collision": "several timestamp/provenance envelopes and sidecars are composed by orchestration modules rather than one evidence boundary",
        "clarity": "MIXED / high regression risk",
    },
    {
        "domain": "prediction-universe/base-job/current-serving state",
        "owners": "prediction_universe.py; base_prediction_jobs.py; current_serving_state.py; automation_cycle.py",
        "callers": "production workflows, dashboard, prediction runner, postmatch and health",
        "collision": "current/future publication, job ledger and current serving each select/normalize identity separately",
        "clarity": "MIXED / ownership map incomplete",
    },
    {
        "domain": "model input + model governance/freeze",
        "owners": "automatic_model_core.py; model_governance.py; base_prediction_runner.py; exact_distribution.py",
        "callers": "production base cycle, report generation, benchmark/replay and settlement",
        "collision": "healthy freeze/kernel boundaries exist, but runner/report orchestration still spans acquisition, model input, freeze and side effects",
        "clarity": "HEALTHY CORE / ORCHESTRATION COUPLING",
    },
    {
        "domain": "market math / score math / contract settlement",
        "owners": "market_engine.py; score_engine.py; market_contracts.py; evaluation_kernel.py",
        "callers": "automatic model, baseline, settlement, report and prospective paths",
        "collision": "accepted owner map and guards show these core semantics are consolidated; compatibility re-exports remain intentional",
        "clarity": "HEALTHY CONTROL ZONE",
    },
    {
        "domain": "evaluation/settlement",
        "owners": "evaluation_kernel.py; baseline_settlement.py; prospective_settlement.py; automatic_postmatch_review.py",
        "callers": "postmatch review, baseline, Market-Side and production reports",
        "collision": "kernel owns shared formulas; wager/market-specific and report shaping remain separate as intended",
        "clarity": "HEALTHY CORE / BOUNDED COMPATIBILITY",
    },
    {
        "domain": "postmatch lifecycle",
        "owners": "postmatch_queue.py; postmatch_schedule.py; postmatch_result.py; automatic_postmatch_review.py; sync_result_schedules.py",
        "callers": "postmatch workflow, workspace, result schedule and evaluation",
        "collision": "queue/report/runtime identity fallbacks and evaluation inputs cross lifecycle boundaries",
        "clarity": "MIXED / lifecycle consolidation candidate",
    },
    {
        "domain": "runtime/health state",
        "owners": "automation_cycle.py; production_health_watch.py; current_serving_state.py; root 05_RUNTIME_STATE consumers",
        "callers": "deploy pages, dashboard, UI evidence, workspace, live bridge, postmatch and health gates",
        "collision": "data/product_runtime and root 05_RUNTIME_STATE are both reachable current-like state surfaces",
        "clarity": "P0 MULTIPLE STATE AUTHORITIES",
    },
    {
        "domain": "immutable/generated data persistence",
        "owners": "durable_main_write.py; runtime_snapshot.py; market_side_shadow.py; model_governance.py; workflow staging blocks",
        "callers": "deploy, research review, production health, dashboard and postmatch",
        "collision": "repository durable data is operationally written by several scheduled/manual workflows with overlapping namespaces",
        "clarity": "MIXED / write ownership needs explicit map",
    },
    {
        "domain": "public product projection / Match Detail / Dashboard / workspace",
        "owners": "build_public_site.py; prediction_dashboard.py; match_detail.py; match_workspace.py; capture_public_ui_evidence.py",
        "callers": "Pages deployment, visual evidence and workspace refresh",
        "collision": "workspace joins and renders data/runtime/report state while public builder has a selective read-only projection contract",
        "clarity": "MIXED / projection boundary needs characterization",
    },
    {
        "domain": "legacy compatibility",
        "owners": "legacy_analysis_mapper.py; migration scripts; root runtime/report fallbacks; model_baselines/risk_engine re-exports",
        "callers": "current report, workspace, postmatch and benchmark paths plus historical fixtures",
        "collision": "compatibility is intentional in selected kernel APIs, but root runtime and legacy report joins remain reachable from current paths",
        "clarity": "MIXED / deprecation ownership incomplete",
    },
)


FINDING_TEMPLATES = (
    {
        "id": "P0-TIME-001",
        "priority": "P0",
        "title": "Multiple live naive-time semantics",
        "evidence": "AST/symbol scan finds parse_kickoff, _parse_timestamp, parse_datetime, parse_kickoff_local and runtime timestamp parsers in separate modules; R12 records UTC interpretation, Shanghai interpretation, and rejection.",
        "consequence": "The same naive timestamp can select a different current/future record, chronology gate, or postmatch join depending on caller.",
        "future_cost": "Every new workflow/provider must choose among incompatible semantics and can create silent cross-day regression.",
        "boundary": "Candidate: one explicit timezone/naive-input contract at module boundaries, with compatibility adapters characterized before any move.",
    },
    {
        "id": "P0-IDENTITY-001",
        "priority": "P0",
        "title": "Identity authority is distributed across canonical, provider, and presentation joins",
        "evidence": "AST/import and symbol scan shows canonical_match_id consumers plus provider-specific identity, postmatch report_key fallbacks, workspace SequenceMatcher joins, and State Memory/registry paths.",
        "consequence": "A match can be accepted by one consumer and remain unresolved or attach to another report in a different consumer; PR #267 is retained as a counterexample only.",
        "future_cost": "Provider/team naming changes require repeated edits and can alter evaluation/report joins without a single contract test.",
        "boundary": "Candidate: deterministic identity boundary with explicit presentation-only compatibility matching kept outside truth selection; no alias/mapping change is authorized here.",
    },
    {
        "id": "P0-RUNTIME-001",
        "priority": "P0",
        "title": "Root runtime state and product runtime are both reachable",
        "evidence": "Static references show 05_RUNTIME_STATE.json in fetch_football_data, live_odds_bridge, match_workspace, postmatch_dashboard, postmatch_queue and report defaults, while automation/dashboard/health use data/product_runtime.",
        "consequence": "Health/current-state consumers can observe different state surfaces and a stale root file can remain operationally relevant.",
        "future_cost": "Runtime changes need dual-path compatibility and race analysis; deleting either path without reachability proof risks silent stale state.",
        "boundary": "Candidate: establish one current runtime owner and an explicit read-only compatibility adapter after reachability inventory; no data migration is authorized.",
    },
    {
        "id": "P1-IMPORT-001",
        "priority": "P1",
        "title": "Import architecture has path mutation and dual import modes",
        "evidence": "AST scan enumerates sys.path mutations and try/except ImportError direct-versus-package imports; high fan-in/fan-out modules connect provider, governance, report and runtime layers.",
        "consequence": "The same module can execute under different import identities, and dependency direction is harder to enforce in tests and workflows.",
        "future_cost": "Refactors need repeated compatibility edits and can hide cycles or import-order-only behavior.",
        "boundary": "Candidate: package/import boundary characterization and incremental removal of only proven duplicate import paths.",
    },
    {
        "id": "P1-ORCH-001",
        "priority": "P1",
        "title": "Several orchestration modules combine acquisition, domain policy, persistence, and projection",
        "evidence": "Responsibility inventory marks mixed-layer coupling in nowscore_markets.py, base_prediction_runner.py, match_workspace.py, automatic_postmatch_review.py and generate_analysis_report.py from actual calls/imports/data writes.",
        "consequence": "A local behavior change crosses more contracts than its public function suggests.",
        "future_cost": "Repeated-change cost and regression surface grow even where kernel owners are healthy.",
        "boundary": "Candidate: behavior-preserving vertical slices around existing owner contracts; file size alone is not a finding and no extraction is authorized here.",
    },
    {
        "id": "P1-DATA-001",
        "priority": "P1",
        "title": "Repository data is a durable operational store with overlapping workflow writers",
        "evidence": "Workflow map identifies contents:write plus git add/commit/push in production workflows; overlapping main-write namespaces include workspace, market history, reports, postmatch and crosswalk paths, while the same durable writer surface also touches runtime, universe, model-governance and prospective paths.",
        "consequence": "Concurrent/manual/scheduled runs can contend over adjacent state even where concurrency groups exist only in some workflows.",
        "future_cost": "Every new artifact needs a write owner, serialization rule, and immutable/derived classification before CI can safely persist it.",
        "boundary": "Candidate: namespace-level write ownership and one serialization contract, preserving immutable history and current projections separately.",
    },
    {
        "id": "P1-CI-001",
        "priority": "P1",
        "title": "Global collection safety net is broken while focused gates remain green",
        "evidence": "Required collection command fails at tests/test_live_ev_profile.py importing missing build_public_site.PUBLIC_DATA_DIRS; existing ownership guards cover selected kernel/evaluation/generated-state domains only.",
        "consequence": "A repository-wide test run cannot currently establish a green baseline, and new architecture boundaries outside guarded zones can regress unnoticed.",
        "future_cost": "Teams may over-trust focused checks and spend repeated effort diagnosing environment/test-surface drift.",
        "boundary": "Candidate: restore collection contract in a separately authorized change, then expand architecture fitness coverage; this audit does not patch it.",
    },
    {
        "id": "P2-LEGACY-001",
        "priority": "P2",
        "title": "Legacy and milestone workflows remain resident",
        "evidence": "Workflow classification lists research/probe, historical milestone, contract gate, and production workflows together; compatibility modules and legacy fixtures remain reachable.",
        "consequence": "It is harder to tell which path is a current owner versus historical evidence or a compatibility surface.",
        "future_cost": "Cleanup/deprecation work can accidentally remove a still-reachable path or preserve obsolete validation indefinitely.",
        "boundary": "Candidate: explicit lifecycle labels and reachability tests before any deletion; no workflow or legacy removal is authorized here.",
    },
)


def _repo_path(root: Path, relative: str) -> Path:
    return root / Path(relative)


def _tracked_files(root: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "-c", "core.quotePath=false", "ls-files", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return [path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()]
    return [item.decode("utf-8", errors="replace") for item in completed.stdout.split(b"\0") if item]


def _scope_files(root: Path, tracked: Sequence[str], prefix: str, suffixes: Iterable[str] | None = None) -> list[Path]:
    suffix_set = {suffix.casefold() for suffix in suffixes} if suffixes else None
    paths = []
    for relative in tracked:
        normalized = relative.replace("\\", "/")
        if not normalized.startswith(prefix.rstrip("/") + "/"):
            continue
        path = root / Path(relative)
        if not path.is_file() or (suffix_set and path.suffix.casefold() not in suffix_set):
            continue
        if normalized in AUDIT_TOOL_PATHS:
            continue
        paths.append(path)
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _module_name(relative: str) -> str:
    parts = list(Path(relative).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _module_aliases(module: str) -> set[str]:
    aliases = {module}
    if module.startswith("scripts."):
        aliases.add(module[len("scripts."):])
    if module.startswith("tests."):
        aliases.add(module[len("tests."):])
    return aliases


def _constant_strings(tree: ast.AST) -> list[str]:
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def _path_namespace_matches(values: Iterable[str]) -> set[str]:
    joined = "\n".join(values).replace("\\", "/")
    matches: set[str] = set()
    for entry in DATA_CATALOG:
        namespace = entry["namespace"]
        if namespace in joined:
            matches.add(namespace)
            continue
        if namespace.startswith("data/"):
            tail = namespace[len("data/"):]
            if re.search(rf"(?:data[\"']?\s*/\s*[\"']?|[\"']){re.escape(tail)}(?:[\"'/]|\b)", joined):
                matches.add(namespace)
    return matches


def _call_name(node: ast.Call) -> str:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return ""


class _DataAccessVisitor(ast.NodeVisitor):
    WRITE_CALLS = {"write_text", "write_bytes", "dump", "atomic_write", "atomic_write_json", "replace", "rename", "unlink", "mkdir"}
    READ_CALLS = {"read_text", "read_bytes", "load", "exists", "is_file", "glob", "rglob", "iterdir"}

    def __init__(self) -> None:
        self.reads: set[str] = set()
        self.writes: set[str] = set()

    def _strings(self, node: ast.AST) -> list[str]:
        return _constant_strings(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        name = _call_name(node)
        values = self._strings(node)
        namespaces = _path_namespace_matches(values)
        if name in self.WRITE_CALLS:
            self.writes.update(namespaces)
        if name in self.READ_CALLS:
            self.reads.update(namespaces)
        if name == "open":
            mode = "r"
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                mode = str(node.args[1].value)
            if any(flag in mode for flag in ("w", "a", "x", "+")):
                self.writes.update(namespaces)
            else:
                self.reads.update(namespaces)
        self.generic_visit(node)


def _import_records(tree: ast.AST, current_module: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                records.append({"module": alias.name, "kind": "import", "level": 0})
        elif isinstance(node, ast.ImportFrom):
            imported = node.module or ""
            records.append({"module": imported, "kind": "from", "level": node.level})
    return records


def _resolve_import(source_module: str, record: Mapping[str, Any], aliases: Mapping[str, str | None]) -> str | None:
    imported = str(record.get("module") or "")
    level = int(record.get("level") or 0)
    if level:
        source_parts = source_module.split(".")
        package_parts = source_parts[:-1]
        if level > len(package_parts) + 1:
            return None
        base = package_parts[: len(package_parts) - level + 1]
        imported = ".".join([*base, imported] if imported else base)
    candidates = [imported]
    for alias in sorted(aliases, key=len, reverse=True):
        if imported == alias or imported.startswith(alias + "."):
            candidates.append(alias)
    for candidate in candidates:
        resolved = aliases.get(candidate)
        if resolved:
            return resolved
    return None


def _extract_try_imports(node: ast.Try) -> tuple[list[str], list[str]]:
    def imports(nodes: Iterable[ast.AST]) -> list[str]:
        found: list[str] = []
        for child in nodes:
            for nested in ast.walk(child):
                if isinstance(nested, ast.Import):
                    found.extend(alias.name for alias in nested.names)
                elif isinstance(nested, ast.ImportFrom):
                    found.append(nested.module or "")
        return found

    body_imports = imports(node.body)
    fallback_imports: list[str] = []
    for handler in node.handlers:
        names = set()
        if handler.type is None:
            names.add("Exception")
        elif isinstance(handler.type, ast.Name):
            names.add(handler.type.id)
        elif isinstance(handler.type, ast.Tuple):
            names.update(item.id for item in handler.type.elts if isinstance(item, ast.Name))
        if "ImportError" in names or "Exception" in names:
            fallback_imports.extend(imports(handler.body))
    return body_imports, fallback_imports


def _has_sys_path_mutation(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"insert", "append", "extend"}:
            continue
        target = node.func.value
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "sys" and target.attr == "path":
            return True
    return False


def _layer(module: str) -> str:
    lower = module.casefold()
    if lower.startswith("tests"):
        return "tests"
    if "provider" in lower or "fetch_" in lower or "nowscore" in lower or "sporttery" in lower or "polymarket" in lower:
        return "provider/acquisition"
    if any(token in lower for token in ("dashboard", "public_site", "match_detail", "workspace", "capture_public", "copy")):
        return "public/projection"
    if any(token in lower for token in ("model", "prediction", "baseline", "score_engine", "market_engine", "risk_engine", "exact_distribution")):
        return "model/serving"
    if any(token in lower for token in ("postmatch", "settlement", "evaluation", "review", "result")):
        return "evaluation/postmatch"
    if any(token in lower for token in ("runtime", "automation_cycle", "health", "durable_main_write")):
        return "runtime/persistence"
    if any(token in lower for token in ("identity", "match_identity", "team_identity", "competition")):
        return "identity/competition"
    return "other"


def _responsibility_tags(module: str, text: str, direct_writes: Iterable[str]) -> list[str]:
    lower = f"{module}\n{text}".casefold()
    tags: set[str] = set()
    if module.startswith("tests"):
        tags.add("test")
    if any(token in lower for token in ("canonical_match_id", "identity", "alias", "sequencematcher")):
        tags.add("identity")
    if any(token in lower for token in ("datetime", "kickoff", "timestamp", "timezone", "chronology")):
        tags.add("time/chronology")
    if any(token in lower for token in ("urlopen", "requests.", "retry", "cache", "http", "parser", "parse_")):
        tags.add("acquisition/parsing")
    if any(token in lower for token in ("model", "poisson", "probability", "lambda", "calibration")):
        tags.add("model/math")
    if any(token in lower for token in ("freeze", "governance", "provenance", "source_as_of", "snapshot")):
        tags.add("governance/provenance")
    if any(token in lower for token in ("json", "write_text", "write_bytes", "json.dump", "atomic_write")) or list(direct_writes):
        tags.add("io/persistence")
    if any(token in lower for token in ("html", "render", "dashboard", "workspace", "report")):
        tags.add("projection/report")
    if any(token in lower for token in ("postmatch", "settlement", "evaluation", "result")):
        tags.add("evaluation/postmatch")
    if "legacy" in lower or "migration" in lower or "fallback" in lower or "re-export" in lower:
        tags.add("legacy/compatibility")
    return sorted(tags)


def _role(module: str, tags: Sequence[str]) -> list[str]:
    lower = module.casefold()
    roles: set[str] = set()
    if lower.startswith("tests"):
        roles.add("test")
    elif any(token in lower for token in ("probe", "audit", "research", "experiment", "shadow", "pilot")):
        roles.add("research")
    else:
        roles.add("production")
    if "legacy/compatibility" in tags or "legacy" in lower or "migration" in lower:
        roles.add("legacy-compatible")
    return sorted(roles)


def _consolidation_risk(tags: Sequence[str], local_dependency_count: int, write_count: int) -> str:
    cross_layer = sum(tag in tags for tag in ("acquisition/parsing", "model/math", "governance/provenance", "io/persistence", "projection/report", "evaluation/postmatch"))
    if cross_layer >= 3 or write_count >= 4 or local_dependency_count >= 18:
        return "HIGH"
    if cross_layer >= 2 or write_count >= 2 or local_dependency_count >= 10:
        return "MEDIUM"
    return "LOW"


def _tarjan_cycles(graph: Mapping[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in sorted(graph.get(node, ())):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] != indices[node]:
            return
        component: list[str] = []
        while True:
            target = stack.pop()
            on_stack.remove(target)
            component.append(target)
            if target == node:
                break
        if len(component) > 1:
            components.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return sorted(components)


def _parse_python_modules(root: Path, paths: Sequence[Path]) -> tuple[list[dict[str, Any]], dict[str, set[str]], dict[str, str | None], list[str], list[dict[str, Any]]]:
    aliases: dict[str, str | None] = {}
    parsed: dict[str, tuple[Path, ast.AST, str]] = {}
    parse_errors: list[str] = []
    for path in paths:
        relative = _relative(root, path)
        module = _module_name(relative)
        try:
            # A UTF-8 BOM is valid for a Python source file.  Decode it away
            # before AST parsing so the inventory reports actual syntax
            # failures rather than an encoding marker.
            text = path.read_bytes().decode("utf-8-sig")
            tree = ast.parse(text, filename=relative)
        except (OSError, SyntaxError, UnicodeError) as exc:
            parse_errors.append(f"{relative}: {type(exc).__name__}: {exc}")
            continue
        parsed[module] = (path, tree, text)
        for alias in _module_aliases(module):
            if alias in aliases and aliases[alias] != module:
                aliases[alias] = None
            else:
                aliases[alias] = module

    graph: dict[str, set[str]] = {module: set() for module in parsed}
    records: list[dict[str, Any]] = []
    module_rows: list[dict[str, Any]] = []
    for module, (path, tree, text) in sorted(parsed.items()):
        imports = _import_records(tree, module)
        local_dependencies = {_resolve_import(module, record, aliases) for record in imports}
        local_dependencies.discard(None)
        local_dependencies.discard(module)
        graph[module].update(local_dependencies)  # type: ignore[arg-type]
        external_dependencies = sorted({str(record["module"]) for record in imports if not _resolve_import(module, record, aliases) and record.get("module")})
        data_access = _DataAccessVisitor()
        data_access.visit(tree)
        constants = _constant_strings(tree)
        referenced_namespaces = _path_namespace_matches([*constants, text])
        tags = _responsibility_tags(module, text, data_access.writes)
        functions = sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree))
        classes = sum(isinstance(node, ast.ClassDef) for node in ast.walk(tree))
        fallback_rows: list[dict[str, Any]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            body_imports, fallback_imports = _extract_try_imports(node)
            if body_imports and fallback_imports:
                fallback_rows.append({"module": module, "primary_imports": sorted(set(body_imports)), "fallback_imports": sorted(set(fallback_imports))})
        if fallback_rows:
            records.extend(fallback_rows)
        if _has_sys_path_mutation(tree):
            records.append({"module": module, "type": "sys_path_mutation"})
        module_rows.append(
            {
                "module": module,
                "path": _relative(root, path),
                "loc": len(text.splitlines()),
                "function_count": functions,
                "class_count": classes,
                "local_dependencies": sorted(local_dependencies),
                "external_dependencies": external_dependencies[:40],
                "referenced_data_namespaces": sorted(referenced_namespaces),
                "direct_data_read_namespaces": sorted(data_access.reads),
                "direct_data_write_namespaces": sorted(data_access.writes),
                "responsibility_tags": tags,
                "role": _role(module, tags),
                "consolidation_risk": _consolidation_risk(tags, len(local_dependencies), len(data_access.writes)),
            }
        )
    return module_rows, graph, aliases, parse_errors, records


def _semantic_primitive_inventory(module_rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    primitive_rules = {
        "datetime_timestamp_parsing": ("time/chronology", "Separate datetime/fromisoformat/strptime/naive-time implementations"),
        "identity_extraction_matching_canonical_key": ("identity", "Canonical, provider, alias, and fuzzy/presentation identity consumers"),
        "json_jsonl_io_atomic_write": ("io/persistence", "JSON/JSONL load/dump/write/atomic persistence paths"),
        "provider_request_retry_cache_envelope": ("acquisition/parsing", "HTTP/request/retry/cache/provider envelope implementations"),
        "status_reason_normalization": ("governance/provenance", "Status/reason/failure-stage normalization consumers"),
        "data_root_path_resolution": ("io/persistence", "ROOT/PROJECT_ROOT/DATA_ROOT/path construction"),
        "result_normalization": ("evaluation/postmatch", "Result/outcome normalization and regulation-time mapping"),
        "current_latest_legal_version_selection": ("governance/provenance", "Current/latest/version/legal selection symbols"),
    }
    result: dict[str, dict[str, Any]] = {}
    for name, (tag, note) in primitive_rules.items():
        modules = [row["module"] for row in module_rows if tag in row.get("responsibility_tags", [])]
        result[name] = {"modules": sorted(modules), "module_count": len(modules), "note": note}
    return result


def _dependency_summary(module_rows: Sequence[Mapping[str, Any]], graph: Mapping[str, set[str]], records: Sequence[Mapping[str, Any]], aliases: Mapping[str, str | None], parse_errors: Sequence[str]) -> dict[str, Any]:
    fan_in = Counter(target for targets in graph.values() for target in targets)
    fan_out = Counter(module for module, targets in graph.items() for _target in targets)
    high_in = [{"module": module, "count": count} for module, count in sorted(fan_in.items(), key=lambda item: (-item[1], item[0]))[:20]]
    high_out = [{"module": module, "count": count} for module, count in sorted(fan_out.items(), key=lambda item: (-item[1], item[0]))[:20]]
    sys_path = sorted({record["module"] for record in records if record.get("type") == "sys_path_mutation"})
    fallbacks = sorted(
        [record for record in records if record.get("primary_imports")],
        key=lambda record: (record["module"], record["primary_imports"], record["fallback_imports"]),
    )
    cross_layer: list[dict[str, str]] = []
    for source, targets in sorted(graph.items()):
        for target in sorted(targets):
            source_layer, target_layer = _layer(source), _layer(target)
            if source_layer != target_layer and source_layer != "tests" and target_layer != "other":
                cross_layer.append({"source": source, "source_layer": source_layer, "target": target, "target_layer": target_layer})
    return {
        "local_module_count": len(graph),
        "local_edge_count": sum(len(targets) for targets in graph.values()),
        "python_parse_errors": list(parse_errors),
        "cycles": _tarjan_cycles(graph),
        "high_fan_in": high_in,
        "high_fan_out": high_out,
        "sys_path_mutations": sys_path,
        "dual_import_fallbacks": fallbacks,
        "cross_layer_edges": cross_layer,
        "ambiguous_import_aliases": sorted(alias for alias, value in aliases.items() if value is None),
    }


def _data_file_counts(tracked: Sequence[str]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for relative in tracked:
        normalized = relative.replace("\\", "/")
        if not normalized.startswith("data/"):
            continue
        matched = None
        for entry in sorted(DATA_CATALOG, key=lambda item: len(item["namespace"]), reverse=True):
            namespace = entry["namespace"]
            if normalized == namespace or normalized.startswith(namespace + "/"):
                matched = namespace
                break
        if matched:
            counts[matched] += 1
    return dict(counts)


def _data_write_read_map(
    module_rows: Sequence[Mapping[str, Any]],
    tracked: Sequence[str],
    workflows: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    counts = _data_file_counts(tracked)
    workflow_rows = (workflows or {}).get("workflows", [])
    namespaces: list[dict[str, Any]] = []
    for entry in DATA_CATALOG:
        namespace = entry["namespace"]
        code_readers = sorted({row["module"] for row in module_rows if namespace in row.get("direct_data_read_namespaces", [])})
        code_writers = sorted({row["module"] for row in module_rows if namespace in row.get("direct_data_write_namespaces", [])})
        references = sorted({row["module"] for row in module_rows if namespace in row.get("referenced_data_namespaces", [])})
        workflow_references = sorted({row["file"] for row in workflow_rows if namespace in row.get("write_namespaces", [])})
        workflow_writers = sorted(
            {
                row["file"]
                for row in workflow_rows
                if row.get("can_write_main") and namespace in row.get("write_namespaces", [])
            }
        )
        namespaces.append(
            {
                **entry,
                "tracked_file_count": counts.get(namespace, 0),
                "readers": code_readers,
                "writers": sorted(set(code_writers).union(workflow_writers)),
                "code_readers": code_readers,
                "code_writers": code_writers,
                "workflow_references": workflow_references,
                "workflow_writers": workflow_writers,
                "referencing_modules": references,
                "unclassified_code_references": sorted(set(references).difference(code_readers, code_writers)),
            }
        )
    return {
        "scan_policy": "paths_only_no_data_contents",
        "tracked_data_file_count": sum(counts.values()),
        "tracked_data_namespace_counts": dict(sorted(counts.items())),
        "workflow_writer_evidence_is_limited_to_explicit_git_write_paths": True,
        "namespaces": namespaces,
    }


def _json_contract_inventory(root: Path, paths: Sequence[Path]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    for path in paths:
        relative = _relative(root, path)
        if path.suffix.casefold() != ".json":
            records.append({"path": relative, "format": "not-json", "status": "NOT_PARSED"})
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            message = f"{relative}: {type(exc).__name__}: {exc}"
            parse_errors.append(message)
            records.append({"path": relative, "format": "json", "status": "FAILED"})
            continue
        records.append(
            {
                "path": relative,
                "format": "json",
                "status": "PASS",
                "top_level_type": type(payload).__name__,
            }
        )
    return {
        "files": records,
        "json_file_count": sum(record["format"] == "json" for record in records),
        "json_parse_errors": parse_errors,
    }


def _workflow_events(text: str) -> list[str]:
    known = ("push", "pull_request", "pull_request_target", "workflow_dispatch", "repository_dispatch", "schedule", "issues", "workflow_call")
    return sorted({event for event in known if re.search(rf"^\s{{0,2}}{re.escape(event)}\s*:", text, re.MULTILINE)})


def _workflow_name(text: str, path: Path) -> str:
    found = re.search(r"^name:\s*[\"']?(.*?)[\"']?\s*$", text, re.MULTILINE)
    return found.group(1).strip() if found else path.stem


def _workflow_paths(text: str) -> list[str]:
    paths = set(re.findall(r"(?<![A-Za-z0-9_])data/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", text.replace("\\", "/")))
    paths.update(re.findall(r"(?<![A-Za-z0-9_])05_RUNTIME_STATE\.json", text))
    return sorted(paths)


def _workflow_classification(relative: str, name: str, text: str) -> tuple[str, str]:
    lower = f"{relative} {name}".casefold()
    durable_write_path = bool(re.search(r"contents:\s*write", text)) and bool(
        re.search(r"\bgit\s+(?:add|commit|push)\b", text)
    )
    if any(token in lower for token in ("deploy-pages", "core-auto-analysis", "postmatch-once", "prematch-market-monitor", "record-real-bet", "deploy minute checkpoint")) or durable_write_path:
        return "durable production workflow", "production trigger/deploy or durable contents-write path"
    if any(token in lower for token in ("state memory", "exact distribution", "jc handicap", "data-plane", "production base prediction timeout")):
        return "durable architecture/contract gate", "focused contract/readiness validation path"
    if "architecture-audit" in lower:
        return "durable architecture/contract gate", "read-only architecture evidence gate"
    if any(token in lower for token in ("probe", "analyze selected", "pure market", "challenger")):
        return "active research/probe", "research/probe or challenger-specific trigger/path"
    if "public ui visual evidence" in lower:
        return "historical milestone workflow still resident", "milestone-specific visual evidence gate remains in main"
    if ".github/actions" in lower or "bootstrap-football-data" in lower:
        return "durable architecture/contract gate", "reusable runtime/bootstrap contract"
    return "unknown / needs review", "no deterministic classification rule matched"


def _workflow_map(root: Path, paths: Sequence[Path]) -> dict[str, Any]:
    workflows: list[dict[str, Any]] = []
    for path in paths:
        relative = _relative(root, path)
        text = path.read_text(encoding="utf-8", errors="replace")
        name = _workflow_name(text, path)
        classification, reason = _workflow_classification(relative, name, text)
        contents_write = bool(re.search(r"contents:\s*write", text))
        git_write = bool(re.search(r"\bgit\s+(?:add|commit|push)\b|\bgh\s+workflow\s+run\b", text))
        write_paths = _workflow_paths(text)
        workflows.append(
            {
                "file": relative,
                "name": name,
                "triggers": _workflow_events(text),
                "classification": classification,
                "classification_reason": reason,
                "contents_write_permission": contents_write,
                "git_write_commands_present": git_write,
                "can_write_main": contents_write and git_write,
                "write_namespaces": write_paths,
                "concurrency_declared": bool(re.search(r"^concurrency:", text, re.MULTILINE)),
            }
        )
    writers_by_namespace: defaultdict[str, list[str]] = defaultdict(list)
    for workflow in workflows:
        for namespace in workflow["write_namespaces"]:
            if workflow["can_write_main"]:
                writers_by_namespace[namespace].append(workflow["file"])
    overlaps = {namespace: sorted(files) for namespace, files in writers_by_namespace.items() if len(files) > 1}
    return {"workflow_count": len(workflows), "workflows": workflows, "overlapping_main_write_namespaces": overlaps}


def _test_collection_evidence(root: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": "python -m pytest --collect-only -q", "status": "NOT_OBTAINED", "error": type(exc).__name__}
    output = f"{completed.stdout}\n{completed.stderr}"
    # Keep the evidence portable between a local Windows checkout and the
    # exact-head Linux Actions checkout.  The repository-relative error and
    # symbol remain; an absolute workspace path is not audit evidence.
    normalized_output = output
    for prefix in {str(root), root.as_posix(), str(root).replace("\\", "/")}:
        normalized_output = normalized_output.replace(prefix, "<repo>")
    collected = re.findall(r"(\d+) tests collected", normalized_output)
    error_files = re.findall(r"ERROR collecting (tests/[^\s]+)", normalized_output)
    import_errors = re.findall(r"ImportError: cannot import name [^\n]+", normalized_output)
    return {
        "command": "python -m pytest --collect-only -q",
        "status": "PASS" if completed.returncode == 0 else "FAILED_DURING_COLLECTION",
        "return_code": completed.returncode,
        "collected_tests_before_failure": int(collected[-1]) if collected else None,
        "error_files": sorted(set(error_files)),
        "import_errors": sorted(set(import_errors)),
    }


def _decision(inventory: Mapping[str, Any], dependencies: Mapping[str, Any], data_map: Mapping[str, Any], workflows: Mapping[str, Any]) -> str:
    if inventory.get("python_parse_errors") or inventory.get("json_contracts", {}).get("json_parse_errors"):
        return "FAIL_CLOSED"
    if inventory.get("test_collection", {}).get("status") == "NOT_OBTAINED":
        return "FAIL_CLOSED"
    if any(item.get("namespace") == "05_RUNTIME_STATE.json" and item.get("referencing_modules") for item in data_map.get("namespaces", [])):
        return "ARCHITECTURE_CONSOLIDATION_REQUIRED"
    if dependencies.get("sys_path_mutations") or dependencies.get("dual_import_fallbacks") or workflows.get("overlapping_main_write_namespaces"):
        return "ARCHITECTURE_CONSOLIDATION_REQUIRED"
    return "BOUNDED_DEBT_ONLY"


def audit_repository(root: Path, *, collect_tests: bool = False) -> dict[str, Any]:
    root = root.resolve()
    tracked = _tracked_files(root)
    script_paths = _scope_files(root, tracked, "scripts", {".py"})
    test_paths = _scope_files(root, tracked, "tests", {".py"})
    workflow_paths = _scope_files(root, tracked, ".github/workflows", {".yml", ".yaml"})
    action_paths = _scope_files(root, tracked, ".github/actions", {".yml", ".yaml"})
    schema_paths = _scope_files(root, tracked, "schemas")
    config_paths = _scope_files(root, tracked, "config")
    python_rows, graph, aliases, parse_errors, records = _parse_python_modules(root, [*script_paths, *test_paths])
    dependencies = _dependency_summary(python_rows, graph, records, aliases, parse_errors)
    workflows = _workflow_map(root, [*workflow_paths, *action_paths])
    data_map = _data_write_read_map(python_rows, tracked, workflows)
    json_contracts = _json_contract_inventory(root, [*schema_paths, *config_paths])
    collection = _test_collection_evidence(root) if collect_tests else {"command": "python -m pytest --collect-only -q", "status": "NOT_RUN_BY_SCANNER"}
    inventory = {
        "contract_version": CONTRACT_VERSION,
        "scope": {
            "python_roots": ["scripts/**/*.py", "tests/**/*.py"],
            "workflow_roots": [".github/workflows/**", ".github/actions/**"],
            "schema_root": "schemas/**",
            "config_root": "config/**",
            "data_scan_policy": "paths_only_no_data_contents",
            "audit_tool_exclusions": sorted(AUDIT_TOOL_PATHS),
        },
        "script_file_count": len(script_paths),
        "test_file_count": len(test_paths),
        "workflow_file_count": len(workflow_paths),
        "action_file_count": len(action_paths),
        "schema_file_count": len(schema_paths),
        "config_file_count": len(config_paths),
        "module_count": len(python_rows),
        "python_parse_errors": parse_errors,
        "json_contracts": json_contracts,
        "data_scan_policy": "paths_only_no_data_contents",
        "test_collection": collection,
        "shared_semantic_primitives": _semantic_primitive_inventory(python_rows),
        "modules": python_rows,
    }
    decision = _decision(inventory, dependencies, data_map, workflows)
    inventory["decision"] = decision if decision in ALLOWED_DECISIONS else "FAIL_CLOSED"
    return {
        "decision": inventory["decision"],
        "architecture_inventory": inventory,
        "dependency_summary": dependencies,
        "data_write_read_map": data_map,
        "workflow_map": workflows,
    }


def _markdown_table(rows: Sequence[Mapping[str, str]]) -> str:
    lines = ["| Domain | Current owner(s) | Callers / boundary | Proven duplication or collision | Ownership status |", "| --- | --- | --- | --- | --- |"]
    for row in rows:
        lines.append("| {domain} | {owners} | {callers} | {collision} | {clarity} |".format(**row))
    return "\n".join(lines)


def render_domain_owner_map(result: Mapping[str, Any]) -> str:
    inventory = result["architecture_inventory"]
    dependencies = result["dependency_summary"]
    workflows = result["workflow_map"]
    return "\n".join(
        [
            "# FBOS whole-code domain ownership map — Issue #268 R1",
            "",
            "This is a read-only audit of the exact repository head used for this PR. It records current owners and evidenced collisions; it does not authorize refactors or data changes.",
            "",
            f"- Decision: `{result['decision']}`",
            f"- Python modules inventoried: `{inventory['module_count']}`; scripts: `{inventory['script_file_count']}`; tests: `{inventory['test_file_count']}`.",
            f"- JSON schema/config files parsed: `{inventory['json_contracts']['json_file_count']}`; parse errors: `{len(inventory['json_contracts']['json_parse_errors'])}`.",
            f"- Local import edges: `{dependencies['local_edge_count']}`; cycles: `{len(dependencies['cycles'])}`; sys.path mutations: `{len(dependencies['sys_path_mutations'])}`; dual import fallbacks: `{len(dependencies['dual_import_fallbacks'])}`.",
            f"- Workflows/actions classified: `{workflows['workflow_count']}`; overlapping main-write namespaces: `{len(workflows['overlapping_main_write_namespaces'])}`.",
            "- Data policy: tracked data paths were counted for namespace ownership only; historical data contents were not parsed or hashed.",
            "",
            _markdown_table(DOMAIN_ROWS),
            "",
            "## Healthy comparison controls",
            "",
            "The accepted owner map and architecture guards establish healthy control zones for `scripts/market_engine.py`, `scripts/score_engine.py`, `scripts/market_contracts.py`, `scripts/evaluation_kernel.py`, `scripts/exact_distribution.py`, Market-Side generated-state ownership, and `scripts/football_data/providers/base.py` plus adapters. Their compatibility re-exports are recorded as intentional boundaries, not duplicate math.",
            "",
            "## Scope boundary",
            "",
            "PR #267 remains held and unmerged. This audit does not inspect it as a change set, repair its identity behavior, change identity mappings, modify model/Champion/Serving/UI, alter production workflows, migrate data, or change dependencies.",
            "",
        ]
    )


def render_report(result: Mapping[str, Any]) -> str:
    inventory = result["architecture_inventory"]
    dependencies = result["dependency_summary"]
    data_map = result["data_write_read_map"]
    workflows = result["workflow_map"]
    collection = inventory["test_collection"]
    finding_lines: list[str] = []
    for finding in FINDING_TEMPLATES:
        finding_lines.extend(
            [
                f"### {finding['id']} — {finding['title']}",
                f"- Evidence: {finding['evidence']}",
                f"- Actual current consequence: {finding['consequence']}",
                f"- Future maintenance/regression consequence: {finding['future_cost']}",
                f"- Smallest candidate consolidation boundary (not authorized): {finding['boundary']}",
                "",
            ]
        )
    return "\n".join(
        [
            "# FBOS whole-code architecture, ownership and maintenance audit — Issue #268 R1",
            "",
            f"## Decision: `{result['decision']}`",
            "",
            "`ARCHITECTURE_CONSOLIDATION_REQUIRED` is an audit conclusion about future maintenance/regression cost. It is not authorization to refactor, delete, rename, migrate, change provider/model/UI/Serving behavior, or open a follow-up Issue.",
            "",
            "## Scope and method",
            "",
            "- Exact code/config surface: `scripts/**/*.py`, `tests/**/*.py`, `.github/workflows/**`, `.github/actions/**`, `schemas/**`, and `config/**`.",
            "- AST inventory: LOC, functions/classes, imports, local dependency edges, cycles, sys.path mutation, direct/package fallback, responsibility tags, data access signals and module roles.",
            "- Workflow inventory: triggers, permissions, git write commands, namespaces written, concurrency declaration and classification for every workflow/action.",
            "- Data policy: `data/**` was enumerated by tracked path for namespace counts and ownership references only. No historical data file contents were bulk-read, parsed or hashed.",
            "",
            "## Mechanical evidence",
            "",
            f"- Python modules: `{inventory['module_count']}`; parse errors: `{len(inventory['python_parse_errors'])}`.",
            f"- JSON schema/config files: `{inventory['json_contracts']['json_file_count']}`; parse errors: `{len(inventory['json_contracts']['json_parse_errors'])}`.",
            f"- Local dependency edges: `{dependencies['local_edge_count']}`; cycles: `{len(dependencies['cycles'])}`.",
            f"- sys.path mutations: `{len(dependencies['sys_path_mutations'])}`; direct/package fallback sites: `{len(dependencies['dual_import_fallbacks'])}`; cross-layer local edges: `{len(dependencies['cross_layer_edges'])}`.",
            f"- Tracked data files counted by catalog: `{data_map['tracked_data_file_count']}`; namespace rows: `{len(data_map['namespaces'])}`.",
            f"- Workflows/actions: `{workflows['workflow_count']}`; main-write overlap rows: `{len(workflows['overlapping_main_write_namespaces'])}`.",
            "",
            "## Test-system evidence",
            "",
            f"- Command: `{collection.get('command')}`",
            f"- Status: `{collection.get('status')}`",
            f"- Collected before failure: `{collection.get('collected_tests_before_failure')}`",
            f"- Error files: `{', '.join(collection.get('error_files', [])) or 'none recorded'}`",
            f"- Import errors: `{'; '.join(collection.get('import_errors', [])) or 'none recorded'}`",
            "- Per Issue #268, collection failure is recorded as baseline evidence and was not patched. Existing architecture/ownership and bounded characterization tests were run separately.",
            "",
            "## Ranked findings",
            "",
            *finding_lines,
            "## Candidate consolidation sequence — hypothesis only",
            "",
            "1. Characterize and lock timestamp/naive-time semantics at current consumer boundaries.",
            "2. Characterize deterministic identity precedence versus presentation-only compatibility joins, without changing alias/mapping truth.",
            "3. Establish root runtime versus product runtime reachability and write ownership before any migration.",
            "4. Separate provider transport/parsing from orchestration only through behavior-preserving owner contracts.",
            "5. Restore global collection, then extend architecture guards to the uncovered identity/time/runtime/projection boundaries.",
            "",
            "Each item is a candidate boundary derived from this audit, not an implementation instruction. Independent acceptance and a separately authorized Issue are required before any slice.",
            "",
            "## Explicit non-actions",
            "",
            "- No production source/provider/model/Champion/Serving/UI behavior changed.",
            "- No identity alias or mapping changed; PR #267 was not repaired.",
            "- No workflow behavior, runtime data, frozen/history/prospective truth, or dependency changed.",
            "- No raw data/page content was added to the artifacts.",
            "",
        ]
    )


def write_audit_outputs(root: Path, output_dir: Path | None = None, *, collect_tests: bool = False) -> dict[str, Any]:
    root = root.resolve()
    result = audit_repository(root, collect_tests=collect_tests)
    destination = (output_dir or root / AUDIT_OUTPUT_RELATIVE).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    files = {
        "architecture_inventory.json": result["architecture_inventory"],
        "data_write_read_map.json": result["data_write_read_map"],
        "workflow_map.json": result["workflow_map"],
        "dependency_summary.json": result["dependency_summary"],
    }
    for filename, payload in files.items():
        (destination / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (destination / "domain_owner_map.md").write_text(render_domain_owner_map(result), encoding="utf-8")
    (destination / "report.md").write_text(render_report(result), encoding="utf-8")
    result["output_dir"] = destination.as_posix()
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-dir", default=str(AUDIT_OUTPUT_RELATIVE))
    parser.add_argument("--collect-tests", action="store_true")
    args = parser.parse_args(argv)
    result = write_audit_outputs(Path(args.repo_root), Path(args.output_dir), collect_tests=args.collect_tests)
    print(json.dumps({"decision": result["decision"], "output_dir": result["output_dir"], "module_count": result["architecture_inventory"]["module_count"], "workflow_count": result["workflow_map"]["workflow_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
