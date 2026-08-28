# Paper Comparison

## Requirements

### Requirement: Comparison specifications identify multiple papers
The system SHALL represent a comparison task with a user query, two or more
paper references, and comparison dimensions.

#### Scenario: Valid comparison specification
- **WHEN** a comparison specification is created with two to five unique paper
  references
- **THEN** the specification is accepted
- **AND** the paper references are normalized for identity comparison

#### Scenario: Duplicate paper references
- **WHEN** two references normalize to the same arXiv paper
- **THEN** the specification is rejected
- **AND** no comparison workflow is started

### Requirement: Existing paper resources are preferred
The acquisition boundary SHALL prefer an existing complete PaperArtifact,
then a local PDF, before online acquisition.

#### Scenario: Existing artifact
- **WHEN** a matching local PaperArtifact is available
- **THEN** the workflow reuses it
- **AND** records the source as `local`

#### Scenario: Missing local resource
- **WHEN** no matching local artifact or PDF is available
- **THEN** the workflow may obtain metadata with `arxiv_get_paper`
- **AND** may download the PDF with `paper_download`

### Requirement: Comparison output is validated
The workflow SHALL produce a validated comparison artifact containing all
confirmed papers, dimensions, a comparison matrix, conclusions, and missing
information.

#### Scenario: Comparison completed
- **WHEN** all confirmed paper inputs are available
- **THEN** `paper_comparison.json` is generated
- **AND** the artifact is schema-valid

#### Scenario: Missing evidence
- **WHEN** a paper does not provide evidence for a comparison field
- **THEN** the field is represented as `unknown` or listed in
  `missing_information`
- **AND** the absence of evidence is not converted to a negative fact
