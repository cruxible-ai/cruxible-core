"""HTTP auth helpers for the Cruxible server."""

from __future__ import annotations

import contextvars
import hmac
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse

from cruxible_core.errors import AuthenticationError
from cruxible_core.mcp.permissions import PermissionMode, request_permission_scope
from cruxible_core.server.auth_store import DeploySessionRecord, RuntimeKeyRecord, get_auth_store
from cruxible_core.server.config import (
    get_bootstrap_audience,
    get_bootstrap_issuer,
    get_bootstrap_jwks_url,
    get_bootstrap_public_key,
    get_server_token,
    is_server_auth_enabled,
)
from cruxible_core.server.errors import ErrorResponse

_AUTH_CONTEXT: contextvars.ContextVar["ResolvedAuthContext | None"] = contextvars.ContextVar(
    "cruxible_auth_context",
    default=None,
)
_jwks_client: jwt.PyJWKClient | None = None


@dataclass(frozen=True)
class ResolvedAuthContext:
    principal_id: str
    principal_label: str
    credential_type: str
    operation_id: str | None
    instance_scope: str | None
    role: str | None
    effective_permission_mode: PermissionMode | None
    created_by: str | None = None
    system_id: str | None = None
    actions: list[str] = field(default_factory=list)
    bootstrap_jti: str | None = None
    bootstrap_expires_at: datetime | None = None


def get_current_auth_context() -> ResolvedAuthContext | None:
    """Return the current request-scoped auth context, if any."""
    return _AUTH_CONTEXT.get()


def _unauthorized_response(message: str = "Unauthorized") -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content=ErrorResponse(
            error_type="AuthenticationError",
            message=message,
        ).model_dump(mode="json"),
    )


def _role_to_mode(role: str) -> PermissionMode:
    mapping = {
        "viewer": PermissionMode.READ_ONLY,
        "editor": PermissionMode.GOVERNED_WRITE,
        "admin": PermissionMode.ADMIN,
    }
    return mapping.get(role, PermissionMode.READ_ONLY)


def _runtime_key_context(record: RuntimeKeyRecord) -> ResolvedAuthContext:
    return ResolvedAuthContext(
        principal_id=record.key_id,
        principal_label=record.subject_label,
        credential_type="runtime_api_key",
        operation_id=None,
        instance_scope=record.instance_scope,
        role=record.role,
        effective_permission_mode=_role_to_mode(record.role),
        created_by=record.created_by,
    )


def _decode_bootstrap_jwt(token: str) -> dict[str, Any] | None:
    public_key = get_bootstrap_public_key()
    jwks_url = get_bootstrap_jwks_url()
    issuer = get_bootstrap_issuer()
    audience = get_bootstrap_audience()

    if public_key is None and jwks_url is None:
        return None

    try:
        if public_key is not None:
            return jwt.decode(
                token,
                public_key,
                algorithms=["RS256", "ES256", "EdDSA"],
                audience=audience,
                issuer=issuer,
            )

        global _jwks_client
        if _jwks_client is None:
            assert jwks_url is not None
            _jwks_client = jwt.PyJWKClient(jwks_url)
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256", "EdDSA"],
            audience=audience,
            issuer=issuer,
        )
    except jwt.PyJWTError:
        return None


def _deploy_session_context(record: DeploySessionRecord) -> ResolvedAuthContext:
    return ResolvedAuthContext(
        principal_id=record.session_id,
        principal_label=f"deploy_session:{record.operation_id}",
        credential_type="deploy_session",
        operation_id=record.operation_id,
        instance_scope=None,
        role=None,
        effective_permission_mode=None,
        created_by=record.principal_id,
        system_id=record.system_id,
        actions=record.actions,
    )


def _bootstrap_context(token: str) -> ResolvedAuthContext | None:
    claims = _decode_bootstrap_jwt(token)
    if claims is None or claims.get("kind") != "bootstrap":
        return None

    exp_value = claims.get("exp")
    jti = claims.get("jti")
    system_id = claims.get("system_id")
    org_id = claims.get("org_id")
    actions_raw = claims.get("actions", [])
    if not isinstance(exp_value, (int, float)) or not isinstance(jti, str):
        return None
    if not isinstance(system_id, str) or not isinstance(org_id, str):
        return None
    if isinstance(actions_raw, list) and all(isinstance(item, str) for item in actions_raw):
        actions = list(actions_raw)
    else:
        actions = []

    expires_at = datetime.fromtimestamp(float(exp_value), tz=UTC)

    return ResolvedAuthContext(
        principal_id=jti,
        principal_label=f"bootstrap:{system_id}",
        credential_type="bootstrap_jwt",
        operation_id=None,
        instance_scope=None,
        role="admin",
        effective_permission_mode=PermissionMode.ADMIN,
        created_by=f"bootstrap:{system_id}",
        system_id=system_id,
        actions=actions,
        bootstrap_jti=jti,
        bootstrap_expires_at=expires_at,
    )


@contextmanager
def _auth_context_scope(
    context: ResolvedAuthContext | None,
) -> Any:
    token = _AUTH_CONTEXT.set(context)
    try:
        yield
    finally:
        _AUTH_CONTEXT.reset(token)


def require_bootstrap_or_admin_auth(*, system_id: str | None = None) -> ResolvedAuthContext:
    """Require either a bootstrap JWT or an admin runtime credential."""
    context = get_current_auth_context()
    if context is None:
        raise AuthenticationError("Deploy route requires bootstrap or admin authentication")
    if context.credential_type == "bootstrap_jwt":
        if system_id is not None and context.system_id != system_id:
            raise AuthenticationError("Bootstrap token is not valid for this system")
        if not set(context.actions).intersection({"bootstrap", "admin"}):
            raise AuthenticationError("Bootstrap token does not permit deploy bootstrap actions")
        return context
    if context.credential_type == "runtime_api_key" and context.role == "admin":
        return context
    if context.credential_type == "legacy_server_token":
        return context
    raise AuthenticationError("Deploy route requires bootstrap or admin authentication")


def require_deploy_session(operation_id: str, action: str) -> ResolvedAuthContext:
    """Require a deploy-session credential scoped to a specific operation/action."""
    context = get_current_auth_context()
    if context is None or context.credential_type != "deploy_session":
        raise AuthenticationError("Deploy session credential required")
    if context.operation_id != operation_id:
        raise AuthenticationError("Deploy session is not valid for this operation")
    if action not in set(context.actions):
        raise AuthenticationError("Deploy session does not permit this action")
    return context


def require_admin_runtime_auth() -> ResolvedAuthContext:
    """Require an admin-scoped runtime credential for key-management routes."""
    context = get_current_auth_context()
    if context is None:
        raise AuthenticationError("Admin runtime credential required")
    if context.credential_type == "runtime_api_key" and context.role == "admin":
        return context
    raise AuthenticationError("Admin runtime credential required")


async def token_auth_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Any]],
) -> Any:
    """Resolve auth context and request-scoped permission mode for incoming requests."""
    if request.url.path in {"/health", "/version"}:
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    bearer_token: str | None = None
    if auth_header:
        prefix = "Bearer "
        if not auth_header.startswith(prefix):
            return _unauthorized_response()
        bearer_token = auth_header[len(prefix) :].strip()
        if not bearer_token:
            return _unauthorized_response()

    resolved_context: ResolvedAuthContext | None = None

    if bearer_token is not None:
        runtime_record = get_auth_store().resolve_runtime_key(bearer_token)
        if runtime_record is not None:
            resolved_context = _runtime_key_context(runtime_record)
        else:
            deploy_session = get_auth_store().resolve_deploy_session_token(bearer_token)
            if deploy_session is not None:
                resolved_context = _deploy_session_context(deploy_session)
            else:
                resolved_context = _bootstrap_context(bearer_token)
        if resolved_context is None:
            legacy = get_server_token()
            if legacy and hmac.compare_digest(bearer_token, legacy):
                resolved_context = ResolvedAuthContext(
                    principal_id="legacy_server_token",
                    principal_label="legacy_server_token",
                    credential_type="legacy_server_token",
                    operation_id=None,
                    instance_scope=None,
                    role="admin",
                    effective_permission_mode=None,
                    created_by="legacy_server_token",
                )
            else:
                return _unauthorized_response()

    if resolved_context is None and is_server_auth_enabled():
        return _unauthorized_response()

    with _auth_context_scope(resolved_context):
        if resolved_context is not None and resolved_context.effective_permission_mode is not None:
            with request_permission_scope(resolved_context.effective_permission_mode):
                return await call_next(request)
        return await call_next(request)
