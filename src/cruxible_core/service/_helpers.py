"""Internal helpers shared across service modules."""

from __future__ import annotations

import hashlib

import structlog

from cruxible_core.config.schema import CoreConfig
from cruxible_core.errors import CoreError, MutationError
from cruxible_core.graph.entity_graph import EntityGraph
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.receipt.types import Receipt

logger = structlog.get_logger()


def _persist_receipt(instance: InstanceProtocol, receipt: Receipt) -> bool:
    """Best-effort receipt persistence. Returns True if saved."""
    store = instance.get_receipt_store()
    try:
        store.save_receipt(receipt)
        return True
    except Exception:
        logger.warning("Failed to persist receipt %s", receipt.receipt_id, exc_info=True)
        return False
    finally:
        store.close()


def _save_graph(instance: InstanceProtocol, graph: EntityGraph) -> None:
    """Save graph, wrapping non-CoreError failures so mutation_receipt_id flows."""
    try:
        instance.save_graph(graph)
    except CoreError:
        raise
    except Exception as exc:
        raise MutationError(f"Failed to save graph: {exc}") from exc


def _config_digest(config: CoreConfig) -> str:
    """SHA-256 digest of config JSON (first 12 hex chars)."""
    return hashlib.sha256(config.model_dump_json(exclude_none=True).encode()).hexdigest()[:12]
