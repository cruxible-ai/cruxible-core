"""Provider runtime dispatch."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
from urllib.parse import urlparse

import httpx

from cruxible_core.config.schema import ProviderSchema
from cruxible_core.errors import ConfigError, QueryExecutionError
from cruxible_core.provider.types import ProviderCallable, ProviderContext


def resolve_provider(provider_name: str, provider: ProviderSchema) -> ProviderCallable:
    """Resolve a provider into an executable callable for its declared runtime."""
    if provider.runtime == "python":
        return _resolve_python_provider(provider_name, provider)
    if provider.runtime == "http_json":
        return _build_http_json_provider(provider_name, provider)
    if provider.runtime == "command":
        return _build_command_provider(provider_name, provider)

    raise ConfigError(
        f"Provider '{provider_name}' uses unsupported runtime '{provider.runtime}'. "
        "Supported runtimes are 'python', 'http_json', and 'command'."
    )


def _resolve_python_provider(provider_name: str, provider: ProviderSchema) -> ProviderCallable:
    ref = provider.ref
    module_name, sep, attr_name = ref.rpartition(".")
    if not sep:
        raise ConfigError(
            f"Provider '{provider_name}' has invalid ref '{ref}'. Use module.attr import path."
        )

    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover - exercised in tests
        raise ConfigError(
            f"Provider '{provider_name}' could not import module '{module_name}': {exc}"
        ) from exc

    try:
        candidate = getattr(module, attr_name)
    except AttributeError as exc:
        raise ConfigError(
            f"Provider '{provider_name}' ref '{ref}' does not resolve to an attribute"
        ) from exc

    if not callable(candidate):
        raise ConfigError(f"Provider '{provider_name}' ref '{ref}' is not callable")

    return candidate


def _build_http_json_provider(provider_name: str, provider: ProviderSchema) -> ProviderCallable:
    parsed = urlparse(provider.ref)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(
            f"Provider '{provider_name}' has invalid http_json ref '{provider.ref}'. "
            "Use a full http(s) URL."
        )

    headers = provider.config.get("headers", {})
    if not isinstance(headers, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in headers.items()
    ):
        raise ConfigError(f"Provider '{provider_name}' config.headers must be a string map")

    timeout_s = _coerce_timeout(provider_name, provider.config.get("timeout_s", 30))

    def _execute(input_payload: dict[str, object], _context: ProviderContext) -> dict[str, object]:
        try:
            with httpx.Client(timeout=timeout_s) as client:
                response = client.post(provider.ref, json=input_payload, headers=headers)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise QueryExecutionError(
                f"Provider '{provider_name}' http_json request timed out after {timeout_s}s"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise QueryExecutionError(
                f"Provider '{provider_name}' http_json request failed with status "
                f"{exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise QueryExecutionError(
                f"Provider '{provider_name}' http_json request failed: {exc}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise QueryExecutionError(
                f"Provider '{provider_name}' http_json response was not valid JSON"
            ) from exc

        if not isinstance(payload, dict):
            raise QueryExecutionError(
                f"Provider '{provider_name}' http_json response must be a JSON object"
            )
        return payload

    return _execute


def _build_command_provider(provider_name: str, provider: ProviderSchema) -> ProviderCallable:
    if not provider.ref.strip():
        raise ConfigError(f"Provider '{provider_name}' command ref must not be empty")

    args = provider.config.get("args", [])
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise ConfigError(f"Provider '{provider_name}' config.args must be a list of strings")

    extra_env = provider.config.get("env", {})
    if not isinstance(extra_env, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in extra_env.items()
    ):
        raise ConfigError(f"Provider '{provider_name}' config.env must be a string map")

    timeout_s = _coerce_timeout(provider_name, provider.config.get("timeout_s", 30))
    command = [provider.ref, *args]

    def _execute(input_payload: dict[str, object], _context: ProviderContext) -> dict[str, object]:
        try:
            completed = subprocess.run(
                command,
                input=json.dumps(input_payload),
                text=True,
                capture_output=True,
                timeout=timeout_s,
                env={**os.environ, **extra_env},
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise QueryExecutionError(
                f"Provider '{provider_name}' command timed out after {timeout_s}s"
            ) from exc
        except OSError as exc:
            raise QueryExecutionError(
                f"Provider '{provider_name}' command failed to start: {exc}"
            ) from exc

        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            detail = f": {stderr}" if stderr else ""
            raise QueryExecutionError(
                f"Provider '{provider_name}' command exited with status "
                f"{completed.returncode}{detail}"
            )

        try:
            payload = json.loads(completed.stdout)
        except ValueError as exc:
            raise QueryExecutionError(
                f"Provider '{provider_name}' command output was not valid JSON"
            ) from exc

        if not isinstance(payload, dict):
            raise QueryExecutionError(
                f"Provider '{provider_name}' command output must be a JSON object"
            )
        return payload

    return _execute


def _coerce_timeout(provider_name: str, value: object) -> float:
    try:
        timeout_s = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Provider '{provider_name}' timeout_s must be numeric") from exc
    if timeout_s <= 0:
        raise ConfigError(f"Provider '{provider_name}' timeout_s must be greater than zero")
    return timeout_s
