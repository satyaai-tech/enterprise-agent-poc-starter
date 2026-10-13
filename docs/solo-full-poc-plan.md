# Solo Full POC Plan

## 1. Objective

Evaluate whether Solo’s open-source agentgateway can provide three distinct gateway roles as the selected primary POC path:

1. Northbound API gateway
2. Agent-to-agent A2A gateway
3. MCP gateway

Solo is now the selected primary POC direction. Kong Phase 0 remains preserved as historical and reference evidence only.

## 2. Preserved Kong profile

Document this architecture as historical reference only:

Notebook
→ Kong API Gateway
→ trusted external authorizer
→ Agent A
→ A2A gateway
→ Agent B
→ MCP gateway
→ banking MCP mock server

The completed Phase 0 Kong and external-authorizer evidence remains unchanged and is retained for historical context.

## 3. Selected Solo profile

Document this architecture as the active POC path:

Notebook
→ Solo agentgateway instance 1: API edge
→ Agent A
→ Solo agentgateway instance 2: A2A boundary
→ Agent B
→ Solo agentgateway instance 3: MCP boundary
→ banking MCP mock server

Three separately configured gateway instances are preferred because they provide:

- separate trust boundaries
- isolated policy configuration
- independent ports and logs
- reduced blast radius
- easier testing and comparison

The Solo path is the selected primary direction; it is not a production certification claim.

## 4. Shared components

Both profiles should reuse:

- Microsoft Entra test tenant and test user
- Notebook Client registration
- Agent A and Agent B registrations
- Agent A → Agent B OBO flow
- local Google ADK agents
- local Ollama
- banking MCP mock server
- common acceptance tests where possible

The gateways do not replace Entra, ADK, Ollama, Agent A, Agent B, or the MCP server.

## 5. Proposed repository organization

Recommend this target structure without moving anything yet:

```text
infra/
├── kong/
│   └── existing Kong configuration
└── solo/
    ├── api-edge/
    ├── a2a-gateway/
    └── mcp-gateway/

agents/
├── agent-a/
└── agent-b/

mcp/
└── banking-mock/

deployments/
├── kong-profile/
└── solo-profile/
```

Implementation may initially remain under `experiments/solo-agentgateway/` until each spike is verified.

## 6. Phased implementation

### Solo Phase 1 — API edge (COMPLETE)

The isolated API-edge spike is complete with synthetic local evidence:

Synthetic client
→ Solo agentgateway
→ private mock Agent A

Required validation:

- valid JWT accepted
- missing and malformed JWT rejected
- expired and not-yet-valid JWT rejected
- tampered signature rejected
- wrong issuer, tenant, audience, scope, and authorized client rejected
- exact scope membership enforced
- missing `iat` rejected
- incorrect signing algorithm tested
- JWKS cold-start failure tested
- cached-JWKS outage behavior observed
- rejected requests proven not to reach Agent A
- only the gateway host port exposed

### Solo Phase 2 — A2A and OBO (COMPLETE)

The local Entra-backed A2A/OBO validation is complete with both synthetic and live evidence:

Agent A
→ Agent A performs Entra OBO in application code
→ Solo A2A gateway
→ Agent B

Acceptance criteria:

- device-code login succeeds locally
- Token A is validated for Agent A
- Agent A performs OBO for Agent B
- Token B is validated for Agent B
- same delegated-user continuity is verified
- Solo agentgateway authorization succeeds
- Agent B defense-in-depth validation succeeds
- Token A is rejected at the Agent B boundary
- successful A2A message delivery is observed
- Docker cleanup runs automatically after each run

The remaining roadmap remains exactly as follows.

- Agent A receives a delegated Agent A token
- Agent A performs OBO for Agent B
- Agent B token retains the same delegated user
- Agent B audience and scope are correct
- Agent A token is rejected when presented directly to Agent B
- invalid, expired, wrong-tenant, wrong-client, and wrong-scope tokens fail closed
- A2A gateway routing and policy behavior are verified
- raw tokens and secrets are never logged

Clearly separate Entra OBO behavior performed by Agent A from A2A routing and enforcement performed by the gateway.

### Solo Phase 3 — MCP gateway (COMPLETE)

Implement:

Agent B
→ Solo MCP gateway
→ banking MCP mock server

The mock server must expose at least:

- one read tool
- one write tool

Acceptance criteria:

- authenticated MCP connection succeeds
- unauthenticated connection fails
- read-authorized user can discover and call the read tool
- read-only user cannot discover or call the write tool
- read/write-authorized user can call both tools
- denied calls never reach the banking server
- tool-level authorization uses verified identity claims
- write operations include confirmation, idempotency, and replay protections as required by the existing project plan

Clearly distinguish gateway authorization from final business authorization enforced by the banking server.

### Solo Phase 4 — Local agents and model (COMPLETE)

Connect:

- Jupyter Notebook
- Agent A using Google ADK
- Agent B using Google ADK
- local Ollama
- Solo API, A2A, and MCP gateway instances
- banking MCP mock server

Document Docker Desktop networking and when `host.docker.internal` is required to reach host-based Ollama or agents.

This Phase 4 local-agent slice is complete with sanitized evidence showing the Solo A2A gateway route, private Agent B runtime, and verified delegated PASS result through the local Ollama-backed ADK flow.

### Solo Phase 5 — End-to-end Solo validation (CURRENT, IN PROGRESS)

Phase 5 slice status:

- Slice 5A: COMPLETE — validated read-only evidence remains valid for the read-only architecture
- Slice 5B: PLANNED / guarded live validation required before completion can be claimed
- Slice 5C: PLANNED / NOT STARTED — Per-User Read/Write Authorization

Phase 5 remains IN PROGRESS until the required write-capable Slice 5C gates and evidence are complete. The existing read-only evidence must not be treated as end-to-end write-capable evidence.

Run the complete Solo flow end-to-end:

1. Jupyter Notebook
2. Solo agentgateway API edge
3. Agent A using Google ADK and local Ollama
4. Solo agentgateway A2A boundary
5. Agent B using Google ADK and local Ollama
6. Solo agentgateway MCP boundary
7. banking MCP mock server

Validate:

- identity validation
- Entra compatibility
- OBO behavior
- A2A routing
- MCP protocol support
- MCP tool authorization
- fail-closed behavior
- observability
- configuration complexity
- local Docker networking
- operational isolation
- verified limitations

This is validation of the complete Solo flow, not a Kong-versus-Solo comparison. Do not claim production readiness.

### Solo Phase 6 — FastMCP and MACAW trust mesh (PLANNED)

Phase 6 remains a planned future work stream and does not include the Phase 5 Slice 5C implementation. It introduces FastMCP compatibility and MACAW policy enforcement without changing the completed read-only Phase 5 baseline. Phase 5 must not be marked complete until the required Slice 5C gates and evidence are recorded.

#### Slice 5C — Per-User Read/Write Authorization (PLANNED / NOT STARTED)

Purpose:

Extend the proven Phase 5 read-only flow with deterministic, per-user authorization and controlled banking transfers. This slice is intentionally planned as a separate Phase 5 extension and is not a claim that controlled transfer support currently exists end to end.

The model may interpret the user request and choose an appropriate tool, but it must never grant authorization. Authorization decisions must come from validated Microsoft Entra claims and deterministic gateway and Banking MCP policy enforcement.

Two-user POC model:

- `poc-banking-reader` is assigned `Banking.Reader` only and is not assigned `Banking.Writer`.
- `poc-banking-writer` is assigned both `Banking.Reader` and `Banking.Writer`.
- Both users authenticate independently with distinct `oid` values under the configured POC tenant `tid`.
- Token C must contain the delegated scope and the user’s assigned Banking MCP app roles.

Authorization matrix:

| Test identity | Banking.Reader | Banking.Writer | Read balance | Create transfer |
|---|---:|---:|---:|---:|
| `poc-banking-reader` | Yes | No | Allowed | Denied |
| `poc-banking-writer` | Yes | Yes | Allowed | Allowed with additional controls |

The implementation boundary for Slice 5C is limited to planned Entra app roles, Token C validation, unified gateway policy, Banking MCP authorization and ownership checks, confirmation, idempotency, and the required live validation evidence. It does not include MACAW or the FastMCP migration; those remain Phase 6 responsibilities.

Required policy model:

- Use validated `tid` and `oid` as the stable user identity and ownership boundary.
- Do not authorize using email address, display name, prompt text, or `preferred_username`.
- `preferred_username` remains diagnostic/display data only.
- Read requires `Banking.Read` plus either `Banking.Reader` or `Banking.Writer`.
- Transfer requires `Banking.Write` plus `Banking.Writer`.
- Gateway authorization must run before forwarding the MCP request.
- Banking MCP must repeat claim and ownership checks as defense in depth.
- Reader users must not be able to discover or call `create_transfer`.
- Writer users may call `create_transfer` only after deterministic transfer controls pass.

Required transfer controls:

- source and destination ownership checks using validated `tid` and `oid`
- explicit user confirmation
- positive and valid transfer amount
- caller-supplied idempotency key
- same idempotency key must not create duplicate mutation
- fail closed for missing or malformed Token C, required scope, role, identity, confirmation, ownership, or idempotency key
- no raw token, secret, authorization header, or complete JWT payload in logs or evidence
- raw identity debug logging remains off by default and guarded by `POC_LOG_RAW_USER_ID=true`

The required Phase 5 flow remains:

```text
User/Gradio → Token A → Agent A → OBO Token B → Agent B → OBO Token C → agentgateway MCP policy → Banking MCP
```

This flow must preserve the same delegated user across Token A, Token B, and Token C, while the gateway and Banking MCP enforce the same identity and authorization boundary before any write executes.

No implementation or evidence is created as part of this documentation-only task. The slice remains planned until its synthetic and guarded live gates pass and are recorded under `evidence/phase-5/`.

The migration and security integration must be implemented as separate validation gates so failures can be attributed either to the MCP framework migration or to MACAW policy enforcement.

#### Phase 6A — FastMCP migration

Objective:

Convert the Banking MCP server's custom MCP transport and dispatch layer into a FastMCP-compatible server without changing the existing banking behavior or security contract.

Requirements:

- pin an explicitly supported FastMCP version
- expose the existing MCP endpoint using Streamable HTTP
- preserve the existing MCP lifecycle and Agent B client compatibility
- preserve `get_account_summary` and `create_transfer`
- preserve Token C authentication, scope enforcement, scope-based tool discovery, and direct-call authorization checks
- preserve account ownership, explicit confirmation, positive-amount validation, idempotent retries, conflicting-replay rejection, and fail-closed behavior
- preserve sanitized flow-ID propagation, `/healthz`, private debug state, and counters proving rejected calls do not execute tools or mutate state
- keep the unified Solo agentgateway as the transport and JWT enforcement boundary
- do not add MACAW policy enforcement during this slice

Validation gate:

- existing focused MCP tests pass against the FastMCP implementation
- existing token-boundary tests pass
- existing unified Slice 5A end-to-end validation passes
- read-only calls return the same business result as the Phase 5 baseline
- rejected and write-related calls preserve their existing counter and mutation guarantees
- no generated token, private key, JWKS, or rendered configuration remains in the repository

#### Phase 6B — MACAW SecureMCP integration

Objective:

Wrap the FastMCP-compatible Banking MCP server with MACAW `SecureMCP` so MACAW policy is evaluated before a banking tool executes.

Intended request path:

```text
Agent B
  -> Token C
  -> unified Solo MCP listener
  -> MACAW SecureMCP policy evaluation
  -> FastMCP Banking MCP tool
```

Requirements:

- keep Solo agentgateway responsible for transport routing and JWT enforcement
- keep the Banking MCP server's existing authorization and business checks as defense in depth
- apply MACAW policy before `get_account_summary` or `create_transfer` executes
- do not rely on prompt instructions as an authorization boundary
- prevent denied calls from reaching banking tool execution
- prevent denied writes from incrementing transfer attempts or mutations
- fail closed when the MACAW policy decision cannot be obtained
- keep policy errors sanitized and never log tokens, sensitive identity claims, account data, secrets, or policy internals
- preserve the shared non-sensitive flow ID across the gateway, MACAW decision, and MCP execution path

Validation gate:

- an allowed read reaches `get_account_summary`
- a denied read does not execute the tool
- a denied write does not execute `create_transfer`
- denied calls do not increment mutation counters
- policy-service failure is fail-closed
- existing JWT, ownership, confirmation, amount, and idempotency checks remain effective
- Phase 5 regression behavior remains intact

#### Phase 6C — Trust-mesh validation

Objective:

Extend and validate approved MACAW trust controls across the broader agent workflow.

Candidate policy boundaries:

- Agent A delegation to Agent B
- Agent A model calls
- Agent B model calls
- Agent B invocation of Banking MCP
- Banking MCP tool execution

Requirements:

- confirm which Google ADK integration points are officially supported by the selected MACAW version
- do not claim a native Google ADK adapter unless current MACAW documentation verifies it
- use explicit wrapper or middleware integration where no native adapter exists
- keep Solo agentgateway as the network and JWT boundary
- keep MACAW as a pre-execution policy and trust-decision layer
- validate allowed, denied, unavailable-policy-service, and fail-closed paths
- produce sanitized evidence only after the implementation passes its validation gates
- update the physical deployment diagram to show only actual, verified placement

Phase 6 guardrails:

- Phase 5 remains unchanged and serves as the comparison baseline
- FastMCP migration and MACAW integration remain separate slices
- no production-readiness claim
- no live Entra changes unless separately authorized
- do not weaken Token C, scope, ownership, confirmation, or idempotency enforcement
- do not store tokens, secrets, private keys, personal identity claims, or account data in evidence
- do not add a separate `SecureMCPProxy` container if direct `SecureMCP` integration is proven compatible and meets the required controls
- if direct `SecureMCP` integration is not compatible, document `SecureMCPProxy` as the fallback architecture rather than silently changing the topology

Preferred deployment effect:

The preferred design keeps the same four core application containers: the unified Solo agentgateway, Agent A, Agent B, and Banking MCP. FastMCP and `SecureMCP` run inside the Banking MCP container. A separate MACAW proxy container is not required for the preferred design. Any external or managed MACAW control plane must be shown separately from the four core application containers.

## 7. Evidence rules

For every phase:

- distinguish documented capability from locally verified capability
- use timestamped, sanitized evidence
- never store raw JWTs, secrets, usernames, email addresses, `oid`, `sub`, or personal claims
- keep temporary per-request evidence in pytest temporary storage
- do not overwrite historical evidence
- label synthetic and live Entra tests separately
- do not claim unsupported functionality as verified

## 8. Git workflow

Recommend:

- preserve both profiles in the same repository
- use a short-lived feature branch for each spike
- open a pull request for review
- merge verified work into `main`
- do not maintain Kong and Solo permanently on separate Git branches
- never run multiple coding agents against the same branch simultaneously

## 9. Deferred scope

Keep MACAW deferred until Phase 6. Phase 5 must close and provide the comparison baseline before FastMCP migration or MACAW integration begins.

Do not include Kubernetes, production deployment, high availability, production secrets, or enterprise licensing in the initial local POC unless separately approved.

## 10. Final deliverable

The completed POC should allow the same notebook, agents, identity flow, Ollama model, and banking MCP server to run behind the selected all-Solo architecture. The result must be an evidence-backed local validation of the full Solo flow, not a production certification claim.
