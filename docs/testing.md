# Testing and Evidence

Tests must prove denial behavior as well as the happy path. Record component versions, test timestamp, correlation ID, expected result, actual result, and redacted evidence.

## Test layers

1. **Contract:** token claims, A2A messages, MCP schemas, and banking tool inputs/outputs.
2. **Component:** each gateway, agent, token-exchange client, and mock server in isolation.
3. **Identity integration:** Entra issuance, validation, consent, claims challenges, and OBO.
4. **End to end:** notebook through all boundaries and back.
5. **Security:** bypass, injection, replay, cross-user access, excessive scope, and leakage.
6. **Resilience:** process/network failure, key rotation, timeouts, restarts, and ambiguous writes.

## Minimum identity matrix

| Case | Expected result |
|---|---|
| Valid A-audience user token with required A scope | Accepted at edge |
| No token / malformed token | Denied before Agent A |
| Expired / not-yet-valid token | Denied |
| Wrong issuer or tenant | Denied |
| Wrong audience | Denied |
| Missing required delegated scope | Denied |
| Unsupported algorithm or invalid signature | Denied |
| A token forwarded directly to B | Denied by B |
| Valid OBO B-audience token with required B scope | Accepted by B |
| App-only token where user delegation is required | Denied |
| Tampered identity header with otherwise invalid request | Denied |
| Entra metadata/key retrieval failure | Fails closed according to bounded cache policy |

## Minimum A2A and MCP matrix

| Case | Expected result |
|---|---|
| Allowed A caller to registered B operation | Accepted |
| Unknown target agent or operation | Denied |
| Unauthenticated, oversized, malformed, timed-out request | Denied or safely terminated |
| Authorized read for user's fake account | Exact least-privilege data returned |
| Cross-user account identifier | Denied without disclosing existence |
| Unknown MCP server/tool | Denied |
| Read-only user requests write | Denied |
| Write lacks confirmation or idempotency key | Denied |
| Valid confirmed write | Applied once and audited |
| Replay/retry of same write | No duplicate effect |
| Tool description/result contains hostile instructions | Treated as data; policy remains enforced |

## Network and bypass tests

- Confirm every intended route using the addressing matrix.
- Confirm a container cannot use its own `localhost` to reach a Mac-host service.
- Attempt direct access to Agent A, Agent B, and the banking mock from every relevant network location.
- Prove that protected operations cannot bypass their gateway/policy boundary.
- Check bind addresses and published ports; document why each exposure exists.
- Stop each gateway in turn and confirm the request fails closed.

## Observability checks

- One correlation ID is visible at every hop.
- Decisions identify the enforcing component and reason category.
- Authorization headers, complete JWTs, client secrets, refresh tokens, and sensitive payloads are absent from logs and traces.
- Subject identifiers are minimized or pseudonymized in evidence.
- Clock, component version, and configuration hash are captured.

## Evidence layout

```text
evidence/
  phase-0/
  phase-1/
  phase-2/
  phase-3/
  phase-4/
  phase-5/
```

Each phase should eventually contain a short index with commands or test IDs, sanitized results, source links, versions, hashes, decisions, and unresolved issues. Do not commit reusable tokens or secrets. `.gitkeep` files preserve the initial empty structure.

## Completion report

The final report must separate:

- Verified locally for a named version and configuration.
- Supported according to a linked primary source but not locally tested.
- Not supported.
- Unknown or deferred.

Macaw must remain listed as deferred, not accidentally described as evaluated.

