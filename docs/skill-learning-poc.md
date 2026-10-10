# Offline skill-learning proof of concept

KutiraAI's existing workflow trace records a task name, output, and timestamp.
That is useful observability, but it is not enough to reconstruct a reusable
agent procedure. This proof of concept adds a portable execution-record format
and an offline extractor without training model weights or executing generated
skills.

## Scope

The prototype accepts only an explicit list of `ExecutionRecord` objects. It
does not scan Codex archives, conversation folders, credentials, or accounts.
The caller selects record IDs through `SourceSelection`; failed and incomplete
records are ignored for candidate generation.

Each record can represent:

- ordered tool calls, structured inputs, and outputs;
- decisions, observations, failures, and validation events;
- authorization context;
- completion evidence and source provenance.

Before extraction, credentials, account identifiers, email addresses, and
free-form private content are redacted by default. The candidate preserves
tool names, input/output shapes, validation kinds, and provenance without
copying private conversation text.

## Observed versus inferred

`observed_steps`, `required_tools`, and `validation_criteria` are derived from
events that were actually present in the selected records. `inferred_improvements`
contains review notes such as adding a validation checkpoint or explicit
authorization check. Inferred improvements are marked non-executable and are
never silently merged into the observed procedure.

## Approval boundary

Every candidate starts with `approval_status: pending` and `executable: false`.
Calling `CandidateSkill.approve()` requires a non-empty human approver and an
approval timestamp. The prototype has no runtime that executes approved skills;
approval only demonstrates the portable state transition needed before a future
executor could consume one.

## Example

The synthetic fixture runs the same two-tool pull-request review procedure twice:

1. fetch the pull request;
2. fetch its checks;
3. observe a verified CI result;
4. report completion.

Running the focused test produces one pending candidate with the two observed
tool calls, explicit validation criteria, provenance for both records, redaction
findings, and confidence limitations. The candidate can then be approved in a
separate human review step.

The experiment intentionally leaves MLX fine-tuning, unrestricted history
ingestion, autonomous execution, and Codexify production integration out of
scope.
