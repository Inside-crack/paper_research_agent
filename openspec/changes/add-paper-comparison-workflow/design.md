# Design: Paper Comparison Workflow

## Boundaries

```text
ConversationApplicationService
  -> compare_papers capability
  -> Orchestrator task
  -> PaperComparisonWorkflow
      -> PaperAcquisitionService
      -> existing PaperArtifact/PaperProcessingWorkflow
      -> validated PaperComparisonArtifact
```

## Acquisition precedence

```text
PaperArtifact -> local PDF -> metadata -> arxiv_get_paper -> paper_download
```

Every local resource must be matched by normalized arXiv identity and version.

## Facts versus analysis

Code owns paper identity, resource provenance, deduplication, and schema
validation. The LLM may explain differences and commonalities but may not
overwrite tool-backed facts.

## Compatibility

The new workflow is independent of `PaperProcessingWorkflow`. Existing
single-paper task phases, artifacts, and checkpoints remain readable.
