# Capability: task-lifecycle

> Baseline - reverse-engineered by the `ss-reverse-spec` skill.
> Generated at commit: `aca8f3c`
> Date: 2026-08-19
> Legacy requirements: P01-P04

## Purpose

The system creates and advances a research task through named phases while
keeping task state, budgets, revisions, checkpoints, and failure status
observable to callers.

## Requirements

### Requirement: Create a task with persisted research state

The system SHALL create a `ResearchSpec` and `TaskState` for a new task, create
task workspace and artifact directories, persist the research specification, and
initialize phase state before execution.

#### Scenario: New task initialization

- **WHEN** a caller starts a task without a checkpoint
- **THEN** the system creates a task state in `task_initialization`, persists
  the research specification, creates workspace and artifact directories, and
  initializes the task manifest.

Evidence: `src/paper_agent/orchestrator/orchestrator.py`,
`src/paper_agent/common/models/research_spec.py`,
`src/paper_agent/common/models/task_state.py`,
`src/paper_agent/common/persistence/state_persistence.py`.

### Requirement: Advance through the defined research phases

The system SHALL advance a task in this order:
`task_initialization`, `paper_retrieval`, `paper_parsing`, `code_location`,
`reproduction_planning`, `experiment_execution`, and `result_reporting`, then
`completed`.

#### Scenario: Phase passes evaluation

- **WHEN** a phase receives a `PASS` evaluation
- **THEN** the phase is marked completed and the task moves to the next phase.

#### Scenario: Phase is blocked

- **WHEN** a phase receives a `BLOCKED` evaluation
- **THEN** the task is marked failed, records the blocked phase and reason, and
  does not advance to the next phase.

Evidence: `src/paper_agent/orchestrator/orchestrator.py`,
`src/paper_agent/common/models/base.py`.

### Requirement: Apply bounded revision handling

The system SHALL record a phase revision and retry the same phase when the
evaluation verdict is `REVISE`, subject to the configured maximum revision
count.

#### Scenario: Revision remains within the limit

- **WHEN** a phase receives `REVISE` and the revision count is below the limit
- **THEN** the system records the revision, saves a checkpoint, and retries the
  same phase.

#### Scenario: Revision limit is exceeded

- **WHEN** a phase exceeds the configured revision limit
- **THEN** the system changes the result to `BLOCKED`, requires human
  intervention, and fails the task.

Evidence: `src/paper_agent/orchestrator/orchestrator.py`,
`src/paper_agent/common/models/task_state.py`,
`examples/test_a03_revise.py`.

### Requirement: Stop execution when the budget is exceeded

The system SHALL stop the task when token, GPU-minute, or wall-time usage
reaches its configured budget.

#### Scenario: Budget exceeded

- **WHEN** `Budget.is_exceeded()` returns true during the task loop
- **THEN** the task is marked failed with a budget-exceeded reason and no new
  phase is started.

Evidence: `src/paper_agent/common/models/base.py`,
`src/paper_agent/orchestrator/orchestrator.py`.

### Requirement: Resume from a checkpoint

The system SHALL load task state from a checkpoint, rebuild a missing manifest
from persisted task state when possible, and trim old checkpoints on resume.

#### Scenario: Resume with a valid checkpoint

- **WHEN** a caller supplies a checkpoint path
- **THEN** the system restores the task state, initializes task logging, repairs
  a missing manifest when state data is available, and continues execution.

Evidence: `src/paper_agent/orchestrator/orchestrator.py`,
`src/paper_agent/common/persistence/state_persistence.py`,
`src/paper_agent/common/persistence/manifest.py`.
