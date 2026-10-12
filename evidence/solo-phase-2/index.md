# Solo Phase 2 evidence

Phase 2 is COMPLETE.

## Synthetic validation

The synthetic A2A/OBO validation established the route and policy boundary checks for locally generated JWTs, including:

- public Agent Card availability
- protected route enforcement
- exact audience and scope checks
- issuer, tenant, lifetime, and client validation
- fail-closed handling for malformed and invalid tokens
- backend-only counting of protected requests
- temporary config and JWKS generation under pytest-local storage

## Live local Entra validation

The local live Entra-backed validation passed for the full delegated path:

- device login
- Token A validation
- Agent A to Agent B OBO
- Token B validation
- delegated-user continuity
- Solo Agentgateway enforcement
- Agent B defense-in-depth validation
- Token A rejection at the Agent B boundary
- successful A2A delivery
- automatic Docker cleanup

Canonical evidence file: [solo-a2a-live-20261012T030839498195Z-7a4b163f60b4.json](solo-a2a-live-20261012T030839498195Z-7a4b163f60b4.json)

## Evidence rules

This evidence intentionally stores only sanitized pass/fail signals and metadata. Raw tokens, secrets, personal identity claims, usernames, email addresses, `oid`, `sub`, or other sensitive identity material are not stored in the repository.
