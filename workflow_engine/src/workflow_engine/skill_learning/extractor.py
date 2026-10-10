"""Deterministic offline extraction of reviewable skill candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

from .execution_record import ExecutionRecord
from .redaction import redact_record_payload


@dataclass(frozen=True)
class SourceSelection:
    """The only records eligible for extraction in one run."""

    record_ids: Tuple[str, ...]
    allow_private_content: bool = False

    def validate(self) -> None:
        if not self.record_ids:
            raise ValueError("explicit source selection is required")
        if len(set(self.record_ids)) != len(self.record_ids):
            raise ValueError("source selection contains duplicate record IDs")


@dataclass(frozen=True)
class CandidateSkill:
    candidate_id: str
    name: str
    trigger: Dict[str, Any]
    required_tools: List[Dict[str, Any]]
    observed_steps: List[Dict[str, Any]]
    inferred_improvements: List[Dict[str, Any]]
    validation_criteria: List[Dict[str, Any]]
    provenance: Dict[str, Any]
    confidence: Dict[str, Any]
    approval_status: str = "pending"
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    executable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def approve(self, approver: str, approved_at: Optional[str] = None) -> "CandidateSkill":
        """Cross the human approval boundary explicitly."""

        if self.approval_status != "pending":
            raise ValueError("only pending candidates can be approved")
        if not approver.strip():
            raise ValueError("approver is required")
        timestamp = approved_at or datetime.now(timezone.utc).isoformat()
        return replace(
            self,
            approval_status="approved",
            approved_by=approver,
            approved_at=timestamp,
            executable=True,
        )


def _shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _shape(child) for key, child in sorted(value.items())}
    if isinstance(value, list):
        return ["list", len(value)]
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def _event_step(event: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "order": event["sequence"],
        "event_type": event["event_type"],
        "name": event["name"],
        "tool": event.get("tool"),
        "input_shape": _shape(event.get("inputs")),
        "output_shape": _shape(event.get("outputs")),
        "decision_present": bool(event.get("decision")),
        "authorization_present": bool(event.get("authorization")),
    }


def _validation_criteria(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    criteria: List[Dict[str, Any]] = []
    seen = set()
    for record in records:
        for evidence in record.get("completion_evidence", []):
            criterion = {
                "kind": evidence.get("kind", "completion_evidence"),
                "verified": bool(evidence.get("verified", True)),
                "source_record": record["record_id"],
            }
            marker = (criterion["kind"], criterion["verified"])
            if marker not in seen:
                seen.add(marker)
                criteria.append(criterion)
        for event in record.get("events", []):
            if event["event_type"] != "validation":
                continue
            criterion = {
                "kind": event["name"],
                "verified": True,
                "source_record": record["record_id"],
                "source_sequence": event["sequence"],
            }
            marker = (criterion["kind"], criterion["verified"])
            if marker not in seen:
                seen.add(marker)
                criteria.append(criterion)
    return criteria


def extract_skill_candidates(
    records: Iterable[ExecutionRecord],
    selection: SourceSelection,
    *,
    min_occurrences: int = 2,
) -> List[CandidateSkill]:
    """Extract recurring procedures from explicitly selected successful records.

    The extractor is intentionally conservative: it groups only identical
    ordered tool sequences and never treats inferred improvements as observed
    executable steps.
    """

    selection.validate()
    if min_occurrences < 1:
        raise ValueError("min_occurrences must be positive")

    records_by_id = {record.record_id: record for record in records}
    selected: List[ExecutionRecord] = []
    for record_id in selection.record_ids:
        if record_id not in records_by_id:
            raise KeyError(f"selected record not found: {record_id}")
        record = records_by_id[record_id]
        record.validate()
        if record.status == "success" and record.completion_evidence:
            selected.append(record)

    groups: Dict[Tuple[str, Tuple[str, ...]], List[Dict[str, Any]]] = {}
    for record in selected:
        redacted, findings = redact_record_payload(
            record.to_dict(),
            allow_private_content=selection.allow_private_content,
        )
        tool_events = [
            event for event in redacted["events"] if event["event_type"] == "tool_call"
        ]
        tool_sequence = tuple(event.get("tool") or event["name"] for event in tool_events)
        if not tool_sequence:
            continue
        key = (record.workflow_name, tool_sequence)
        groups.setdefault(key, []).append(
            {"record": redacted, "redaction_findings": findings}
        )

    candidates: List[CandidateSkill] = []
    for (workflow_name, tool_sequence), occurrences in groups.items():
        if len(occurrences) < min_occurrences:
            continue
        records_payload = [item["record"] for item in occurrences]
        first = records_payload[0]
        first_tool_events = [
            event for event in first["events"] if event["event_type"] == "tool_call"
        ]
        observed_steps = [
            _event_step(event)
            for event in first["events"]
            if event["event_type"] != "completion"
        ]
        required_tools = [
            {"name": tool, "observed_occurrences": len(occurrences)}
            for tool in dict.fromkeys(tool_sequence)
        ]
        all_events = [event for record in records_payload for event in record["events"]]
        has_validation = any(event["event_type"] == "validation" for event in all_events)
        has_authorization = all(bool(event.get("authorization")) for event in all_events if event["event_type"] == "tool_call")
        inferred_improvements = []
        if not has_validation:
            inferred_improvements.append({
                "kind": "safety",
                "description": "Add an explicit validation checkpoint before reporting completion.",
                "basis": "No validation event was observed in the selected records.",
                "confidence": "low",
                "executable": False,
            })
        if not has_authorization:
            inferred_improvements.append({
                "kind": "authorization",
                "description": "Require task-scoped authorization before each external tool call.",
                "basis": "Authorization context was absent from at least one selected tool call.",
                "confidence": "low",
                "executable": False,
            })
        findings = sorted({finding for item in occurrences for finding in item["redaction_findings"]})
        confidence_score = min(0.95, 0.5 + 0.15 * min(len(occurrences), 3))
        limitations = [
            "Candidate reflects observed traces; it is not a learned model policy.",
            "Synthetic or sparse records may omit important branches and failure handling.",
            "Inferred improvements are review notes and are not executable steps.",
        ]
        if findings:
            limitations.append("Sensitive or private fields were redacted before extraction.")
        candidates.append(
            CandidateSkill(
                candidate_id=f"skill-candidate-{uuid4().hex[:12]}",
                name=f"{workflow_name.replace('_', ' ').title()} procedure",
                trigger={
                    "description": (
                        first["trigger"]
                        if selection.allow_private_content
                        else f"Request matching workflow '{workflow_name}'."
                    ),
                    "raw_text_included": selection.allow_private_content,
                    "workflow_name": workflow_name,
                    "observed_occurrences": len(occurrences),
                },
                required_tools=required_tools,
                observed_steps=observed_steps,
                inferred_improvements=inferred_improvements,
                validation_criteria=_validation_criteria(records_payload),
                provenance={
                    "source_record_ids": [record["record_id"] for record in records_payload],
                    "source_refs": [record["source"] for record in records_payload],
                    "selection": {
                        "record_ids": list(selection.record_ids),
                        "allow_private_content": selection.allow_private_content,
                    },
                    "redaction_findings": findings,
                },
                confidence={
                    "level": "medium" if confidence_score <= 0.8 else "high",
                    "score": round(confidence_score, 2),
                    "limitations": limitations,
                },
            )
        )
    return candidates
