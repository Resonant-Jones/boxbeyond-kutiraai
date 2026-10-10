"""Offline learning of reviewable skills from agent execution records.

This package deliberately stops at candidate generation. It does not train model
weights, ingest history directories, or execute generated skills.
"""

from .execution_record import ExecutionEvent, ExecutionRecord, SourceRef
from .extractor import (
    CandidateSkill,
    SourceSelection,
    extract_skill_candidates,
)

__all__ = [
    "CandidateSkill",
    "ExecutionEvent",
    "ExecutionRecord",
    "SourceRef",
    "SourceSelection",
    "extract_skill_candidates",
]
