"""Portable, provider-neutral execution records.

The format is intentionally richer than KutiraAI's existing task trace. A
record can describe tool calls, decisions, errors, validation evidence, and
authorization context without requiring a model provider or a live database.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "1.0"
EVENT_TYPES = {
    "tool_call",
    "decision",
    "observation",
    "error",
    "validation",
    "completion",
}
RECORD_STATUSES = {"success", "failed", "unknown"}


@dataclass(frozen=True)
class SourceRef:
    """A provenance pointer selected by the caller, not discovered implicitly."""

    kind: str
    locator: str
    content_hash: Optional[str] = None

    def validate(self) -> None:
        if not self.kind or not self.locator:
            raise ValueError("source kind and locator are required")


@dataclass(frozen=True)
class ExecutionEvent:
    """One ordered event in an agent execution."""

    sequence: int
    event_type: str
    name: str
    tool: Optional[str] = None
    inputs: Any = None
    outputs: Any = None
    decision: Optional[str] = None
    error: Optional[str] = None
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    authorization: Optional[Dict[str, Any]] = None

    def validate(self) -> None:
        if self.sequence < 0:
            raise ValueError("event sequence must be non-negative")
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"unsupported event type: {self.event_type}")
        if not self.name:
            raise ValueError("event name is required")
        if self.event_type == "tool_call" and not self.tool:
            raise ValueError("tool_call events require a tool")
        if self.event_type == "error" and not self.error:
            raise ValueError("error events require an error message")


@dataclass(frozen=True)
class ExecutionRecord:
    """A complete, portable account of one selected execution."""

    record_id: str
    source: SourceRef
    workflow_name: str
    trigger: str
    status: str
    events: List[ExecutionEvent]
    completion_evidence: List[Dict[str, Any]] = field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema version: {self.schema_version}")
        if not self.record_id or not self.workflow_name or not self.trigger:
            raise ValueError("record_id, workflow_name, and trigger are required")
        if self.status not in RECORD_STATUSES:
            raise ValueError(f"unsupported record status: {self.status}")
        self.source.validate()
        sequences = []
        for event in self.events:
            event.validate()
            sequences.append(event.sequence)
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("events must have unique, ordered sequence numbers")

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ExecutionRecord":
        source = SourceRef(**payload["source"])
        events = [ExecutionEvent(**event) for event in payload.get("events", [])]
        record = cls(
            record_id=payload["record_id"],
            source=source,
            workflow_name=payload["workflow_name"],
            trigger=payload["trigger"],
            status=payload["status"],
            events=events,
            completion_evidence=payload.get("completion_evidence", []),
            started_at=payload.get("started_at"),
            completed_at=payload.get("completed_at"),
            metadata=payload.get("metadata", {}),
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
        )
        record.validate()
        return record
