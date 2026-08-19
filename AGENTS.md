# Paper Research Agent Agent Rules

## Project workflow

Read `WORKFLOW.md` before changing project behavior. For a new feature or a
cross-module change, use the following gates:

1. Clarify the requirement, scope, failure paths, and acceptance criteria.
2. Record the agreed specification and implementation boundary.
3. Implement in small verified slices.
4. Review the result against the specification and run the required checks.

SuperSpec is the preferred execution workflow when the `ss-*` skills are
available:

- `ss-feature-workflow`: new or cross-cutting features.
- `ss-coding-workflow`: implementation from an existing plan or direct change.
- `ss-troubleshooting-workflow`: runtime failures and evidence-based diagnosis.
- `ss-code-review`: final code and specification review.
- `ss-write-spec`, `ss-plan`, and `ss-trace-spec`: specification lifecycle work.

The existing `requirements/` documents remain authoritative for the current
project until an explicit migration to `openspec/` is completed. Do not delete
or rewrite them as part of installing or trialing SuperSpec.

## Non-negotiable engineering constraints

- Prefer incremental, low-intrusion edits over broad refactors.
- Do not discard upstream errors. Wrap and propagate them, or handle them with
  an explicit log and an intentional fallback.
- New persisted fields must preserve compatibility with existing data.
- Deterministic checks take precedence over LLM judgement for files, numbers,
  JSON structure, exit codes, and state transitions.
- Every feature needs positive and negative validation, including invalid input
  and relevant dependency-failure paths.
- Do not modify unrelated files or commit generated files, `.env` files,
  runtime data, logs, caches, or IDE metadata.
- The Research Agent must not call new tools during the synthesize stage.
- When a specification is ambiguous or conflicts with the codebase, stop and
  record the gap instead of inventing behavior.
- Persistence failures in core state or manifest updates must fail the main
  flow. Auxiliary error-context dumps may degrade to warnings only where the
  project specification explicitly allows it.

## Artifact and state rules

- Keep task state as the recovery source of truth.
- Preserve the existing artifact naming and JSONL logging conventions.
- Keep `progress.md`, `blockers.md`, and `resolutions.md` synchronized with
  implementation work while the legacy requirements workflow is active.
- A review verdict must be evidence-based and use `PASS`, `REVISE`, or
  `BLOCKED`. A `REVISE` cycle is limited to one targeted correction unless the
  specification is explicitly reopened.

## Verification baseline

Before and after relevant changes, prefer the smallest applicable checks first,
then run the affected examples and regression tests. At minimum, verify:

```bash
python -c "import paper_agent"
```

Do not claim completion without reporting the commands run and their results.
