# Security Policy

## Supported Versions

The project currently supports security fixes for the latest published minor release line.

| Version line | Supported |
| --- | --- |
| `0.21.x` | Yes |
| `0.20.x` | Best-effort (upgrade to `0.21.x`) |
| `<0.20.0` | No |

## Trust Boundaries

Data-level sharing between principals (scope policies, ACL bindings, deny/read visibility) is documented in [docs/ACL.md](docs/ACL.md); it is not a substitute for transport authentication.

### MCP (stdio)

The default MCP server speaks JSON-RPC over stdio. **Any process that can launch the server can read and write the full memory database** for the configured project. There is no authentication layer on stdio transport.

Treat MCP as a **local trust boundary** (IDE, agent host, same user session). Do not expose the MCP subprocess to untrusted multi-tenant environments without OS-level isolation.

### REST API

When bound beyond loopback, REST requires a bearer token (see README REST section). Binding to non-loopback addresses without a token is rejected at startup.

### Python SDK

Direct `MemoryClient` usage inherits the privileges of the calling process and reads/writes the same on-disk project data as MCP.

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