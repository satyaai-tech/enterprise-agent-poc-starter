# Local Enterprise Agent POC Starter

Documentation, experiment scaffolding, and the active all-Solo roadmap for a local, identity-aware, multi-agent banking proof of concept on macOS. Historical Kong materials are retained as reference evidence, while the active direction is the Solo agentgateway path.

## Active POC direction

The active POC direction is the all-Solo architecture:

```text
Jupyter Notebook (Mac host)
  -> Solo agentgateway API edge
  -> Agent A (Google ADK, local; Ollama model)
  -> Solo agentgateway A2A boundary
  -> Agent B (Google ADK, local; Ollama model)
  -> Solo agentgateway MCP boundary
  -> local MCP banking mock server (read/write tools)
```

Microsoft Entra ID supplies a test user and separate registrations for Agent A and Agent B. The active design tests user-token validation at the northbound API edge, Agent A to Agent B OBO in application code, and independent validation at the Solo agentgateway boundaries before routing and tool execution.

## Important status and constraints

- This repository retains the Kong Phase 0 work as historical/reference evidence only. Kong is not part of the active runtime path for the selected POC direction.
- The all-Solo architecture is the active POC direction and the primary path for ongoing implementation and validation.
- OBO, workload/agent identity, A2A policy enforcement, and MCP authorization remain local POC validations, not production certification.
- “Agent Gateway” is a role in this design until a specific open-source project and release are selected and tested. A product with that phrase in its name is not implicitly endorsed.
- The banking service is a local mock. It must never hold real credentials, accounts, or financial data.
- MACAW is deferred until the planned Phase 6 work. It is not part of the current Phase 5 runtime.

## Start here

1. Read [docs/architecture.md](docs/architecture.md).
2. Follow the active roadmap in [docs/solo-full-poc-plan.md](docs/solo-full-poc-plan.md).
3. Resolve Entra choices in [docs/entra-identity.md](docs/entra-identity.md).
4. Select and verify gateways using [docs/gateway-routing.md](docs/gateway-routing.md).
5. Use [docs/testing.md](docs/testing.md) as the evidence checklist.
6. Give GitHub Copilot the kickoff prompt below, then use the phase prompts in `.github/prompts/` one phase at a time.

## Active plan and current phase

Use [docs/solo-full-poc-plan.md](docs/solo-full-poc-plan.md) as the active roadmap for the project.

Completed:

- Phase 0: Identity and gateway validation
- Phase 1: Solo API edge
- Phase 2: Solo A2A gateway and Entra OBO
- Phase 3: Solo MCP gateway and banking mock server
- Phase 4: Google ADK agents with local Ollama

Current phase:

- Phase 5: Jupyter end-to-end Solo demonstration (COMPLETE)

Phase 5 slice status:

- Slice 5A: COMPLETE (read-only end-to-end stability gate passed; validated evidence remains read-only)
- Slice 5B: COMPLETE — guarded live read-only validation and local Gradio notebook are proven
- Slice 5C: COMPLETE — Per-User Read/Write Authorization (live evidence: `evidence/phase-5/slice-5c-two-user-authorization-20261015T015546Z.json`)
- Slice 5D: NEXT / PLANNED — OpenTelemetry and Arize Phoenix telemetry (not implemented or verified)

Remaining:

- Phase 6: PLANNED — FastMCP-compatible Banking MCP conversion and MACAW policy enforcement, with separate validation gates and no acceleration into Slice 5C.

The historical Kong work remains in the repository as reference material only and is not part of the active runtime architecture.

## Phase 5 Slice 5C: Per-User Read/Write Authorization

Slice 5C extends the proven read-only Phase 5 flow with deterministic, per-user authorization and controlled banking transfers. The implementation, synthetic gates and the guarded two-user live gate have passed; the sanitized evidence is recorded under `evidence/phase-5/`.

The active architecture remains:

```text
User/Gradio → Token A → Agent A → OBO Token B → Agent B → OBO Token C → agentgateway MCP policy → Banking MCP
```

The same delegated user must remain identifiable across Token A, Token B, and Token C and must be anchored to validated `tid` and `oid` values. Authorization decisions are made from the validated Entra tokens and deterministic gateway/Banking MCP policy, not from the UI, prompt text, email address, or `preferred_username`.

### Two-user POC model

The POC uses two independent Microsoft Entra test identities, documented only as aliases and never as real identities or secrets:

| Test identity | Banking.Reader | Banking.Writer | Read balance | Create transfer |
|---|---:|---:|---:|---:|
| `poc-banking-reader` | Yes | No | Allowed | Denied |
| `poc-banking-writer` | Yes | Yes | Allowed | Allowed with additional controls |

- `poc-banking-reader` is assigned the `Banking.Reader` app role only; it does not receive `Banking.Writer`.
- `poc-banking-writer` is assigned both `Banking.Reader` and `Banking.Writer`.
- Both users authenticate separately and complete independent Token A → Token B → Token C OBO flows.
- Token C must include the required delegated scope and the user’s Banking MCP app role(s).
- The two users must have distinct `oid` values while sharing the configured POC tenant `tid`.

### Slice 5C Entra authorization model

The Banking MCP API defines the following app roles for this POC:

- `Banking.Reader`
- `Banking.Writer`

The roles are assigned through the Banking MCP enterprise application. The current POC user will be assigned both roles in the writer configuration; the reader-only identity is assigned only `Banking.Reader`. The role assignment is not tenant-wide by default and is not inferred from the UI or natural-language intent.

Read authorization is planned to require all of the following:

- valid Token C
- expected issuer, tenant, audience, and authorized client
- delegated scope `Banking.Read`
- app role `Banking.Reader` or `Banking.Writer`
- valid `tid` and `oid`
- ownership of the requested account

Transfer authorization is planned to require all of the following:

- valid Token C
- expected issuer, tenant, audience, and authorized client
- delegated scope `Banking.Write`
- app role `Banking.Writer`
- valid `tid` and `oid`
- source and destination ownership validation
- explicit confirmation
- positive, valid transfer amount
- caller-supplied idempotency key

`Banking.Writer` does not bypass identity, ownership, confirmation, amount, or idempotency validation.

The planned enforcement boundaries are:

1. The Gradio/Jupyter UI may present the next operation, but UI visibility is never an authorization decision.
2. Agent A may orchestrate or classify the request, but it must not grant access.
3. Agent B may select the Banking MCP operation, but it must not grant access.
4. The unified agentgateway must evaluate validated Token C claims before it forwards the MCP request.
5. A reader must not be allowed to discover or invoke `create_transfer`.
6. Banking MCP must independently repeat the claim, role, ownership, confirmation, and idempotency checks as defense in depth.
7. Banking MCP must reject unauthorized writes even if the gateway is bypassed or incorrectly configured.
8. Missing, malformed, or invalid authorization inputs fail closed.

### Controlled transfer requirements

The planned write path includes the following controls:

- source and destination accounts must belong to the validated user’s `tid` and `oid`
- confirmation must be explicit and structured
- conversational wording alone must not count as confirmation
- amount must be positive and valid
- every transfer must include a caller-supplied idempotency key
- reusing the same idempotency key for the same request must not create a duplicate mutation
- conflicting reuse of an idempotency key must fail closed
- denied reader and denied-write attempts produce zero mutations
- unauthorized tool invocation is rejected before business-state mutation

### Security and logging requirements

- never log access tokens, client secrets, authorization headers, or complete JWT payloads
- never include token contents in prompts, model input, responses, notebooks, or evidence
- preserve flow IDs without treating them as authorization data
- raw identity debug logging remains POC-only and must remain disabled by default
- raw identity logging may be enabled only when `POC_LOG_RAW_USER_ID=true`
- committed live evidence should use sanitized or hashed identity references

### Implementation status

Implemented locally:

- Token C OBO requests the single Banking `/.default` scope; the Reader must hold `Banking.Read`, the Writer `Banking.Read` and `Banking.Write`
- unified agentgateway read/write scope-and-role policy
- role-filtered MCP tool discovery and defense-in-depth direct-call checks
- per-user account ownership, confirmation, positive-amount, and idempotency enforcement
- Agent B `create_transfer` support and Agent A banking delegation
- a separate Slice 5C Gradio chat notebook with user switching and staged `CONFIRM`/`CANCEL` transfer handling
- focused contract and synthetic integration coverage
- a safe-by-default two-user guarded live runner

Live validation result (2026-10-15 UTC, branch `phase-5-e2e-solo`):

- `live_slice5c_two_user.py --live` passed once with independent Reader and Writer sign-ins in the same tenant
- authorization model: Entra scopes plus app roles; roles (`Banking.Reader`, `Banking.Writer`) are the per-user write boundary, and the Reader may carry the `Banking.Write` delegated scope under tenant-wide consent
- Token A, Token B and Token C preserved the same delegated user and tenant for each identity
- tool discovery is filtered: the Reader sees only `get_account_summary`, the Writer sees `get_account_summary` and `create_transfer`
- account ownership, explicit confirmation, a caller-supplied idempotency key and a positive amount are enforced; identical replay added no mutation and a conflicting replay was denied
- exactly one authorized transfer mutation; denied requests produced no mutation
- evidence: `evidence/phase-5/slice-5c-two-user-authorization-20261015T015546Z.json`; tests: 92 focused and 23 unified regression tests passed
- logs and evidence carry pseudonymous identity references only, never tokens, secrets, authorization headers or raw identifiers
- not claimed: telemetry (Slice 5D), MACAW or FastMCP (Phase 6), production readiness

The deliberate design remains to keep Phase 6 responsible for MACAW and FastMCP changes separately from Slice 5C.

### Slice 5C acceptance gates

Slice 5C is not complete until all of the following gates pass and are recorded in `evidence/phase-5/`:

Reader-user gates:

1. `poc-banking-reader` signs in independently through Microsoft Entra.
2. Token A, Token B, and Token C preserve the reader’s expected `tid` and `oid`.
3. Token C contains `Banking.Read`.
4. Token C contains `Banking.Reader`.
5. Token C does not contain `Banking.Writer`.
6. The reader can call `get_account_summary` for an owned account.
7. The reader cannot discover `create_transfer`.
8. The reader cannot invoke `create_transfer` directly.
9. A reader transfer attempt is rejected before Banking MCP mutation.
10. Reader validation produces zero transfer mutations.

Writer-user gates:

11. `poc-banking-writer` signs in independently through Microsoft Entra.
12. Token A, Token B, and Token C preserve the writer’s expected `tid` and `oid`.
13. Token C contains `Banking.Read` and `Banking.Write`.
14. Token C contains `Banking.Reader` and `Banking.Writer`.
15. The writer can call `get_account_summary` for an owned account.
16. The writer can discover `create_transfer`.
17. The writer can perform one explicitly confirmed transfer between owned accounts.
18. The successful transfer produces exactly one mutation.
19. Repeating the same request with the same idempotency key does not create a second mutation.
20. A conflicting request using the same idempotency key fails closed.
21. A transfer without explicit confirmation is rejected.
22. A transfer without an idempotency key is rejected.
23. A transfer with an invalid or non-positive amount is rejected.
24. A transfer involving an account not owned by the writer is rejected without mutation.

Cross-user and security gates:

25. The reader and writer have distinct `oid` values.
26. One user cannot read or mutate the other user’s accounts.
27. Authentication state and delegated-token context do not leak between users.
28. Testing the second user must not silently reuse the first user’s cached login.
29. Missing `Banking.Read`, `Banking.Write`, `Banking.Reader`, or `Banking.Writer` fails according to the operation’s policy.
30. Invalid issuer, tenant, audience, authorized client, lifetime, or signature fails closed.
31. No raw token, secret, authorization header, or complete JWT payload appears in logs or evidence.
32. Denied requests produce no business-state mutation.
33. The same flow ID is propagated through the allowed request path without being used as authorization.
34. Temporary Docker resources are removed after validation.
35. Both users’ guarded live results are recorded under `evidence/phase-5/`.
36. Phase 5 is not marked complete until all required Slice 5C gates pass.

### Guarded live validation sequence

The required live validation path is:

1. Start from a clean authentication state.
2. Sign in as `poc-banking-reader`.
3. Prove an owned-account balance read succeeds.
4. Prove transfer discovery or invocation is denied.
5. Prove all transfer mutation counters remain zero.
6. Clear the device-login/MSAL cache or otherwise force an independent second login.
7. Sign in as `poc-banking-writer`.
8. Prove an owned-account balance read succeeds.
9. Perform one explicitly confirmed transfer between owned accounts.
10. Prove exactly one mutation occurred.
11. Repeat the request with the same idempotency key.
12. Prove no duplicate mutation occurred.
13. Attempt a transfer involving an unowned account.
14. Prove the ownership denial produces no additional mutation.
15. Inspect sanitized cross-service flow evidence.
16. Tear down all temporary Docker resources.
17. Record evidence only after both user paths pass.

Run the guarded two-user gate only when the local `.env`, external secret files, Entra assignments, Ollama, and Docker prerequisites are ready:

```bash
PYTHONPATH="$PWD" uv run python \
  experiments/solo-agentgateway/unified/live_slice5c_two_user.py \
  --live
```

The runner is safe by default without `--live`. It forces two independent device-code flows, derives the account-owner map from the validated users' `oid` claims, prints only pseudonymous identity references, and tears down its Docker project.

For the manual Gradio demonstration, set `BANKING_ACCOUNT_OWNERS_JSON` in the local untracked `.env`, start the persistent live stack, then open `notebooks/phase-5-slice-5c-gradio-user-authorization.ipynb` and run both cells:

```bash
PYTHONPATH="$PWD" uv run python \
  experiments/solo-agentgateway/unified/live_unified_obo.py \
  --start-only
```

Stop it afterward with the same command using `--stop`. The historical Slice 5B notebook remains unchanged.

### Evidence requirements

Slice 5C evidence under `evidence/phase-5/` includes:

- timestamp
- tested commit
- sanitized configuration summary
- reader-user outcome
- writer-user outcome
- distinct sanitized identity references
- required scopes and roles observed
- read result
- transfer result
- denial results
- mutation counters
- idempotency result
- ownership-denial result
- cleanup result
- exact test commands
- exact test outcomes

The evidence will be created only after the guarded validation gates pass. Local implementation and synthetic test results are not substitutes for live evidence.

The current read-only Phase 5 evidence remains valid and should not be reinterpreted as write-capable evidence.

## Exact Copilot kickoff prompt

Copy this text exactly into GitHub Copilot Chat from the repository root:

```text
Read README.md, docs/solo-full-poc-plan.md, docs/architecture.md, docs/testing.md, and .github/copilot-instructions.md before proposing changes. Treat the all-Solo architecture as the active POC path. Follow the active roadmap in docs/solo-full-poc-plan.md and focus on the next phase: Phase 5, the Jupyter end-to-end Solo demonstration. Preserve the historical Kong material as reference only; do not restart Phase 0 or re-open the Kong investigation as an active task. Keep the security and evidence guardrails in place: no real credentials, no raw tokens, no personal identity claims, no live Entra calls or live docker execution during planning, and no unsupported production claims. Do not generate implementation code for phases outside the selected task. End with the assumptions, decisions, files to change, evidence needed for the next gate, and any remaining risks.
```

The same prompt is stored in `.github/prompts/plan-project.prompt.md`.

## macOS and Docker networking

Use these conventions consistently during implementation:

- A process running in Docker Desktop reaches a service on the Mac host through `host.docker.internal`, not `localhost`.
- A Mac-host process reaches an exposed container port through `localhost:<published-port>`.
- Containers on the same user-defined Docker network should use their Compose service names.
- Bind host services intentionally. If a service must be reached from Docker, confirm its bind address and firewall exposure; do not casually expose it to the LAN.
- Never place an Entra client secret in a notebook, Git-tracked file, Docker image, or command transcript.

See [docs/gateway-routing.md](docs/gateway-routing.md) for the complete routing matrix.

## Repository map

```text
docs/                         Architecture, identity, routing, plan, and test guidance
.github/copilot-instructions.md
.github/prompts/              Planning prompt plus one prompt per delivery phase
notebooks/                    Future notebook client
infra/kong/                   Historical Kong reference assets
infra/agent-gateway-a2a/      Future A2A gateway assets
infra/agent-gateway-mcp/      Future MCP gateway assets
agents/agent-a/               Future ADK Agent A
agents/agent-b/               Future ADK Agent B
mcp/banking-mock/             Future MCP banking mock server
tests/                        Future contract, identity, integration, and security tests
evidence/                     Future redacted proof collected at each gate
scripts/                      Future local developer helpers
```

The repository retains historical reference material for the earlier Kong path and the active Solo implementation plan for the current POC direction.

## Definition of a safe POC

The POC is successful only when its evidence shows both allowed and denied paths, correlation across hops, correct delegation semantics, tool-level authorization for reads and writes, and no token or secret leakage. A demo that merely returns a successful banking response is insufficient.
