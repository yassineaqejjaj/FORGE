"""Feedback reports (docs/ARCHITECTURE.md §7.7): deterministic builder for a run or a set of runs."""

from forge.domain.feedback.builder import (
    DETERMINISTIC,
    FeedbackCriterion,
    FeedbackError,
    FeedbackInput,
    build_feedback,
    build_group_feedback,
    feedback_criteria,
    group_errors,
)

__all__ = [
    "DETERMINISTIC",
    "FeedbackCriterion",
    "FeedbackError",
    "FeedbackInput",
    "build_feedback",
    "build_group_feedback",
    "feedback_criteria",
    "group_errors",
]
