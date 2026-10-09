from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable
from urllib import request

import jwt

ALLOWED_TOKEN_VERSIONS = {"1.0", "2.0"}


class MetadataError(RuntimeError):
    """Raised when the tenant metadata document is missing required data."""


class UnsupportedTokenVersionError(ValueError):
    """Raised when a token advertises an unsupported OpenID version."""


class MissingScopeError(RuntimeError):
    """Raised when the expected scope is absent from a valid token."""


class TenantMismatchError(RuntimeError):
    """Raised when a token's tid does not match the configured tenant."""


class AuthorizedClientMismatchError(RuntimeError):
    """Raised when the authorized-client claim is missing or does not match the expected client."""


OpenIdConfigurationProvider = Callable[[str, str, int], dict[str, Any]]
JwksProvider = Callable[[str, int], dict[str, Any]]


def safe_error_category(exc: BaseException) -> str:
    if isinstance(exc, MetadataError):
        return "METADATA_FAILURE"
    if isinstance(exc, UnsupportedTokenVersionError):
        return "UNKNOWN_TOKEN_VERSION"
    if isinstance(exc, MissingScopeError):
        return "MISSING_SCOPE"
    if isinstance(exc, TenantMismatchError):
        return "TENANT_MISMATCH"
    if isinstance(exc, AuthorizedClientMismatchError):
        return "UNAUTHORIZED_CLIENT"
    if isinstance(exc, jwt.MissingRequiredClaimError):
        claim_name = exc.claim if isinstance(getattr(exc, "claim", None), str) else "required claim"
        if claim_name == "iss":
            return "MISSING_ISSUER"
        if claim_name == "tid":
            return "MISSING_TENANT"
        return "MISSING_REQUIRED_CLAIM"
    if isinstance(exc, jwt.InvalidSignatureError):
        return "INVALID_SIGNATURE"
    if isinstance(exc, jwt.InvalidAudienceError):
        return "INVALID_AUDIENCE"
    if isinstance(exc, jwt.InvalidIssuerError):
        return "INVALID_ISSUER"
    if isinstance(exc, jwt.ExpiredSignatureError):
        return "EXPIRED_TOKEN"
    if isinstance(exc, jwt.InvalidTokenError):
        return "MALFORMED_TOKEN"
    if isinstance(exc, RuntimeError):
        return "CONFIGURATION_ERROR"
    return "UNKNOWN_ERROR"


def sha256_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def extract_delegated_scope_name(scope_value: str) -> str:
    if scope_value is None:
        raise ValueError("Scope value is required.")
    normalized = str(scope_value).strip()
    if not normalized:
        raise ValueError("Scope value is empty.")
    if normalized.endswith("/.default"):
        raise ValueError("Delegated scope names must not use /.default.")
    if "/" in normalized:
        delegated = normalized.rsplit("/", 1)[1]
    else:
        delegated = normalized
    if not delegated or delegated in {".", ".default"}:
        raise ValueError("Scope value is malformed.")
    return delegated


def metadata_url_for_version(tenant_id: str, version: str) -> str:
    normalized = str(version or "").strip()
    if normalized == "1.0":
        return f"https://login.microsoftonline.com/{tenant_id}/.well-known/openid-configuration"
    if normalized == "2.0":
        return f"https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration"
    raise UnsupportedTokenVersionError(f"Unsupported token version: {normalized!r}.")


def fetch_json(url: str, *, timeout: int = 5) -> dict[str, Any]:
    try:
        with request.urlopen(url, timeout=timeout) as response:
            data = response.read().decode("utf-8")
        return json.loads(data)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        raise MetadataError("Metadata request failed.") from None


def fetch_openid_configuration(tenant_id: str, *, version: str, timeout: int = 5) -> dict[str, Any]:
    try:
        metadata_url = metadata_url_for_version(tenant_id, version)
        metadata = fetch_json(metadata_url, timeout=timeout)
    except MetadataError:
        raise
    except Exception:
        raise MetadataError("Metadata request failed.") from None
    if not isinstance(metadata, dict):
        raise MetadataError("Metadata document missing required fields.")
    if not metadata.get("issuer") or not metadata.get("jwks_uri"):
        raise MetadataError("Metadata document missing required fields.")
    return metadata


def fetch_jwks_document(jwks_uri: str, *, timeout: int = 5) -> dict[str, Any]:
    try:
        jwks = fetch_json(jwks_uri, timeout=timeout)
    except MetadataError:
        raise
    except Exception:
        raise MetadataError("JWKS request failed.") from None
    if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
        raise MetadataError("JWKS document missing signing keys.")
    return jwks


def validate_token_for_policy(
    token: str,
    *,
    tenant_id: str,
    expected_audience: str,
    expected_scope: str,
    expected_issuer: str,
    expected_authorized_client: str | None = None,
    test_name: str,
    openid_configuration_provider: OpenIdConfigurationProvider | None = None,
    jwks_provider: JwksProvider | None = None,
) -> dict[str, Any]:
    timestamp_utc = datetime.now(timezone.utc).isoformat()
    evidence = {
        "timestamp_utc": timestamp_utc,
        "token_version": "unknown",
        "token_fingerprint": sha256_fingerprint(token),
        "signature_verified": False,
        "issuer_verified": False,
        "tenant_verified": False,
        "audience_verified": False,
        "lifetime_verified": False,
        "scope_verified": False,
        "authorized_client_verified": False,
        "result": "FAIL",
        "test_name": test_name,
        "error_category": "UNKNOWN_ERROR",
    }

    metadata_provider = openid_configuration_provider or fetch_openid_configuration
    signing_key_provider = jwks_provider or fetch_jwks_document

    try:
        unverified_payload = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_aud": False,
                "verify_exp": False,
                "verify_nbf": False,
                "verify_iat": False,
                "verify_iss": False,
            },
        )
        version = str(unverified_payload.get("ver") or "")
        if version not in ALLOWED_TOKEN_VERSIONS:
            raise UnsupportedTokenVersionError(f"Unsupported token version: {version!r}.")
        evidence["token_version"] = version

        metadata = metadata_provider(tenant_id, version, 5)
        metadata_issuer = metadata.get("issuer")
        if not metadata_issuer:
            raise MetadataError("Metadata missing issuer.")
        if expected_issuer and expected_issuer != metadata_issuer:
            raise MetadataError("Expected issuer does not match tenant metadata issuer.")

        jwks_uri = metadata.get("jwks_uri")
        if not jwks_uri:
            raise MetadataError("Metadata missing jwks_uri.")
        jwks = signing_key_provider(jwks_uri, 5)

        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            raise MetadataError("Token header missing kid.")
        jwk = next((key for key in jwks.get("keys", []) if key.get("kid") == kid), None)
        if jwk is None:
            raise MetadataError("Signing key missing for token kid.")

        signing_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        decoded = jwt.decode(
            token,
            key=signing_key,
            algorithms=["RS256"],
            audience=expected_audience,
            issuer=metadata_issuer,
            options={
                "require": ["ver", "iss", "aud", "tid", "exp", "nbf", "iat"],
                "verify_signature": True,
                "verify_aud": True,
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iat": True,
                "verify_iss": True,
            },
        )
        evidence["signature_verified"] = True
        evidence["issuer_verified"] = decoded.get("iss") == metadata_issuer == expected_issuer
        evidence["tenant_verified"] = decoded.get("tid") == tenant_id
        evidence["audience_verified"] = decoded.get("aud") == expected_audience
        evidence["lifetime_verified"] = bool(decoded.get("exp") and decoded.get("nbf") and decoded.get("iat"))

        normalized_expected_scope = expected_scope
        try:
            normalized_expected_scope = extract_delegated_scope_name(expected_scope)
        except ValueError:
            normalized_expected_scope = str(expected_scope).strip() if expected_scope else ""
        scopes = set((decoded.get("scp") or "").split())
        evidence["scope_verified"] = normalized_expected_scope in scopes
        if not evidence["issuer_verified"]:
            raise jwt.InvalidIssuerError("Issuer mismatch.")
        if not evidence["tenant_verified"]:
            raise TenantMismatchError("Tenant mismatch.")
        if not evidence["audience_verified"]:
            raise jwt.InvalidAudienceError("Audience mismatch.")
        if not evidence["lifetime_verified"]:
            raise jwt.ExpiredSignatureError("Expired or invalid lifetime.")
        if not evidence["scope_verified"]:
            raise MissingScopeError("Missing required scope.")

        if expected_authorized_client is not None:
            claim_name = "azp" if version == "2.0" else "appid" if version == "1.0" else None
            if claim_name is None:
                raise UnsupportedTokenVersionError(f"Unsupported token version: {version!r}.")
            actual_authorized_client = decoded.get(claim_name)
            if actual_authorized_client is None or str(actual_authorized_client) != str(expected_authorized_client):
                raise AuthorizedClientMismatchError("Authorized client mismatch.")
            evidence["authorized_client_verified"] = True

        if (
            evidence["issuer_verified"]
            and evidence["tenant_verified"]
            and evidence["audience_verified"]
            and evidence["lifetime_verified"]
            and evidence["scope_verified"]
            and (expected_authorized_client is None or evidence["authorized_client_verified"])
        ):
            evidence["result"] = "PASS"
            evidence["error_category"] = "NONE"
    except Exception as exc:  # pragma: no cover - synthetic safety paths
        evidence["error_category"] = safe_error_category(exc)
        evidence["result"] = "FAIL"
        if isinstance(exc, jwt.InvalidAudienceError):
            evidence["audience_verified"] = False
        if isinstance(exc, jwt.InvalidIssuerError):
            evidence["issuer_verified"] = False
        if isinstance(exc, TenantMismatchError):
            evidence["tenant_verified"] = False
        if isinstance(exc, MissingScopeError):
            evidence["scope_verified"] = False
        if isinstance(exc, jwt.ExpiredSignatureError):
            evidence["lifetime_verified"] = False
        if isinstance(exc, AuthorizedClientMismatchError):
            evidence["authorized_client_verified"] = False
        if isinstance(exc, MetadataError):
            evidence["token_version"] = evidence.get("token_version", "unknown")
    return evidence


def resolve_expected_issuer(
    tenant_id: str,
    token: str,
    *,
    openid_configuration_provider: OpenIdConfigurationProvider | None = None,
) -> str:
    unverified_payload = jwt.decode(
        token,
        options={
            "verify_signature": False,
            "verify_aud": False,
            "verify_exp": False,
            "verify_nbf": False,
            "verify_iat": False,
            "verify_iss": False,
        },
    )
    version = str(unverified_payload.get("ver") or "")
    if version not in ALLOWED_TOKEN_VERSIONS:
        raise UnsupportedTokenVersionError(f"Unsupported token version: {version!r}.")
    metadata_provider = openid_configuration_provider or fetch_openid_configuration
    metadata = metadata_provider(tenant_id, version, 5)
    issuer = metadata.get("issuer")
    if not issuer:
        raise MetadataError("Metadata missing issuer.")
    return issuer


def summarize_live_validation(agent_a: dict[str, Any], agent_b: dict[str, Any], negative_result: dict[str, Any]) -> str:
    required_checks = [
        agent_a.get("result") == "PASS",
        agent_b.get("result") == "PASS",
        negative_result.get("expected_outcome") == "FAIL" and negative_result.get("actual_outcome") == "FAIL" and negative_result.get("pass") is True,
    ]
    return "PASS" if all(required_checks) else "FAIL"