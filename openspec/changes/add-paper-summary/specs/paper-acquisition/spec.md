## ADDED Requirements

### Requirement: Persist an evidence-linked paper summary

The system SHALL accept structured research questions, methodology, contributions,
conclusions, limitations, and evidence section IDs for a parsed paper, and SHALL
persist the summary and evidence mapping in `PaperArtifact`.

#### Scenario: Valid summary with section evidence is persisted

- **WHEN** the caller provides valid summary fields and existing section IDs for every non-empty summary category
- **THEN** the system updates the corresponding `PaperArtifact` summary fields
- **AND** persists `summary_evidence` with the referenced section IDs

#### Scenario: Optional summary lists are empty

- **WHEN** a valid summary explicitly provides an empty contributions or limitations list with evidence for the remaining categories
- **THEN** the system persists the summary successfully
- **AND** does not invent missing content

### Requirement: Reject unsupported summary claims

The system SHALL reject summaries with missing required fields, invalid field types,
empty required content, or evidence section IDs absent from the parsed artifact.

#### Scenario: Evidence references an unknown section

- **WHEN** any evidence mapping references a section ID not present in the artifact
- **THEN** the system returns a failed `ToolResult` identifying the unknown section
- **AND** it does not update any summary field

#### Scenario: Summary field is invalid

- **WHEN** methodology is empty, a list item is empty, or a summary field has the wrong type
- **THEN** the system returns a failed `ToolResult` identifying the invalid field
- **AND** it does not update the artifact

#### Scenario: Artifact is not parsed

- **WHEN** the artifact has no sections or original text
- **THEN** the system returns a failed `ToolResult` explaining that P11 parsing is required
- **AND** it does not create a summary

### Requirement: Persist summary atomically

The system SHALL atomically update the summary artifact and SHALL propagate artifact or
Manifest persistence failures as unsuccessful tool results.

#### Scenario: Summary persistence fails

- **WHEN** artifact or Manifest persistence fails after validation
- **THEN** the system returns a failed `ToolResult` containing the persistence error
- **AND** it does not report summary success
