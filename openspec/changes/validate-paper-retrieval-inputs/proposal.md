# Validate Paper Retrieval Inputs

## Why

The current arXiv search tool validates that `query` is present but allows a
non-positive `max_results` value to reach the arXiv client. This makes invalid
requests fail late or behave ambiguously and does not provide a stable negative
test contract.

## What Changes

- Reject `max_results <= 0` before creating an arXiv search request.
- Return a failed `ToolResult` with the exact error
  `max_results must be greater than 0`.
- Add executable coverage for zero and negative values.

## Capability

- Existing capability: `paper-retrieval`
- Compatibility: backward-compatible validation tightening; valid positive
  search requests and existing missing-query behavior are preserved.

## Scope

- In scope: validation in `ArxivSearchTool._execute` and its regression test.
- Out of scope: query parsing, arXiv API behavior, result ranking,
  classification, and other retrieval filters.

## Constraints

- Preserve the existing non-empty query validation.
- Do not introduce a new abstraction for one validation rule.
- The invalid-input path must not create an arXiv client or make a network
  request.

## Acceptance

- The delta scenarios in
  `openspec/changes/validate-paper-retrieval-inputs/specs/paper-retrieval/spec.md`
  pass.
- Existing retrieval behavior remains unchanged for positive `max_results`.
