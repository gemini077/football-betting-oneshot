# Phase 2A Implementation Plan: Football Data Foundation

## Scope

建立只读、可追溯、provider-specific 的足球数据基础层。Raw Evidence 先保留来源语义，再进入 Normalized Football Data；Validated Features 只建立合同和质量门，不被当前 Champion 读取。正式 Champion、Phase 1 benchmark、前台页面和现有 match identity 语义均不改。

`grill-me unavailable in current Codex environment`。OSS discovery 使用 agent-reach skill 的路由；本机 `agent-reach doctor --json` 命令不可执行，因此使用已认证的 `gh` read-only API 和官方文档作为 fallback，并在 discovery 文档中记录。

## Architecture Decisions

- 使用标准库 dataclass/validation，不新增依赖；JSON Schema 作为跨语言合同，Python 合同层负责可执行的结构和语义校验。
- 新数据层独立放在 `scripts/football_data/`、`schemas/football_data/`、`data/football_data/`，不接入 `scripts/automatic_model_core.py`。
- 复用现有 `canonical_match_id`、`provider_match_crosswalk` 和既有 `data/team_aliases.json` 的审计结论；新 resolver 不重写 match identity，也不改变 Champion 使用的旧 helper。
- Entity resolution 只允许 provider ID、现有 crosswalk、已登记 alias 或明确上下文的唯一映射；危险短名和模糊相似度始终返回 `unresolved`。
- 第一批最多两个 adapter：现有 Nowscore/500 snapshot normalizer，以及离线 StatsBomb Open Data research adapter。二者都不产生正式 benchmark record。
- xG 只保存 provider-specific observation 和定义元数据，不做跨 provider 平均或校准；opponent adjustment 只保留合同字段，v1 的 adjusted value 为 `null`。
- storage 采用 content-addressed/immutable-friendly JSON 和 registry JSON；DuckDB/Parquet 只写 decision memo，不引入数据库迁移。

## Ordered Tasks

### Task 1: OSS discovery and current capability audit

**Allowed reads:** `scripts/`, `schemas/`, `data/provider_match_crosswalk.json`, `data/model_benchmarks/`, related governance tests, official OSS repositories/docs.

**Allowed writes:** `docs/data-foundation/OPEN_SOURCE_DISCOVERY.md`, `docs/data-foundation/CURRENT_CAPABILITY_AUDIT.md`, `docs/data-foundation/DATA_COVERAGE_MATRIX.md`, `tasks/plan.md`, `tasks/todo.md`.

**Acceptance criteria:**

- [ ] Five named projects plus entity-resolution, Elo, lineup/injury, event-schema, open-results, and analytical-storage candidates are recorded.
- [ ] Every decision is one of `ADOPT`, `ADAPT`, `REFERENCE`, `REJECT`, `DEFER` with license/ToS/maintenance/provenance/coverage reasoning.
- [ ] Existing Nowscore/500/ESPN fields are classified as raw, normalized, narrative-only, or deterministic Champion input.

**Verification:** review the three documents against the requested matrix and source links.

### Task 2: Contract-first normalized data layer

**Allowed writes:** `schemas/football_data/`, `scripts/football_data/contracts.py`, `data/football_data/` registry/config samples, `tests/test_football_data_contracts.py`.

**Acceptance criteria:**

- [ ] Versioned v1 contracts cover team, competition, season, match, strength, form, xG, lineup, availability, and provenance.
- [ ] Common source/entity/timestamp/sample/value/quality/freshness/provenance fields are represented.
- [ ] Tests reject missing provenance, invalid statuses/grades, and provider-mixed xG records.

**Verification:** focused contract test passes with offline fixtures only.

### Task 3: Safe entity resolution

**Allowed writes:** `scripts/football_data/entity_resolution.py`, `data/football_data/team_alias_registry.json`, `tests/test_team_entity_resolution.py`.

**Acceptance criteria:**

- [ ] Canonical team/competition/season IDs and provider mappings are explicit.
- [ ] Manchester United, Inter, and PSG aliases resolve only through registered evidence.
- [ ] Same-name countries, youth/women/B/reserve teams, and dangerous words remain distinct or unresolved.

**Verification:** resolution tests cover exact IDs, aliases, context mismatch, conflict, and unresolved cases.

### Task 4: Quality, freshness, provenance, and two adapters

**Allowed writes:** `scripts/football_data/quality.py`, `scripts/football_data/providers/`, `config/football_data_quality.json`, `tests/test_football_data_quality.py`, `tests/test_statsbomb_open_adapter.py`, offline StatsBomb fixtures.

**Acceptance criteria:**

- [ ] A/B/C/D data-layer grades and fresh/stale/unknown freshness are config-driven.
- [ ] Nowscore/500 normalizer preserves actual goals/form and leaves unsupported xG/availability unknown.
- [ ] StatsBomb adapter parses offline match/event/lineup JSON and preserves provider xG definition and license/attribution metadata.

**Verification:** focused quality and adapter tests; no network calls.

### Task 5: Feature registry, Champion isolation, review, and handoff

**Allowed writes:** `config/football_feature_registry.json`, `tests/test_champion_data_foundation_isolation.py`, handoff artifact, and final PR metadata.

**Acceptance criteria:**

- [ ] Every new feature has `validated_for_model=false`.
- [ ] Mutating the new registry, StatsBomb fixture, and normalized xG snapshot leaves Champion math digest, source fingerprint, and prediction identity unchanged.
- [ ] Required focused tests, governance/integration tests, full suite, and `git diff --check` pass.
- [ ] Champion core SHA remains `064f9fa96e2995a66966c916dd9e9f600358b6c49b3ad9aa1efe9704cbdd1f15`; fixed digest remains `b104c0f81c2a5c457967d9047b41e389209b99bd3cfc1613d9fb13fb0c2175df`.

**Verification:** five-axis review, clean Git status, commit `feat(data): establish football data foundation`, Draft PR, and ZIP contents/hash inspection.

## Checkpoints

- **Discovery checkpoint:** OSS matrix, capability audit, coverage matrix reviewed before code.
- **Contract checkpoint:** contract/identity/quality focused tests green before adapter work.
- **Isolation checkpoint:** Champion and Phase 1 tests green before packaging.
- **Closeout checkpoint:** no frontend/model-core/benchmark-definition changes; handoff contains only scoped artifacts.

## Known Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Scraper ToS or upstream HTML changes | Keep soccerdata as reference only; adapters own an explicit provider boundary. |
| Team over-merge | No automatic fuzzy confirmation; unresolved is a valid result. |
| xG definition drift | Store provider, metric definition, penalty/post-shot semantics, and model-version metadata separately. |
| Freshness misuse | TTLs are data-layer policy only and never feed Champion. |
| Scope creep into model/data migration | New files stay outside deterministic core and benchmark paths; no database migration. |
