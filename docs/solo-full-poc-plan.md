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

### Solo Phase 4 — Local agents and model

Connect:

- Jupyter Notebook
- Agent A using Google ADK
- Agent B using Google ADK
- local Ollama
- Solo API, A2A, and MCP gateway instances
- banking MCP mock server

Document Docker Desktop networking and when `host.docker.internal` is required to reach host-based Ollama or agents.

### Solo Phase 5 — End-to-end Solo validation

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

Keep Macaw explicitly deferred.

Do not include Kubernetes, production deployment, high availability, production secrets, or enterprise licensing in the initial local POC unless separately approved.

## 10. Final deliverable

The completed POC should allow the same notebook, agents, identity flow, Ollama model, and banking MCP server to run behind the selected all-Solo architecture. The result must be an evidence-backed local validation of the full Solo flow, not a production certification claim.
