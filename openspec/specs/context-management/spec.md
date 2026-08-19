# Capability: context-management

> Baseline - reverse-engineered by the `ss-reverse-spec` skill.
> Generated at commit: `aca8f3c`
> Date: 2026-08-19
> Legacy requirements: A01-A05, B01-B05, C01-C03

## Purpose

The agent runtime estimates message size, protects important context, compresses
large tool results, and creates a fresh phase context while carrying forward
bounded summaries.

## Requirements

### Requirement: Estimate context size and preserve messages below the threshold

The system SHALL estimate message tokens using the configured approximation and
SHALL return messages unchanged when they are below the compression threshold.

#### Scenario: Empty or small message list

- **WHEN** the message list is empty or below the threshold
- **THEN** compression returns the original messages and reports zero removed
  messages.

Evidence: `src/paper_agent/common/llm/base.py`,
`examples/test_c01_c02_c03_context_overflow.py`.

### Requirement: Compress oversized context by priority

The system SHALL remove non-anchor messages in ascending priority order when
the effective context exceeds the available budget, and SHALL inject a
compression notice containing the removal count.

#### Scenario: Context exceeds the compression threshold

- **WHEN** estimated tokens exceed the effective context budget
- **THEN** low-priority non-anchor messages are removed until the target is
  approached and a compression notice is retained.

Evidence: `src/paper_agent/common/llm/base.py`,
`examples/test_c01_c02_c03_context_overflow.py`.

### Requirement: Protect anchors and recent context

The system SHALL preserve system messages and messages marked as anchors during
compression, including at critical compression levels.

#### Scenario: Anchor messages coexist with filler messages

- **WHEN** oversized context contains system, anchor, and non-anchor messages
- **THEN** system and anchor messages remain in the compressed result while
  eligible filler messages are removed.

Evidence: `src/paper_agent/common/llm/base.py`,
`examples/test_c01_c02_c03_context_overflow.py`.

### Requirement: Isolate phase histories with summary carryover

The system SHALL reset an agent's message history when a new phase starts and
SHALL inject the research specification and prior phase summary cards as
anchored context.

#### Scenario: New phase starts

- **WHEN** `start_new_phase` is called for a different phase
- **THEN** the system initializes a fresh message history and adds the
  applicable specification and previous summaries.

#### Scenario: Same phase starts twice without force

- **WHEN** `start_new_phase` is called twice for the same phase without
  `force=True`
- **THEN** the system raises a runtime error.

Evidence: `src/paper_agent/common/agent_base.py`,
`src/paper_agent/research_agent/agent.py`,
`examples/test_phase_isolation.py`.

### Requirement: Compact large tool results before synthesis

The system SHALL reduce large arXiv and artifact results before inserting them
into synthesis prompts while preserving a reference to the persisted artifact.

#### Scenario: Multiple search results contain duplicate papers

- **WHEN** completed plan steps contain repeated arXiv IDs
- **THEN** the synthesis prompt contains one entry per base arXiv ID and
  reports the deduplicated count.

#### Scenario: A persisted artifact is larger than the prompt budget

- **WHEN** a loaded artifact contains a large dictionary or list
- **THEN** the prompt contains a bounded preview and directs the agent to the
  persisted artifact for the complete data.

Evidence: `src/paper_agent/common/agent_base.py`,
`src/paper_agent/orchestrator/orchestrator.py`,
`examples/test_b01_b02_compression.py`.
