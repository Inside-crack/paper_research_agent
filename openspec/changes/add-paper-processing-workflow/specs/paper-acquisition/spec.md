## ADDED Requirements

### Requirement: Execute paper processing as persisted substeps

The system SHALL keep the existing `PAPER_PARSING` top-level phase and SHALL execute
the ordered persisted substeps `download`, `parse`, `glossary`, `translate`, and
`summary`.

#### Scenario: A selected paper completes P10-P14

- **WHEN** paper retrieval returns at least one candidate and the first candidate is selected
- **THEN** the system executes the five substeps in the defined order
- **AND** persists each substep status and output artifacts
- **AND** enters the existing next top-level phase only after all five substeps pass

#### Scenario: A substep passes

- **WHEN** a substep tool result, deterministic checks, and Evaluation Agent evaluation all pass
- **THEN** the substep status becomes `PASS`
- **AND** its outputs become the only allowed dynamic inputs for dependent later substeps
- **AND** a later revision does not rerun the passed substep

### Requirement: Propagate artifacts between paper substeps

The system SHALL pass real persisted outputs between substeps instead of requiring one
static plan to predict dynamic paths or identifiers.

#### Scenario: Download output feeds parsing

- **WHEN** `download` passes
- **THEN** `parse` receives the persisted `artifact_path` and `pdf_path`

#### Scenario: Parsing output feeds downstream steps

- **WHEN** `parse` passes
- **THEN** `glossary`, `translate`, and `summary` receive the persisted sections and original text

#### Scenario: Glossary and translation outputs feed later steps

- **WHEN** `glossary` passes
- **THEN** `translate` receives the persisted glossary
- **AND WHEN** `translate` passes
- **THEN** `summary` receives translated sections and their evidence context

### Requirement: Apply substep quality gates and targeted revision

The system SHALL evaluate every substep independently, SHALL allow at most one targeted
revision of the current substep, and SHALL block without changing the selected paper
when the second attempt fails.

#### Scenario: Current substep requires revision

- **WHEN** the current substep fails deterministic or Evaluation Agent checks
- **THEN** the system retries only that substep once with targeted correction context
- **AND** it does not rerun any previously passed substep

#### Scenario: Targeted revision fails twice

- **WHEN** the same substep fails after its one allowed revision
- **THEN** the substep and task become `BLOCKED`
- **AND** later substeps are not executed
- **AND** the system does not select a different candidate paper

#### Scenario: Retrieval has no candidates

- **WHEN** paper retrieval returns an empty candidate list
- **THEN** the task becomes `BLOCKED`
- **AND** the system waits for new user input instead of inventing or switching a paper

### Requirement: Persist substep state and preserve legacy tasks

The system SHALL persist substep status, revision count, input artifacts, output artifacts,
timestamps, and errors in task state and Manifest, SHALL use atomic JSON writes, and SHALL
read legacy `PAPER_PARSING` tasks without requiring migration.

#### Scenario: Substep state is interrupted

- **WHEN** a task is interrupted at a substep boundary
- **THEN** completed substeps remain `PASS`
- **AND** the task can resume from the current substep without rerunning passed substeps

#### Scenario: Legacy artifact has no substep state

- **WHEN** an existing task or artifact predates P30 and has no substep fields
- **THEN** the system can read its existing `PAPER_PARSING` data
- **AND** does not require destructive migration

#### Scenario: Persistence fails

- **WHEN** artifact or Manifest persistence fails at any substep
- **THEN** the system records the error context
- **AND** does not report that substep as successful
