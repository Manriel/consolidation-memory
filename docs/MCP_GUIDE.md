# MCP guide

The consolidation-memory MCP server exposes the memory engine to any MCP host:
agents get typed tools, discoverable schemas, structured results and a scope
system for safe sharing. This guide covers everything the README's quick-start
does not: the wire contract, scopes and policies, the error model, every
environment variable, and end-to-end recipes.

- **Full tool reference** (all29 tools, generated from the published schemas):
  [TOOLS.md](TOOLS.md)
- **Quick start / host config**: [README — Connect your agent](../README.md#connect-your-agent-mcp)

## Capabilities at a glance

| Area | What the server gives you |
| --- | --- |
| Tools |29 tools (full profile): store/recall/search, claims graph, outcomes, consolidation, drift detection, hygiene, policies, scope discovery |
| Profiles | `full` (everything) or `simple` (3 conversational tools) via `CONSOLIDATION_MEMORY_MCP_TOOL_PROFILE` |
| Protocol | MCP up to spec **2026-07-28**; negotiates with older hosts down to `2024-11-05` |
| Results | Typed `outputSchema` per tool, `structuredContent` object + UTF-8 JSON text, strict input validation |
| Scopes | Envelope-based isolation (namespace / app / agent / session / project) with discovery and access policies |
| Reliability | Per-tool timeouts, recall and drift fallback chains, `isError` failures with actionable text |
| Surfaces | Same dispatch and semantics behind MCP, REST, Python SDK and OpenAI-compatible schemas |

## Connect

Use an **absolute Python path** — more reliable than a console script,
especially on Windows:

```json
{
  "mcpServers": {
    "consolidation_memory": {
      "command": "/absolute/path/to/python",
      "args": ["-m", "consolidation_memory", "--project", "default", "serve"],
      "env": {
        "PYTHONUNBUFFERED": "1",
        "CONSOLIDATION_MEMORY_IDLE_TIMEOUT_SECONDS": "900",
        "CONSOLIDATION_MEMORY_STATUS_LIGHTWEIGHT": "1",
        "CONSOLIDATION_MEMORY_MCP_AUTO_CONSOLIDATE": "0",
        "CONSOLIDATION_MEMORY_PRELOAD_SCIPY_ON_START": "1",
        "CONSOLIDATION_MEMORY_DEFERRED_KNOWLEDGE_RETRY_SECONDS": "0"
      }
    }
  }
}
```

`consolidation-memory init` prints the full recommended environment.

Drop-in host configs: [Cursor](../examples/cursor-integration/README.md) ·
[Continue](../examples/continue-dev/README.md)

### Profiles

| Profile | Tools | When |
| --- | --- | --- |
| `full` (default) | all29 | Local agent with the whole memory toolkit |
| `simple` | `memory_recall`, `memory_remember`, `memory_ask` | Small context budget, chat-style memory only |

Select with `"CONSOLIDATION_MEMORY_MCP_TOOL_PROFILE": "simple"`.

## Protocol compatibility

The server negotiates the highest protocol version the host offers:

| Version | Role |
| --- | --- |
| `2026-07-28` | Modern current spec: structured results with `resultType`, tool output schemas, caching metadata |
| `2025-11-25` | Previous spec revision, still fully supported |
| `2025-06-18`, `2025-03-26`, `2024-11-05` | Handshake-era versions for older hosts |

Nothing host-side is required to benefit from structured results: every
version receives `content` text, and hosts that understand `structuredContent`
and `outputSchema` get the typed channel as well.

## Result contract

Every tool call returns three synchronized pieces:

1. **`content`** — a single text block with the payload serialized as JSON.
   UTF-8 end to end: non-ASCII text is literal, never `\uXXXX`-escaped, and the
   text is byte-identical to what a write→read round trip stored.
2. **`structuredContent`** — the same payload as a JSON object, for
   applications that consume data rather than text.
3. **`outputSchema`** (published in `tools/list`) — a JSON Schema shaped as
   `anyOf[success, error]`: the success arm describes every field of the
   payload, the error arm is `{"error": "..."}`. Clients **should** validate
   `structuredContent` against it; the server validates every successful
   result against the success arm before it leaves the process.

Unknown input arguments are **rejected** (`additionalProperties: false` on
every `inputSchema`) instead of being silently dropped.

### Example — success

`tools/call` → `memory_search` with `{"query": "deploy", "limit": 5}`:

```json
{
  "content": [
    {
      "type": "text",
      "text": "{\n  \"episodes\": [\n    {\n      \"id\": \"259b0c75-...\",\n      \"content\": \"The deploy pipeline fails...\",\n      \"content_type\": \"exchange\",\n      \"tags\": [],\n      \"created_at\": \"2026-10-03T17:29:26+00:00\",\n      \"surprise_score\": 0.5,\n      \"access_count\": 0\n    }\n  ],\n  \"total_matches\": 1,\n  \"query\": \"deploy\",\n  \"message\": null\n}"
    }
  ],
  "structuredContent": {
    "episodes": [
      {
        "id": "259b0c75-...",
        "content": "The deploy pipeline fails...",
        "content_type": "exchange",
        "tags": [],
        "created_at": "2026-10-03T17:29:26+00:00",
        "surprise_score": 0.5,
        "access_count": 0
      }
    ],
    "total_matches": 1,
    "query": "deploy",
    "message": null
  },
  "isError": false
}
```

(The text block is the compact/indented serialization of exactly the
`structuredContent` object; line breaks above are shortened for readability.)

### Example — tool execution failure (timeout)

```json
{
  "content": [
    {
      "type": "text",
      "text": "memory_status timed out after 30s. Raise CONSOLIDATION_MEMORY_TIMEOUT_MEMORY_STATUS or CONSOLIDATION_MEMORY_TOOL_TIMEOUT_SECONDS."
    }
  ],
  "structuredContent": {
    "error": "memory_status timed out after 30s. Raise CONSOLIDATION_MEMORY_TIMEOUT_MEMORY_STATUS or CONSOLIDATION_MEMORY_TOOL_TIMEOUT_SECONDS."
  },
  "isError": true
}
```

The text is actionable on purpose: hosts pass it to the model so it can retry
with different parameters or raise the budget, per the MCP error-handling
model (tool execution errors are feedback, not protocol failures).

### Example — rejected input

`memory_status` called with an unknown argument:

```json
{
  "content": [
    {
      "type": "text",
      "text": "Error executing tool memory_status: 1 validation error for memory_statusArguments\njunk\n  Extra inputs are not permitted [type=extra_forbidden, input_value=1, input_type=int]"
    }
  ],
  "isError": true
}
```

### Guarantees

| Guarantee | Meaning |
| --- | --- |
| Nothing lost | Undeclared payload keys pass through (`additionalProperties: true` on outputs); text and structured channels carry the same data |
| Typed outputs | Every success payload validates against the published `outputSchema` success arm (strict types, required fields per the dispatcher's shapes) |
| Honest failures | Timeouts, validation errors and dispatch failures are `isError: true`, never a soft `{"error": ...}` success |
| Stable bytes | Stored text survives write→read round trips byte-for-byte; no Unicode re-encoding on the wire |

## Scopes and sharing

A **scope** is the identity envelope every row is stamped with. Reads
(recall, search, browse, claims, outcomes) are filtered by the resolved
scope; writes stamp the scope onto new rows. Without a scope argument the
legacy defaults apply: namespace `default`, app client
`legacy_client/python_sdk`, project from `CONSOLIDATION_MEMORY_PROJECT`.

### Envelope anatomy

| Section | Keys | Meaning |
| --- | --- | --- |
| `namespace` | `slug`, `sharing_mode`, `display_name` | Top-level sharing boundary (`private` / `shared` / `team` / `managed`) |
| `app_client` | `name`, `app_type`, `provider`, `external_key` | Calling application (`mcp`, `python_sdk`, `rest`, `cli`, ...) |
| `agent` | `name`, `external_key` | Logical agent inside the app (`null` when unused) |
| `session` | `external_key`, `session_kind` | Short-lived interaction context (`conversation`, `thread`, `workflow`, `job`) |
| `project` | `slug`, `display_name`, `root_uri`, `repo_remote`, `default_branch` | Repository/project identity |

`scope` accepts three shapes:

1. **Canonical object** — any subset of the sections above, e.g.
   `{"project": {"slug": "billing"}}`.
2. **String shorthand** — mapped to a project scope: values containing `/`,
   `\` or a URI prefix become `project.root_uri`, anything else becomes
   `project.slug` (so `"billing"` and `"/home/me/billing"` both work).
3. **`null`/omitted** — legacy defaults (see above).

### Discovering existing scopes

Scopes are not stored in a dedicated table — they live on the data rows, so
an external registry is not required. `memory_scope_list` aggregates what
exists:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "memory_scope_list",
    "arguments": { "limit": 50, "offset": 0 }
  }
}
```

```json
{
  "structuredContent": {
    "scopes": [
      {
        "scope": {
          "namespace": { "slug": "default", "sharing_mode": "private", "display_name": null },
          "app_client": { "name": "legacy_client", "app_type": "python_sdk", "provider": null, "external_key": null },
          "agent": null,
          "session": null,
          "project": { "slug": "billing", "display_name": null, "root_uri": null, "repo_remote": null, "default_branch": null }
        },
        "counts": { "episodes": 12, "records": 3, "topics": 1 },
        "last_used_at": "2026-10-03T17:29:26+00:00"
      }
    ],
    "total": 1,
    "offset": 0,
    "message": null
  },
  "isError": false
}
```

- Ordering is deterministic: most recently used first, stable tie-break.
- Page with `limit` (1–1000) + `offset`; `message` tells you where the window
  sits (`"Showing N of T scopes at offset ..."`) and `total` is the full count.
- Each returned `scope` can be passed **verbatim** back as the `scope`
  argument of any other tool.

### Policies and ACL

Scopes decide *visibility*; policies decide *permission*:

- `memory_policy_list` — persisted access policies and ACL bindings.
- `memory_policy_grant` — create/update a binding for a principal with
  `write_mode` (`allow`/`deny`) and `read_visibility`
  (`private`/`namespace`/`project`).
- A denied write returns `status: "write_denied"` in the success payload —
  it is a business outcome, not a transport error.

Full reference — resolution order, principal tokens, CLI/REST/agent
configuration, worked examples: **[ACL.md](ACL.md)**.

## Errors, timeouts and fallbacks

### Error taxonomy (MCP)

| Kind | Transport shape | Example |
| --- | --- | --- |
| Protocol error | JSON-RPC `error` (no result) | Unknown tool, malformed request |
| Tool execution error | Result with `isError: true` + actionable text + `structuredContent.error` | Timeout, bad input, dispatch failure |
| Business outcome | Result with `isError: false` and a status field | `status: "not_found"`, `status: "write_denied"` |

Only the middle row is `isError: true`; success-shaped payloads with a
non-happy `status` are **not** failures — callers branch on the status.

### Timeout resolution

Per tool: `CONSOLIDATION_MEMORY_TIMEOUT_<TOOL>` → per-tool default →
`CONSOLIDATION_MEMORY_TOOL_TIMEOUT_SECONDS` (default **60s**).

| Tool | Default | Tool | Default |
| --- | --- | --- | --- |
| `memory_store`, `memory_remember`, `memory_search` | 30s | `memory_claim_browse`, `memory_outcome_*`, `memory_status` | 30s |
| `memory_forget`, `memory_protect`, `memory_read_topic` | 30s | `memory_contradictions`, `memory_consolidation_log` | 30s |
| `memory_claim_search`, `memory_decay_report`, `memory_timeline`, `memory_browse` | 45s | `memory_ask`, `memory_store_batch`, `memory_correct` | 60s |
| `memory_hygiene_scan` | 60s | `memory_hygiene_apply`, `memory_export` | 180s |
| `memory_compact` | 120s | `memory_consolidate` | 600s |
| `memory_policy_list`, `memory_policy_grant` | 20s | `memory_recall`, `memory_detect_drift`, `memory_scope_list` | see below |

Dedicated budgets (own environment variables):

| Variable | Default | Purpose |
| --- | --- | --- |
| `CONSOLIDATION_MEMORY_RECALL_TIMEOUT_SECONDS` | 60s | Semantic recall phase of `memory_recall` / `memory_ask` |
| `CONSOLIDATION_MEMORY_RECALL_FALLBACK_TIMEOUT_SECONDS` | 10s | Keyword-only fallback after a recall timeout |
| `CONSOLIDATION_MEMORY_DRIFT_TIMEOUT_SECONDS` | 90s | Drift scan (first attempt with `base_ref`) |
| `CONSOLIDATION_MEMORY_CLIENT_INIT_TIMEOUT_SECONDS` | 90s | Lazy client/engine startup on first tool call |

### Fallback chains

- **`memory_recall`**: semantic phase times out → keyword `memory_search`
  fallback (payload gains a `message`/`warnings` explaining the degradation)
  → if that also times out, `isError: true` with tuning advice
  (shorter query, lower `n_results`, raise the budget).
- **`memory_detect_drift`**: first scan with `base_ref` times out → retry
  without `base_ref` (payload carries a `message` about the fallback) → if
  that fails too, a degraded result: full shape with empty lists and a
  `message`, reported as `isError: true`.
- **`memory_consolidate`**: bounded by its own budget; timeouts and crashes
  are `isError: true` with the exact variable to raise.

### Troubleshooting

| Symptom | Fix |
| --- | --- |
| `... timed out after Ns. Raise CONSOLIDATION_MEMORY_TIMEOUT_...` | Raise the named variable or reduce work (`n_results`, corpus size) |
| `Extra inputs are not permitted` | Remove the unknown argument — the published `inputSchema` is the contract |
| Recall answers feel stale right after startup | `CONSOLIDATION_MEMORY_DEFERRED_KNOWLEDGE_RETRY_SECONDS` (default `3`) delays knowledge inclusion; set `0` for immediate reads |
| First call is slow | Client init + warmup run lazily; prewarm with `CONSOLIDATION_MEMORY_WARMUP_ON_START=1` (default on) and `CONSOLIDATION_MEMORY_PRELOAD_SCIPY_ON_START=1` |
| Two server processes fight over the DB | The stdio singleton guard serializes per project; tune `CONSOLIDATION_MEMORY_STDIO_SINGLETON` / `..._TAKEOVER_TIMEOUT_SECONDS` |

## Environment reference

All variables are prefixed `CONSOLIDATION_MEMORY_`.

### Paths and projects

| Variable | Purpose |
| --- | --- |
| `CONFIG` | Path to an alternate `config.toml` |
| `DATA_DIR` | Base data directory (default: platform data dir) |
| `PROJECT` | Active project slug (default: `default`) |

### Backends

| Variable | Default | Purpose |
| --- | --- | --- |
| `EMBEDDING_BACKEND` | `fastembed` | `fastembed`, `lmstudio`, `openai`, `ollama` |
| `LLM_BACKEND` | `lmstudio` | `lmstudio`, `openai`, `ollama`, `disabled` |
| `FASTEMBED_CACHE_DIR` | platform cache | Where the embedding model is downloaded |
| `CONSOLIDATION_AUTO_RUN` | `true` | Background consolidation scheduler |

### MCP runtime

| Variable | Default | Purpose |
| --- | --- | --- |
| `MCP_TOOL_PROFILE` | `full` | `full` or `simple` (3 tools) |
| `MCP_AUTO_CONSOLIDATE` | off | Let the engine consolidate after stores when idle |
| `MCP_BLOCKING_WORKERS` | 16 | Worker threads for blocking tool bodies |
| `WARMUP_ON_START` | on | Warm caches at server startup |
| `WARMUP_START_DELAY_SECONDS` / `WARMUP_AWAIT_SECONDS` | — | Warmup scheduling knobs |
| `WARMUP_PRIME_TOPIC_CACHE` / `WARMUP_PRIME_RECORD_CACHE` | `true` | Prime recall caches at warmup |
| `WARMUP_PRIME_CLAIM_CACHE` | `false` | Prime the claim cache (heavier) |
| `PRELOAD_SCIPY_ON_START` / `PRELOAD_NUMERIC_BACKENDS_ON_START` | — | Import heavy numeric deps up front (avoids first-call stalls) |
| `STATUS_LIGHTWEIGHT` | off | Default of `memory_status(lightweight=true)`: skip markdown scans |
| `IDLE_TIMEOUT_SECONDS` | — | Exit stdio server after N idle seconds (`0` = never) |
| `IDLE_CHECK_INTERVAL_SECONDS` | — | Idle sweep cadence |
| `STDIO_SINGLETON` / `STDIO_SINGLETON_TAKEOVER_TIMEOUT_SECONDS` | on / — | One server process per project; takeover wait |
| `DUMP_STACKS_ON_CLIENT_INIT_TIMEOUT` | off | Thread dump when client init hangs |

### Timeouts and recall

| Variable | Default | Purpose |
| --- | --- | --- |
| `TOOL_TIMEOUT_SECONDS` | 60 | Fallback budget for tools without a dedicated default |
| `TIMEOUT_<TOOL>` | per-tool | Per-tool override, e.g. `TIMEOUT_MEMORY_STATUS` |
| `RECALL_TIMEOUT_SECONDS` | 60 | Semantic recall phase |
| `RECALL_FALLBACK_TIMEOUT_SECONDS` | 10 | Keyword fallback phase |
| `RECALL_DEADLINE_MARGIN_RATIO` | 0.85 | Share of the budget reserved before fallback |
| `DRIFT_TIMEOUT_SECONDS` | 90 | Drift scan budget |
| `CLIENT_INIT_TIMEOUT_SECONDS` | 90 | Client/engine startup budget |
| `DEFERRED_KNOWLEDGE_RETRY_SECONDS` | 3 | Wait before knowledge is guaranteed fresh in recall |

### REST (when the HTTP surface is enabled)

| Variable | Purpose |
| --- | --- |
| `REST_AUTH_TOKEN` | Bearer token (required beyond loopback) |
| `REST_ALLOW_PUBLIC_BIND` | Explicit opt-in for non-loopback bind |

## Recipes

### Remember something, then ask about it

```json
{"method": "tools/call", "params": {"name": "memory_remember", "arguments": {"content": "We deploy on Tuesdays; use podman locally.", "kind": "preference"}}}
```

```json
{"method": "tools/call", "params": {"name": "memory_ask", "arguments": {"query": "how do we deploy?"}}}
```

### Store with tags, retrieve semantically

```json
{"method": "tools/call", "params": {"name": "memory_store", "arguments": {"content": "Fix: retry the migration checksum check before deploy", "content_type": "solution", "tags": ["deploy", "ci"]}}}
```

```json
{"method": "tools/call", "params": {"name": "memory_recall", "arguments": {"query": "what breaks the deploy?", "n_results": 5}}}
```

### Work inside a project scope

```json
{"method": "tools/call", "params": {"name": "memory_store", "arguments": {"content": "Billing uses quarterly schema bumps", "scope": {"project": {"slug": "billing"}}}}}
```

```json
{"method": "tools/call", "params": {"name": "memory_search", "arguments": {"query": "schema", "scope": {"project": {"slug": "billing"}}}}}
```

### Discover scopes, then page through them

```json
{"method": "tools/call", "params": {"name": "memory_scope_list", "arguments": {"limit": 20}}}
```

Take any `scopes[i].scope` and reuse it as the `scope` argument above; if
`message` reports more pages, call again with `"offset": 20`.

### Consolidation health loop

```json
{"method": "tools/call", "params": {"name": "memory_consolidate", "arguments": {}}}
{"method": "tools/call", "params": {"name": "memory_status", "arguments": {"lightweight": true}}}
{"method": "tools/call", "params": {"name": "memory_consolidation_log", "arguments": {"last_n": 5}}}
```

### Challenge claims against code changes

```json
{"method": "tools/call", "params": {"name": "memory_detect_drift", "arguments": {"repo_path": "/path/to/repo", "base_ref": "main"}}}
{"method": "tools/call", "params": {"name": "memory_claim_search", "arguments": {"query": "deploy pipeline"}}}
```

## Surfaces parity

MCP, REST, the Python SDK and the OpenAI-compatible schemas all route through
the same dispatch (`tool_dispatch.py`) and canonical query layer — tool names,
parameters and payload shapes match across surfaces. The only surface-specific
parts are transport encoding and the MCP-only bits documented here
(`outputSchema` publication, `isError` mapping, stdio lifecycle).

- OpenAI tool schemas: [`src/consolidation_memory/schemas.py`](../src/consolidation_memory/schemas.py)
- REST surface: [README — REST](../README.md#rest-api)
- Architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
