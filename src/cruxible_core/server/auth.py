"""HTTP auth helpers for the Cruxible server."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from cruxible_core.server.config import get_server_token, is_server_auth_enabled
from cruxible_core.server.errors import ErrorResponse


async def token_auth_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Any]],
) -> Any:
    """Optionally enforce bearer-token auth on incoming requests."""
    if not is_server_auth_enabled():
        return await call_next(request)

    token = get_server_token()
    auth_header = request.headers.get("Authorization", "")
    expected = f"Bearer {token}" if token else None
    if expected is None or auth_header != expected:
        return JSONResponse(
            status_code=401,
            content=ErrorResponse(
                error_type="CoreError",
                message="Unauthorized",
            ).model_dump(mode="json"),
        )

    return await call_next(request)
