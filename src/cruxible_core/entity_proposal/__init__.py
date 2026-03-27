"""Entity change proposal types and store."""

from cruxible_core.entity_proposal.store import EntityProposalStore
from cruxible_core.entity_proposal.types import EntityChangeMember, EntityChangeProposal

__all__ = [
    "EntityChangeMember",
    "EntityChangeProposal",
    "EntityProposalStore",
]
