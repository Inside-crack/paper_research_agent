# Add Paper Comparison Workflow

## Why

The current paper workflow is centered on one target paper and includes
reproduction-oriented stages that are not appropriate when papers have no
usable code. Users need to compare multiple papers using their metadata,
parsed artifacts, and reported findings without executing paper code.

## What Changes

- Add a `paper_comparison` task specification and validated comparison artifact.
- Add a reusable paper acquisition boundary that can prefer existing local
  artifacts/PDFs before using arXiv and paper download capabilities.
- Add an independent `PaperComparisonWorkflow` boundary.
- Keep single-paper processing behavior unchanged.
- Add the foundation for a `compare_papers` capability and confirmation flow.

## Scope

The first implementation covers the models, deterministic paper identity
handling, local-resource reuse contract, and a workflow that can assemble
structured comparison output. Code execution and reproduction remain out of
scope.
