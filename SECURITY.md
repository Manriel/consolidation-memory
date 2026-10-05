# Security Policy

## Supported Versions

The project currently supports security fixes for the latest published minor release line.

| Version line | Supported |
| --- | --- |
| `0.21.x` | Yes |
| `0.20.x` | Best-effort (upgrade to `0.21.x`) |
| `<0.20.0` | No |

The supported line is the latest published minor. A breaking change ships as a
minor in 0.x, so a new minor moves the "Yes" row up and demotes the previous
line to best-effort.

## Trust Boundaries

Data-level sharing between principals (scope policies, ACL bindings, deny/read visibility) is documented in [docs/ACL.md](docs/ACL.md); it is not a substitute for transport authentication.

### MCP (stdio)

The default MCP server speaks JSON-RPC over stdio. **Any process that can launch the server can read and write the full memory database** for the configured project. There is no authentication layer on stdio transport.

Treat MCP as a **local trust boundary** (IDE, agent host, same user session). Do not expose the MCP subprocess to untrusted multi-tenant environments without OS-level isolation.

### REST API

When bound beyond loopback, REST requires a bearer token (see README REST section). Binding to non-loopback addresses without a token is rejected at startup. `/health` is the only auth-exempt path.

Routes: 35, covering the same 29 tools as MCP and OpenAI dispatch (per-tool schemas in [docs/TOOLS.md](docs/TOOLS.md)). The security-relevant asymmetry: several routes take no request body, so they can only answer for the deployment, not for a caller-supplied scope — `GET /memory/status`, `GET /memory/browse`, `GET /memory/decay-report`, `GET /memory/policy`, `GET /memory/hygiene/scan` and the new `GET /memory/scopes`. Their `POST` twins accept an explicit `scope` and are the scoped variants.

#### `GET /memory/scopes` discloses deployment topology

Scope discovery returns the deployment's scope topology — namespaces, projects, app clients, agents, sessions — with per-table row counts (`episodes`, `records`, `topics`), most-recently-used first, pageable via `limit`/`offset`.

It is **intentionally global**: the result is not filtered by `read_visibility`, by policy, or by the caller's scope. A principal that can only read its own scope still learns that other scopes exist and roughly how large they are. Two reasons:

- It is a topology **audit** tool — the value is in showing what the deployment actually contains, including scopes the caller cannot read into.
- The transport already grants far more. On stdio, any process that can launch the server has full database access; the REST token authenticates the transport, not a tenant boundary.

`docs/ACL.md` separates principals *inside* one deployment. Treat `memory_scope_list` (and `GET /memory/scopes`) as deployment-scoped metadata, not tenant isolation. Do not expose either surface to mutually distrusting tenants.

### Python SDK

Direct `MemoryClient` usage inherits the privileges of the calling process and reads/writes the same on-disk project data as MCP.

## Policy Coverage (`write_mode`)

`write_mode='deny'` is enforced by `client._write_denied_message` at exactly six call sites. A denial is a business outcome, not a transport error: the call succeeds and the payload carries `status: "write_denied"`.

Gated: `memory_store`, `memory_remember`, `memory_store_batch`, `memory_outcome_record`, `memory_forget`, `memory_correct`, `memory_protect`.

**Not gated by `write_mode`**: `memory_export`, `memory_compact`, `memory_consolidate`, `memory_hygiene_scan`, `memory_hygiene_apply`, `memory_detect_drift`, and policy administration (`memory_policy_list`, `memory_policy_grant`). These are maintenance and administration operations, and the transport itself is not gated. A `deny` policy therefore does not stop an export or a hygiene apply. Scope them with the transport boundary, not with policy.

## Input Contract Enforcement

Unknown input arguments are rejected on every surface, from one shared allowed-argument set derived from the published `inputSchema` (`tool_dispatch.accepted_argument_names`):

- **MCP** — pydantic `extra="forbid"` on the SDK argument model, before the tool body runs.
- **REST** — request bodies derive from `rest.StrictRequestModel` (`extra="forbid"`); an unknown body key is HTTP 422 naming the offending keys. Query parameters are not covered.
- **OpenAI / dispatch** — `tool_dispatch.reject_unknown_arguments` runs first in `execute_tool_call` and raises `ToolContractError`.

`server._verify_published_argument_contract()` cross-checks the SDK-enforced set against the dispatch-side set for every registered tool at import and in `lifespan`, raising `MCPCompatError` on divergence. A test asserts set equality between the published properties, the enforced set, and the MCP `input_schema` for all 29 tools.

## Output Contract Integrity

Every tool publishes `outputSchema` as `anyOf[success, error]`. Publication is self-healing: `mcp_compat.install_list_tools_heal` wraps the SDK's `tools/list` funnel, so a tool registered after startup gets its schema on the next listing, and the SDK's cached `Tool.output_schema` is evicted when it would go stale. At import and in `lifespan`, `server._verify_published_output_schemas()` fails loudly if any registered tool would publish a success-only schema.

Private `mcp` SDK surfaces are isolated in `src/consolidation_memory/mcp_compat.py`; the supported range is `mcp>=2.3.0,<3` and a missing module or attribute raises `MCPCompatError` naming the installed version, the supported range, and what was probed. `mcp_compat.MCPCompatError` at startup is a hard failure, not a degradation.

## Reporting a Vulnerability

Do not open public GitHub issues for security vulnerabilities.

Report vulnerabilities through GitHub Private Vulnerability Reporting:

- [https://github.com/charliee1w/consolidation-memory/security/advisories/new](https://github.com/charliee1w/consolidation-memory/security/advisories/new)

Include:

- A clear description of impact and affected component(s)
- Reproduction steps or proof-of-concept
- Any suggested mitigation

## Response Expectations

- Initial acknowledgement target: within 3 business days
- Triage/update target: within 7 business days
- Fix and disclosure timing depends on severity and release complexity

We will coordinate disclosure timing with reporters when possible.