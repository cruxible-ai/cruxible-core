""".cruxible/ directory management and graph serialization.

Manages the local instance directory structure:
    .cruxible/
        instance.json   - metadata (config path, data dir, version)
        graph.json      - networkx node_link_data JSON
        receipts.db     - SQLite for receipts
        feedback.db     - SQLite for feedback + outcomes
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cruxible_core import __version__
from cruxible_core.config.loader import load_config, save_config
from cruxible_core.config.schema import CoreConfig
from cruxible_core.errors import InstanceNotFoundError
from cruxible_core.feedback.store import FeedbackStore
from cruxible_core.graph.entity_graph import EntityGraph
from cruxible_core.storage.sqlite import SQLiteStore

logger = logging.getLogger(__name__)


class CruxibleInstance:
    """Manages a .cruxible/ project instance."""

    INSTANCE_DIR = ".cruxible"

    def __init__(self, root: Path, metadata: dict[str, Any]) -> None:
        self.root = root
        self.instance_dir = root / self.INSTANCE_DIR
        self.metadata = metadata
        self._graph_cache: EntityGraph | None = None

    @classmethod
    def init(
        cls,
        root: Path,
        config_path: str,
        data_dir: str | None = None,
    ) -> CruxibleInstance:
        """Initialize a new .cruxible/ instance directory.

        Validates the config file exists and is loadable before creating
        the instance directory.
        """
        # Resolve config path relative to root
        resolved_config = Path(config_path)
        if not resolved_config.is_absolute():
            resolved_config = root / resolved_config

        # Validate config is loadable
        load_config(resolved_config)

        instance_dir = root / cls.INSTANCE_DIR
        instance_dir.mkdir(parents=True, exist_ok=True)

        metadata: dict[str, Any] = {
            "config_path": str(config_path),
            "data_dir": data_dir or ".",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "version": __version__,
        }
        (instance_dir / "instance.json").write_text(json.dumps(metadata, indent=2))

        # Initialize empty graph
        graph_data = EntityGraph().to_dict()
        (instance_dir / "graph.json").write_text(json.dumps(graph_data, indent=2))

        return cls(root, metadata)

    @classmethod
    def load(cls, root: Path | None = None) -> CruxibleInstance:
        """Load an existing instance, walking up from root (or cwd) to find .cruxible/."""
        if root is None:
            root = Path.cwd()

        search = root
        while True:
            candidate = search / cls.INSTANCE_DIR / "instance.json"
            if candidate.exists():
                metadata = json.loads(candidate.read_text())
                return cls(search, metadata)
            parent = search.parent
            if parent == search:
                break
            search = parent

        raise InstanceNotFoundError(f"No .cruxible/ directory found at or above {root}")

    def load_config(self) -> CoreConfig:
        """Load the CoreConfig from the stored config path."""
        config_path = Path(self.metadata["config_path"])
        if not config_path.is_absolute():
            config_path = self.root / config_path
        return load_config(config_path)

    def save_config(self, config: CoreConfig) -> None:
        """Save the CoreConfig back to the YAML file on disk."""
        config_path = Path(self.metadata["config_path"])
        if not config_path.is_absolute():
            config_path = self.root / config_path
        save_config(config, config_path)

    def load_graph(self) -> EntityGraph:
        """Load the entity graph from graph.json. Returns cached graph if available."""
        if self._graph_cache is not None:
            return self._graph_cache

        graph_path = self.instance_dir / "graph.json"
        if not graph_path.exists():
            logger.warning(
                "graph.json not found in %s — returning empty graph",
                self.instance_dir,
            )
            graph = EntityGraph()
        else:
            data = json.loads(graph_path.read_text())
            graph = EntityGraph.from_dict(data)

        self._graph_cache = graph
        return graph

    def save_graph(self, graph: EntityGraph) -> None:
        """Save the entity graph to graph.json and update the cache."""
        data = graph.to_dict()
        (self.instance_dir / "graph.json").write_text(json.dumps(data, indent=2))
        self._graph_cache = graph

    def invalidate_graph_cache(self) -> None:
        """Clear the in-memory graph cache, forcing next load_graph to read from disk."""
        self._graph_cache = None

    def get_receipt_store(self) -> SQLiteStore:
        """Get or create the receipt SQLite store."""
        return SQLiteStore(self.instance_dir / "receipts.db")

    def get_feedback_store(self) -> FeedbackStore:
        """Get or create the feedback SQLite store."""
        return FeedbackStore(self.instance_dir / "feedback.db")
