# consolidation-memory contributor context

Compact maintainer guide aligned with the codebase.

## Repository shape

```text
src/consolidation_memory/
  client.py          orchestration + tool-facing operations
  database.py        backward-compatible facade (re-exports db/)
  db/                SQLite schema/migrations + domain CRUD
  db/scope.py        scope resolution, exact-match filters, scope discovery
  query_service.py   canonical query envelopes
  context_assembler.py  hybrid recall
  claim_graph.py     deterministic claim canonicalization
  drift.py           git-based drift challenge flow
  consolidation/       engine, fast_path, prompting
  schemas.py         OpenAI tools + MCP dispatch
  tool_contracts.py  typed MCP output contracts (published outputSchema)
  tool_dispatch.py   canonical dispatch seam; one allowed-argument set
  mcp_compat.py      ONLY file touching private `mcp` SDK surfaces
```

## Important facts

- Package version: `pyproject.toml`
- Schema version: `database.py` (`CURRENT_SCHEMA_VERSION`)
- Tool schemas: `schemas.py` (`openai_tools` is a module-level list, `dispatch_tool_call`); MCP output contracts: `tool_contracts.py` — a handler's return annotation is the published `outputSchema`, validated strictly at runtime with `extra="allow"` so new payload keys survive. 29 tools, 104 published parameters; 28 contracts, since `memory_store` and `memory_remember` share `StoreOutput` (`memory_store_batch` has its own `BatchStoreOutput`).
- MCP SDK: supported range `mcp[cli]>=2.3.0,<3` (`FastMCP` was renamed `MCPServer` in mcp 2.x). Every private SDK touch is isolated in `mcp_compat.py` (`ArgModelBase`, `MCPServer._tool_manager`, `ToolManager._tools`, `fn_metadata.output_schema`, the `Tool.__dict__["output_schema"]` fallback) — **an `mcp` bump breaks there first**, and a missing module/attribute raises `MCPCompatError` naming the installed version, the range and what was probed. The repo pins no protocol version: the host proposes, `mcp` negotiates, handshake set `2024-11-05`…`2025-11-25` (`2026-07-28` is modern-envelope only, so requesting it downgrades to `2025-11-25`).
- Output schema publication: `anyOf[success, error]` under a root `type` (pre-2026 protocol validators require it). It is **self-healing** — `mcp_compat.install_list_tools_heal` wraps the public `MCPServer.list_tools` (`tools/list` funnel) and evicts the SDK's cached `Tool.output_schema`, so a late-registered tool is healed on the next listing. `server._verify_published_output_schemas()` runs at import and in `lifespan` and fails loudly on a success-only schema.
- MCP error model: tool execution failures return `isError: true` via `_tool_error_result` (actionable text + `{"error": ...}` structured payload).
- Input contract: unknown arguments are rejected on all three surfaces from **one** allowed-argument set — `tool_dispatch.accepted_argument_names` derived from the published `inputSchema` (`reject_unknown_arguments` runs first in `execute_tool_call`), pydantic `extra="forbid"` on the MCP argument model, and `rest.StrictRequestModel` (`extra="forbid"` → HTTP 422) on every top-level request body. `server._verify_published_argument_contract()` cross-checks the SDK set against the dispatch set at import and in `lifespan`. Nested `EpisodeInput`/`OutcomeAnchorInput` stay permissive on purpose (published as plain objects); REST query params are not covered.
- Generated docs: `docs/TOOLS.md` comes from `scripts/generate_tool_reference.py`; `tests/test_tool_reference_sync.py` fails when it drifts

## Local verification

```bash
pip install -e ".[all,dev]"
python scripts/smoke_builder_base.py   # builder smoke: ok
pytest tests/ -q                       # 1477 passed, 5 skipped
python scripts/smoke_mcp_stdio.py      # smoke_mcp_stdio PASS: 8/8 checks
ruff check src tests/ scripts/         # All checks passed!
mypy src/consolidation_memory/         # Success: no issues found in 84 source files
python scripts/generate_tool_reference.py --check   # docs/TOOLS.md is up to date
```

Observed at HEAD of this branch (2026-10-05). CI runs the same set, with two
differences: `ruff` is `src/ tests/` only (scripts are clean and worth checking
locally, but the job does not gate them), and the wire smoke runs on 3.13/ubuntu.

## Lint and typing facts

- `[tool.ruff.lint]` writes the enforced `select` out in full; there is no `ignore` and no `per-file-ignores`. Every suppression is a `# noqa` on its own line, carrying its reason. Bandit stays the security gate (`bandit -q -ll -r src scripts -s B608,B110`).
- `ruff>=0.7.0,<0.17` is pinned with an upper bound on purpose: the rule set is explicit, but a major bump can still add rules.
- BLE001 is **not** selected (nine legitimate `except Exception` sites remain in `tests/`). Do not claim BLE001 is enforced. TRY004 **is** enforced per site, not project-wide; REST maps `(TypeError, ValueError)` to 422, and the 400 handlers catch `RuntimeError`.
- `mcp.*` is **not** in `[tool.mypy.overrides] ignore_missing_imports` any more: the SDK ships `py.typed` and the type checker sees the real signatures. Only genuinely untyped distributions are listed.

## Guardrails

1. Keep semantics aligned across Python, MCP, REST, and OpenAI surfaces.
2. Preserve trust invariants (see [CONTRIBUTING.md](CONTRIBUTING.md)).
3. Update user-facing docs when behavior changes.
4. Avoid hard-coded test counts or stale timeline statements in docs.
5. Changed a tool signature or output contract? Run `scripts/generate_tool_reference.py` and commit `docs/TOOLS.md`.
6. Changed the allowed-argument set? One derivation (`schemas.openai_tools`) feeds the dispatch guard, the REST models and the SDK check — do not fork a second list.

## Known architectural debt (audit 2026-06-15)

Prioritized blind spots — check this before large refactors; update when fixed.

**P0 (trust / scope)** — addressed 2026-06-13
- ~~Scope on audit APIs~~: `contradictions`, `decay_report`, `consolidation_log`, `status` use resolved default scope; explicit `scope` narrows further; `global_scope=True` for corpus-wide ops view.
- ~~`content_type` validation~~: shared `validate_episode_content_type()` in `types.py`.
- ~~`trust_profile` in scoped `status()`~~: `get_claim_trust_stats`, `count_active_challenged_claims`, `get_recently_contradicted_topic_ids` accept `scope`.

**P1 (enforcement / ops)** — addressed 2026-06-15
- ~~`coding_agent_eval` CI gate~~: `quick` mode in `novelty_gates` job. `real_world_eval` remains manual (live corpus).
- ~~`embedding_disk_cache` cross-process lock~~: `.embedding_cache_write.lock` via `process_write_lock.py`.
- ~~`SECURITY.md` + MCP trust boundary~~: stdio trust model documented; supported line is tracked in SECURITY.md (moves with each minor).
- ~~Hygiene surface parity~~: `memory_hygiene_scan` / `memory_hygiene_apply` on MCP, REST, OpenAI dispatch, CLI, web UI, desktop.
- ~~`rest.py` E402~~: imports ordered above type aliases.
- ~~`tool_adapter` recall parity~~: shared deferred-knowledge + deadline semantics across MCP/REST/OpenAI.

**P2 (structure / tests / adoption)** — addressed 2026-06-15
- ~~`ContentType` vs `RecordType`~~: `procedure` ingest type added; `strategy` remains JSON-only at store time (see CONTRIBUTING + FAST_PATH_EPISODES).
- ~~Global-by-design tools~~: documented in CONTRIBUTING (scope-aware vs global contract); hygiene + policy admin listed.
- ~~Migration regression v17–v20~~: additive tests in `tests/test_core.py`.
- ~~Multi-process lock test~~: `tests/test_process_write_lock.py` for `ProcessWriteLease`.
- ~~`database.py` god-module~~: split into `db/` domain modules (2026-06-13); `database.py` remains a thin re-export facade.
- ~~Positioning vs RAG~~: `examples/trust-vs-rag/` with `demo_flow.py`.
- ~~Plugin author guide~~: `docs/PLUGIN_DEVELOPMENT.md`.
- ~~LoCoMo narrative~~: `docs/LOCOMO_BENCHMARK.md` (full run needs API key).

**Fixed (audit-fix pass 2026-10-05)** — was real, now closed
- ~~`memory_hygiene_apply` contract~~: the applied branch omitted `episode_ids` (validation failed *after* the episodes were deleted) and reported `status: "ok"`. `types.HygieneApplyResult` and `HygieneApplyOutput` now mirror each other under an import-time guard, and both modes emit the same key set.
- ~~`memory_scope_list` merge + liveness~~: grouping uses the 11 canonical scope keys, counts are `deleted = 0` live rows, display metadata is picked with `MAX()`, `namespace.display_name` is gone, and the read path no longer runs `ensure_schema()`.
- ~~Unknown-argument enforcement~~: REST and OpenAI dispatch used to drop extras silently while the schema promised `additionalProperties: false`. One shared set now feeds all three surfaces.
- ~~`mcp` private surfaces~~: isolated in `mcp_compat.py`; `outputSchema` publication is self-healing and a startup self-check enforces both arms.
- ~~Drift subprocess interpreter~~: `.resolve()` no longer collapses a venv symlink to the base interpreter; `PYTHONPATH` is forwarded with the package root first.
- ~~Lint/typing config~~: explicit `select`, no `ignore`/`per-file-ignores`, 23 `scripts/` violations fixed rather than ignored, `mcp` removed from mypy's `ignore_missing_imports`.

**Open (audit-fix pass 2026-10-05)** — newly known, ranked
- **P0 `memory_scope_list` visibility wording**: the tool is intentionally *not* filtered by `read_visibility`, but the published `schemas.py` description and `docs/TOOLS.md` do not say so. `SECURITY.md` and `docs/ROADMAP.md` now do; `MCP_GUIDE.md` and the schema description still owe a cross-reference to the `docs/ACL.md` trust boundary.
- **P1 Unvalidated contract subtrees**: 32 of 182 success-arm properties (17.6%) are still `dict[str, Any]` / `list[dict[str, Any]]`, so their subtrees are not validated. `tests/test_output_contract_payload_typing.py` ratchets the number; do not raise it.
- **P1 Changelog ranking rule**: `changelog_builder` now ranks before capping (`DEFAULT_SUBJECT_LIMIT = 200`), so user-visible commits are never displaced by `docs`/`chore`. Two consequences to remember: `--limit` exists on `update_changelog.py` and `release.py`, and dependency-scope commits get their own `### Dependencies` section instead of `Internal`.
- **P2 `mcp` private-surface blast radius**: `mcp_compat.py` concentrates five private probes, but the supported range is `<3`, so the next major is a known break. Watch for it in dependabot; the import-time self-checks fail loudly, they do not degrade.
- **P2 `docs/MCP_GUIDE.md` drift**: `CLIENT_INIT_TIMEOUT_SECONDS` is 30s in `server.py`, `STATUS_LIGHTWEIGHT` defaults to `True`, `CONSOLIDATION_AUTO_RUN` is a config field (env `CONSOLIDATION_MEMORY_CONSOLIDATION_AUTO_RUN`), and the guide still advertises protocol `2026-07-28` and `namespace.display_name` (removed from the output).

**Maintainer reminders (not debt)**
- Full MCP profile ships **29 tools**; simple profile exposes 3 (`memory_recall`, `memory_remember`, `memory_ask`).
- `forget()` still expires claims that lose all provenance (`expire_claims_without_sources`), so a forgotten episode leaves no claim behind; consolidated knowledge can lag code — use `memory_correct` or new episodes + consolidate.
- `memory_hygiene_apply` is not gated by `write_mode`. Read its payload as `status: "applied"` (never `ok`) and expect `episode_ids`/`forgotten`/`not_found` in both modes — an earlier `"ok"` was a published-contract contradiction.
- `memory_scope_list` counts live rows only (`deleted = 0` on `episodes`/`knowledge_records`; `knowledge_topics` has no such column) and is not read-filtered — see `SECURITY.md`.
- Run `memory_hygiene_scan` on noisy corpora; verify with `ruff check src tests/ scripts/`, `mypy src/consolidation_memory/`, `pytest tests/ -q`, `python scripts/smoke_mcp_stdio.py`.

**Runtime residual (P0-1, mitigated 2026-07-10)**
- **Windows SciPy import hang on MCP workers**: mitigated by lazy `consolidation` package export, lightweight `status` import isolation, main-thread SciPy preload, and bounded MCP tool timeouts. Residual: first consolidate still requires SciPy — preload on main thread / `_ensure_scipy_for_consolidate()` before worker. Regression: `tests/test_import_isolation.py`, `scripts/smoke_mcp_stdio.py`.

**Keep (do not rewrite)**
- Episodes → records → claims → topics stack; `tool_dispatch` seam; FAISS write lease; fast-path before LLM; `query_service` envelopes.

## Core docs

- [README.md](README.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/MCP_GUIDE.md](docs/MCP_GUIDE.md) — wire contract, scopes, errors, environment, recipes
- [docs/TOOLS.md](docs/TOOLS.md) — generated input/output schemas for every tool
- [docs/ACL.md](docs/ACL.md) — policies, principals, multi-service scope pattern
- [docs/UI.md](docs/UI.md) — browser UI, TUI dashboard, desktop app
- [docs/FAST_PATH_EPISODES.md](docs/FAST_PATH_EPISODES.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)