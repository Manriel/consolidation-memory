# consolidation-memory (Grok project rules)

## Memory first

See [00-memory-first.md](00-memory-first.md). `memory_recall` is the mandatory first
tool on every user turn when `consolidation_memory` MCP is available.

Read [CONTRIBUTING.md](../../CONTRIBUTING.md) and [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) before code changes.

## Fresh working copy

After `memory_recall`, run `python scripts/sync_working_copy.py` as the first shell step
when the tree is clean. It fetches and rebases onto `origin/<branch>`. If the tree is
dirty, report it and ask whether to commit, stash (`--stash`), or continue on the
current base. Re-run sync before pushing or after long idle gaps.

## Workflow

- Preserve trust invariants (temporal correctness, provenance, contradictions, drift auditability, scope isolation, surface parity).
- One focused slice per session; run targeted `pytest` + `ruff check src tests scripts` before done.
- Update user-facing docs when behavior changes.
- Read the **Debt ledger** in [CLAUDE.md](../../CLAUDE.md) before large refactors.

## Invariants that are easy to break

- Full MCP profile = **29 tools**; simple profile = `memory_recall`, `memory_remember`, `memory_ask`.
- Unknown tool arguments are rejected everywhere: MCP, REST (HTTP 422) and OpenAI dispatch share one allowed-argument set. Nested `EpisodeInput` / `OutcomeAnchorInput` values (`episodes`, `code_anchors`) stay permissive by design.
- Hygiene: `memory_hygiene_scan` / `memory_hygiene_apply` are global-by-design and not gated by `write_mode`; `forget()` expires orphan claims. `memory_hygiene_apply` reports `status` `dry_run` or `applied` — never `ok` — and always returns `episode_ids`, `forgotten` and `not_found` (0 on a dry run).
- `memory_scope_list` is a deployment-topology audit: counts are live rows only and the result is **not** filtered by `read_visibility`.
- Consolidated knowledge can lag code — use `memory_correct` or superseding episodes + consolidate.
- New tools: ship on MCP + REST + OpenAI dispatch + tests; document scope-aware vs global in CONTRIBUTING.

## Mantra

Deterministic belief maintenance first; LLMs only for unstructured residue; tests prove trust.