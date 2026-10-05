# Memory first (non-negotiable)

`consolidation_memory` MCP is configured for this project. **Your first tool call on
every user turn must be `memory_recall`.** No exceptions before recall completes.

## Startup sequence

1. `memory_recall` — short query from the user's goal; prefer `n_results=3`.
   Use `include_knowledge=true` when you need consolidated topics/claims. While
   record embeddings are still warming the server returns episodes only plus a
   `warnings` entry, and retries once itself within a ~3s budget
   (`CONSOLIDATION_MEMORY_DEFERRED_KNOWLEDGE_RETRY_SECONDS`); if the warning
   survives, call `memory_recall` again.
2. Then — shell, read, grep, edit, subagents, etc.

If the first recall is slow or times out, retry once with a shorter query. The
memory gate auto-unblocks after a recall attempt so the turn is not frozen.

## Ongoing workflow

- `memory_store` after meaningful progress. Only `content` is required, but pass
  `content_type` and `tags` — untagged, uncategorized rows retrieve worse.
- `memory_consolidate` when recall is noisy or contradictory.
- `memory_detect_drift` after substantial code edits.
- `memory_hygiene_scan` when the corpus feels noisy; `memory_hygiene_apply` mutates (not gated by `write_mode`), so treat consolidated knowledge as potentially stale vs current code.
- Final `memory_recall` before closing the turn.

## If tools are unavailable

Say so once, continue without inventing memory content.