## ADDED Requirements

### Requirement: Generate and validate a paper glossary

The system SHALL accept terminology candidates for a parsed paper, SHALL validate
that each source term has evidence in the original paper text, and SHALL persist
deduplicated `TermEntry` records with source term, target term, context, and confidence.

#### Scenario: Valid terminology candidates are persisted

- **WHEN** the caller provides a parsed paper artifact and valid terminology candidates
- **THEN** the system stores the validated terms in `PaperArtifact.glossary`
- **AND** returns the artifact ID, deduplicated term count, and persisted artifact path

#### Scenario: Duplicate source terms are provided

- **WHEN** candidates contain source terms that differ only by case or surrounding whitespace
- **THEN** the system keeps one entry with the highest confidence
- **AND** produces stable ordering for the persisted glossary

#### Scenario: No terminology candidates are found

- **WHEN** the caller provides an empty candidate list
- **THEN** the system persists an empty glossary successfully
- **AND** does not invent terminology

### Requirement: Reject unsupported terminology candidates

The system SHALL reject candidates with missing source terms, missing target terms,
invalid confidence, or source terms absent from the paper's original text.

#### Scenario: Source term has no paper evidence

- **WHEN** a candidate source term does not occur in the original paper text
- **THEN** the system returns a failed `ToolResult` identifying the unsupported term
- **AND** it does not update the glossary

#### Scenario: Candidate fields are invalid

- **WHEN** a candidate has an empty target term or confidence outside the inclusive range 0 to 1
- **THEN** the system returns a failed `ToolResult` identifying the invalid field
- **AND** it does not update the glossary

#### Scenario: Artifact is not parsed

- **WHEN** the paper artifact has no original text
- **THEN** the system returns a failed `ToolResult` explaining that P11 parsing is required
- **AND** it does not generate a glossary

### Requirement: Persist glossary updates atomically

The system SHALL atomically update the existing paper artifact and register the glossary
update in the task Manifest.

#### Scenario: Glossary persistence fails

- **WHEN** artifact or Manifest persistence fails
- **THEN** the system returns a failed `ToolResult` containing the persistence error
- **AND** it does not report glossary generation success
