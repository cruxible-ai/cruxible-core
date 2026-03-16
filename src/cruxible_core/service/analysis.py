"""Analysis service functions — find_candidates, evaluate."""

from __future__ import annotations

from typing import Literal

from cruxible_core.errors import ConfigError
from cruxible_core.evaluate import EvaluationReport, evaluate_graph
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.query.candidates import CandidateMatch, MatchRule, find_candidates


def service_find_candidates(
    instance: InstanceProtocol,
    relationship_type: str,
    strategy: Literal["property_match", "shared_neighbors"],
    match_rules: list[MatchRule] | None = None,
    via_relationship: str | None = None,
    min_overlap: float = 0.5,
    min_confidence: float = 0.5,
    limit: int = 20,
    min_distinct_neighbors: int = 2,
) -> list[CandidateMatch]:
    """Find candidate relationships using a deterministic strategy."""
    _VALID_STRATEGIES = ("property_match", "shared_neighbors")
    if strategy not in _VALID_STRATEGIES:
        raise ConfigError(f"Invalid strategy '{strategy}'. Use: {', '.join(_VALID_STRATEGIES)}")

    if min_distinct_neighbors < 1:
        raise ConfigError("min_distinct_neighbors must be >= 1")

    config = instance.load_config()
    graph = instance.load_graph()

    return find_candidates(
        config,
        graph,
        relationship_type,
        strategy,
        match_rules=match_rules,
        via_relationship=via_relationship,
        min_overlap=min_overlap,
        min_confidence=min_confidence,
        limit=limit,
        min_distinct_neighbors=min_distinct_neighbors,
    )


def service_evaluate(
    instance: InstanceProtocol,
    confidence_threshold: float = 0.5,
    max_findings: int = 100,
    exclude_orphan_types: list[str] | None = None,
) -> EvaluationReport:
    """Evaluate graph quality with deterministic checks."""
    config = instance.load_config()
    graph = instance.load_graph()
    return evaluate_graph(
        config,
        graph,
        confidence_threshold=confidence_threshold,
        max_findings=max_findings,
        exclude_orphan_types=exclude_orphan_types,
    )
