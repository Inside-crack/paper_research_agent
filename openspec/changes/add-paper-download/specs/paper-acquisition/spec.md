## ADDED Requirements

### Requirement: Acquire and validate an arXiv paper PDF

The system SHALL accept an arXiv identifier, an arXiv PDF URL, or a paper candidate
containing either identifier, SHALL acquire the requested version, and SHALL reject
responses that are not non-empty PDF content before reporting success.

#### Scenario: Valid arXiv identifier is acquired

- **WHEN** the caller provides a valid arXiv identifier and task ID
- **THEN** the system downloads the requested PDF version into the task artifact directory
- **AND** returns the arXiv ID, version, relative PDF path, byte size, and paper artifact ID

#### Scenario: Candidate PDF URL is acquired

- **WHEN** the caller provides a candidate with an arXiv PDF URL and task ID
- **THEN** the system uses that URL, validates the response as a non-empty PDF, and returns a persisted artifact reference

#### Scenario: Input has no usable paper identifier

- **WHEN** the caller provides neither an arXiv identifier nor a valid arXiv PDF URL
- **THEN** the system returns a failed `ToolResult` with an explicit input error
- **AND** it does not make a network request or create a success artifact

#### Scenario: Response is not a PDF

- **WHEN** the remote response is successful but its content is empty or does not start with the PDF magic bytes
- **THEN** the system returns a failed `ToolResult` identifying invalid PDF content
- **AND** it does not register the file in the task Manifest

### Requirement: Preserve source metadata and version identity

The system SHALL persist the source, arXiv identifier, version, title, authors, DOI,
publication date, and PDF path in a structured `PaperArtifact` associated with the task.

#### Scenario: Metadata is persisted after download

- **WHEN** PDF validation and artifact persistence both succeed
- **THEN** the `PaperArtifact` JSON contains the source metadata and relative PDF path
- **AND** the task Manifest lists both persisted files

#### Scenario: Manifest persistence fails

- **WHEN** the PDF or paper artifact cannot be registered in the task Manifest
- **THEN** the tool returns a failed `ToolResult` containing the persistence error
- **AND** it does not report the acquisition as successful

### Requirement: Write acquired files atomically

The system SHALL write downloaded PDF and JSON artifact content through temporary files
and SHALL atomically replace the destination only after the content has been validated.

#### Scenario: Interrupted or invalid download

- **WHEN** downloading or PDF validation fails
- **THEN** the destination PDF is not replaced by invalid content
- **AND** temporary files are removed
