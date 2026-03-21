"""Provider registry for import-string provider refs."""

from __future__ import annotations

import importlib

from cruxible_core.config.schema import ProviderSchema
from cruxible_core.errors import ConfigError
from cruxible_core.provider.types import ProviderCallable


def resolve_provider(provider_name: str, provider: ProviderSchema) -> ProviderCallable:
    """Resolve a provider ref to a Python callable."""
    if provider.runtime != "python":
        raise ConfigError(
            f"Provider '{provider_name}' uses unsupported runtime '{provider.runtime}'. "
            "Only runtime 'python' is supported in v1."
        )

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
