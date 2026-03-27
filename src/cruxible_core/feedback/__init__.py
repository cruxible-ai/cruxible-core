"""Feedback and outcome recording."""

from cruxible_core.feedback.applier import apply_feedback
from cruxible_core.feedback.store import FeedbackStore
from cruxible_core.feedback.types import (
    EdgeTarget,
    FeedbackBatchItem,
    FeedbackRecord,
    OutcomeRecord,
)

__all__ = [
    "EdgeTarget",
    "FeedbackBatchItem",
    "FeedbackRecord",
    "FeedbackStore",
    "OutcomeRecord",
    "apply_feedback",
]
