"""CLI compatibility re-export for the runtime instance implementation."""

from cruxible_core.runtime import instance as _runtime_instance
from cruxible_core.runtime.instance import CruxibleInstance

# Preserve legacy patch targets like cruxible_core.cli.instance.json.dump.
json = _runtime_instance.json

__all__ = ["CruxibleInstance"]
