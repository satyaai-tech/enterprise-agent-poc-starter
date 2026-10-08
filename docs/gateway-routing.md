# Gateway and Routing Design

“Agent Gateway” describes two architectural roles. Phase 0 must select and verify specific open-source software and versions; this document makes no product capability claim.

## Logical routes

| Hop | Caller location | Target location | Addressing rule | Intended security |
|---|---|---|---|---|
| Notebook → Kong | Mac host | Docker | `http://localhost:<kong-published-port>` during local development | User bearer token; TLS decision documented |
| Kong → Agent A | Docker | Mac host | `http://host.docker.internal:<agent-a-port>` | Verified token enforcement before routing; protected upstream |
| Agent A → Ollama | Mac host | Mac host | `http://localhost:<ollama-port>` | Local-only bind where possible; model is not an authorizer |
| Agent A → A2A gateway | Mac host | Docker | `http://localhost:<a2a-published-port>` | B-audience delegated token or verified equivalent |
| A2A gateway → Agent B | Docker | Mac host | `http://host.docker.internal:<agent-b-port>` | Authenticated route; Agent B revalidates authorization |
| Agent B → MCP gateway | Mac host | Docker | `http://localhost:<mcp-gateway-published-port>` or verified supported transport | Bound identity context and tool policy |
| MCP gateway → banking mock | Docker | Mac host | `http://host.docker.internal:<banking-mock-port>` or verified supported transport | Least-privilege tool call; mock rechecks policy |

If Agent A, B, or the banking mock later move into Docker, address them by Compose service name on a user-defined network. Do not retain `host.docker.internal` blindly after topology changes.

## `host.docker.internal` rule

Inside a container, `localhost` identifies that container. On Docker Desktop for Mac, a container normally uses `host.docker.internal` to reach a service bound on the Mac host. The host service must listen on an address reachable from Docker Desktop; verify this carefully and avoid unnecessary LAN exposure.

From the Mac host, use `localhost:<published-port>` to reach a container port published by Docker Desktop. Publishing a port is an exposure decision and must be listed in the threat model.

## Northbound Kong route

Target behavior:

- Expose only the intended Agent A path and health behavior.
- Reject missing or invalid tokens before forwarding.
- Preserve or generate a correlation ID using a strict format.
- Strip spoofable identity headers from the client.
- Add only identity context produced by a trusted validation mechanism, and protect the Kong-to-A hop from header spoofing/bypass.
- Apply body, header, and timeout limits.

Kong OSS implementation remains blocked on the validation gate in `entra-identity.md`. Do not write configuration that merely decodes a JWT or checks one claim and label it complete validation.

## A2A gateway selection checklist

For each candidate and pinned version, demonstrate:

- Conformance with the exact A2A protocol version selected by the project.
- Agent discovery/card handling, task/message semantics, streaming needs, and error behavior required by the POC.
- Authentication integration capable of carrying or validating the approved Entra/OBO context.
- Policy for allowed caller, target agent, and operation.
- Payload limits, timeouts, cancellation, retries, and replay behavior.
- Trace/correlation propagation and token redaction.
- Docker Desktop compatibility, license, active maintenance, and dependency provenance.

If these are not demonstrated, use a simpler explicitly documented boundary or revise the design. Do not describe untested features as supported.

## MCP gateway selection checklist

Demonstrate for the selected MCP version and transport:

- Tool discovery and invocation semantics required by Agent B.
- Server allowlisting and prevention of arbitrary upstream selection.
- Authentication and authorization hooks with a trustworthy binding to the user and calling agent.
- Per-tool and per-operation read/write policy.
- JSON schema/argument limits, response limits, timeout, cancellation, and error behavior.
- Write confirmation, idempotency, replay protection, and audit events.
- Protection against malicious tool descriptions/results and prompt injection.

An MCP router that merely forwards messages is not an authorization gateway.

## Failure behavior

- Fail closed when identity metadata, key retrieval, the authorizer, or a policy engine is unavailable.
- Bound retries; never automatically retry an ambiguous state-changing operation without idempotency.
- Return sanitized errors to clients and retain redacted diagnostic detail locally.
- Keep health endpoints from revealing tokens, tenant details, or tool inventories.
- Do not let direct upstream ports provide an undocumented policy bypass.

## Deferred

Macaw is not part of gateway selection, routing, or evaluation in this POC.

