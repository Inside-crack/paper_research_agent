# Capability: evaluation-quality-gates

> Baseline - reverse-engineered by the `ss-reverse-spec` skill.
> Generated at commit: `aca8f3c`
> Date: 2026-08-19
> Legacy requirements: evaluation mechanism requirements and P01-P29 quality gates

## Purpose

The Evaluation Agent independently evaluates phase output using original
evidence, deterministic checks, structured model evaluation, and bounded
revision outcomes.

## Requirements

### Requirement: Evaluate a phase from independent evidence

The system SHALL build an evaluation input containing the original user query,
trimmed original evidence, the execution plan when present, and the Research
Agent output.

#### Scenario: Evaluation input is assembled

- **WHEN** `evaluate_phase` is called
- **THEN** the evaluation prompt contains original evidence before the
  Research Agent output and includes the phase completion checklist.

Evidence: `src/paper_agent/evaluation_agent/agent.py`,
`prompts/evaluation_agent/system.txt`.

### Requirement: Run deterministic checks before accepting model output

The system SHALL run deterministic checks before using the model verdict and
SHALL treat missing or erroneous output as a failed deterministic check.

#### Scenario: Output is empty or contains an error

- **WHEN** the phase output is empty or contains an `error` field
- **THEN** the system records a critical `missing_output` issue and returns a
  blocked evaluation result.

#### Scenario: Deterministic checks pass

- **WHEN** all deterministic checks pass
- **THEN** the system may parse the model's structured verdict and issues.

Evidence: `src/paper_agent/evaluation_agent/agent.py`,
`src/paper_agent/common/models/evaluation_result.py`.

### Requirement: Return a structured evaluation result

The system SHALL return an `EvaluationResult` containing the phase, verdict,
score, issues, evidence summary, deterministic check counts, reviewer model,
input artifacts, and revision count.

#### Scenario: Valid model verdict

- **WHEN** the model returns a valid `PASS`, `REVISE`, or `BLOCKED` verdict
- **THEN** the result preserves the verdict, score, summary, intervention
  request, and structured issues.

#### Scenario: Invalid model issue data

- **WHEN** an individual issue cannot be converted to the expected schema
- **THEN** the system logs a warning and continues processing other issues.

Evidence: `src/paper_agent/evaluation_agent/agent.py`,
`src/paper_agent/common/models/evaluation_result.py`.

### Requirement: Enforce bounded revision outcomes

The system SHALL convert a `REVISE` result to `BLOCKED` when the phase has
already reached the configured maximum revision count and SHALL request human
intervention.

#### Scenario: Revision limit reached

- **WHEN** a phase revision count is at or above the configured maximum and the
  model returns `REVISE`
- **THEN** the evaluation result is changed to `BLOCKED` with a human
  intervention reason.

Evidence: `src/paper_agent/evaluation_agent/agent.py`,
`src/paper_agent/orchestrator/orchestrator.py`,
`examples/test_a03_revise.py`.
