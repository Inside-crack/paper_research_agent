# Capability: artifact-persistence

> Baseline - reverse-engineered by the `ss-reverse-spec` skill.
> Generated at commit: `aca8f3c`
> Date: 2026-08-19
> Legacy requirements: D01-D04, E01-E04

## Purpose

The system persists task specifications, phase plans and outputs, evaluation
results, error context, manifests, task indexes, checkpoints, and task event
logs in inspectable JSON or JSONL files.

## Requirements

### Requirement: Write JSON artifacts atomically

The system SHALL write JSON data through a temporary file, flush and fsync the
file, and replace the destination atomically; failed writes SHALL be surfaced
after temporary-file cleanup.

#### Scenario: JSON artifact is written

- **WHEN** the persistence layer saves JSON data
- **THEN** the destination contains valid JSON and the temporary file is
  replaced atomically.

Evidence: `src/paper_agent/common/persistence/manifest.py`,
`src/paper_agent/common/persistence/state_persistence.py`.

### Requirement: Maintain task manifests and a global task index

The system SHALL maintain a per-task manifest containing phases, artifacts,
steps, errors, revisions, and status, and SHALL update a global task index with
task status and latest score information.

#### Scenario: Task manifest is created

- **WHEN** a new research specification is persisted
- **THEN** the system creates a manifest with initialized research phases and
  registers the task in the global index.

#### Scenario: Manifest is missing or invalid

- **WHEN** task state exists but the manifest cannot be loaded
- **THEN** the system rebuilds a manifest from task state and discovered
  artifacts when possible.

Evidence: `src/paper_agent/common/persistence/manifest.py`,
`src/paper_agent/common/persistence/state_persistence.py`,
`examples/test_d01_d04_indexing.py`.

### Requirement: Use structured artifact names and discover files

The system SHALL generate phase, step, tool, result, evaluation, summary, and
error names that can be parsed back into their components.

#### Scenario: Standard artifact name is generated

- **WHEN** a phase result is persisted for a tool step
- **THEN** the filename contains the phase, step, type, and tool components and
  can be parsed into structured metadata.

Evidence: `src/paper_agent/common/persistence/naming.py`,
`examples/test_d01_d04_indexing.py`,
`examples/test_e01_e04_error_persistence.py`.

### Requirement: Record task events as JSONL

The system SHALL append structured events for phase starts and completions,
tool steps, revisions, checkpoints, errors, cleanup, and task completion.

#### Scenario: Task event is emitted

- **WHEN** a task lifecycle event occurs
- **THEN** `logs/run.jsonl` receives one JSON object containing the event name
  and event-specific fields.

#### Scenario: Log file cannot be opened

- **WHEN** the task JSONL log cannot be opened
- **THEN** the logger records an error and does not crash the main task solely
  because the auxiliary log is unavailable.

Evidence: `src/paper_agent/common/persistence/task_jsonl_logger.py`,
`examples/test_e01_e04_error_persistence.py`.

### Requirement: Persist failure context and retain recent checkpoints

The system SHALL persist structured error context and phase completion records,
and SHALL retain only the configured number of most recent checkpoints.

#### Scenario: Phase fails or requires revision

- **WHEN** a phase is blocked, raises an exception, or requires revision
- **THEN** the system writes error context including phase, plan, evaluation,
  messages, traceback when available, and recovery information.

#### Scenario: Checkpoint retention is applied

- **WHEN** checkpoint cleanup runs with a retention limit
- **THEN** older checkpoints are deleted and the newest checkpoints are kept.

Evidence: `src/paper_agent/common/persistence/error_context.py`,
`src/paper_agent/common/persistence/state_persistence.py`,
`examples/test_e01_e04_error_persistence.py`.
