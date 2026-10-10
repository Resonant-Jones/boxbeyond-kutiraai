import json
import unittest
from pathlib import Path

from workflow_engine.skill_learning import (
    ExecutionRecord,
    SourceSelection,
    extract_skill_candidates,
)


FIXTURE = Path(__file__).parents[2] / "examples" / "skill_learning" / "synthetic_records.json"


def load_records():
    payload = json.loads(FIXTURE.read_text())
    return [ExecutionRecord.from_dict(item) for item in payload]


class SkillLearningTests(unittest.TestCase):
    def test_extracts_reviewable_candidate_from_recurring_tool_sequence(self):
        records = load_records()
        candidate = extract_skill_candidates(
            records,
            SourceSelection(tuple(record.record_id for record in records)),
        )[0]

        self.assertEqual(candidate.approval_status, "pending")
        self.assertFalse(candidate.executable)
        self.assertEqual(
            [tool["name"] for tool in candidate.required_tools],
            ["github.fetch_pull_request", "github.fetch_checks"],
        )
        self.assertEqual(
            [step["tool"] for step in candidate.observed_steps if step["tool"]],
            ["github.fetch_pull_request", "github.fetch_checks"],
        )
        self.assertEqual(candidate.observed_steps[-1]["event_type"], "validation")
        self.assertEqual(candidate.validation_criteria[0]["kind"], "review_reported")
        self.assertIn("inferred_improvements", candidate.to_dict())


    def test_redacts_credentials_private_content_and_account_data(self):
        candidate = extract_skill_candidates(
            load_records(),
            SourceSelection(("synthetic-export-001", "synthetic-export-002")),
        )[0]
        serialized = json.dumps(candidate.to_dict())

        self.assertNotIn("SYNTHETIC_SECRET", serialized)
        self.assertNotIn("private@example.com", serialized)
        self.assertNotIn("private review title", serialized)
        self.assertNotIn("Review a pull request and report whether it is ready.", serialized)
        self.assertIn("redaction_findings", serialized)


    def test_source_selection_is_required_and_limits_provenance(self):
        with self.assertRaisesRegex(ValueError, "explicit source selection"):
            SourceSelection(()).validate()

        candidate = extract_skill_candidates(
            load_records(),
            SourceSelection(("synthetic-export-001", "synthetic-export-002")),
        )[0]
        self.assertEqual(
            candidate.provenance["source_record_ids"],
            ["synthetic-export-001", "synthetic-export-002"],
        )


    def test_approval_is_the_only_path_to_executable_candidate(self):
        candidate = extract_skill_candidates(
            load_records(),
            SourceSelection(("synthetic-export-001", "synthetic-export-002")),
        )[0]
        with self.assertRaisesRegex(ValueError, "approver"):
            candidate.approve(" ")

        approved = candidate.approve("human-reviewer", "2026-10-10T10:00:00+00:00")
        self.assertEqual(approved.approval_status, "approved")
        self.assertTrue(approved.executable)
        self.assertEqual(approved.approved_by, "human-reviewer")


    def test_failed_or_incomplete_records_are_not_promoted(self):
        records = load_records()
        failed = ExecutionRecord.from_dict(
            {
                **records[0].to_dict(),
                "record_id": "failed",
                "status": "failed",
                "completion_evidence": [],
            }
        )
        self.assertEqual(
            extract_skill_candidates(records + [failed], SourceSelection(("failed",))),
            [],
        )


if __name__ == "__main__":
    unittest.main()
