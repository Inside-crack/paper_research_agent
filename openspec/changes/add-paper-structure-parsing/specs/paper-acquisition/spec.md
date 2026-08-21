## ADDED Requirements

### Requirement: Parse a persisted paper PDF into structured sections

The system SHALL load a persisted `PaperArtifact` and its PDF, extract the original
text, and populate ordered sections with titles, levels, source text, and detectable
formula, table, figure, and citation references.

#### Scenario: Valid persisted PDF is parsed

- **WHEN** the caller provides a task ID and an existing paper artifact path whose PDF is readable
- **THEN** the system extracts page text and updates the `PaperArtifact` with original text and ordered sections
- **AND** the result contains page count, section count, text length, and the persisted artifact path

#### Scenario: PDF has no recognizable headings

- **WHEN** the PDF is readable but no supported heading pattern is found
- **THEN** the system preserves the full extracted text in one ordered `Document` section
- **AND** it does not discard the paper content

#### Scenario: A page cannot be extracted

- **WHEN** an individual PDF page raises an extraction error
- **THEN** the system records the page and error in `PaperArtifact.parsing_errors`
- **AND** it retains text extracted from other readable pages

### Requirement: Reject invalid paper parsing inputs

The system SHALL reject missing artifacts, missing PDFs, invalid artifact paths, and
unreadable PDF files with explicit errors and SHALL NOT report a successful parse.

#### Scenario: Artifact path is missing

- **WHEN** the caller omits `task_id` or `artifact_path`
- **THEN** the system returns a failed `ToolResult` with an explicit missing-input error
- **AND** it does not open a PDF

#### Scenario: Artifact path escapes the task directory

- **WHEN** the caller provides an absolute path or a path containing traversal outside the task artifact directory
- **THEN** the system returns a failed `ToolResult`
- **AND** it does not read or write any file outside the task directory

#### Scenario: Paper artifact or PDF is missing

- **WHEN** the artifact JSON or its referenced PDF does not exist
- **THEN** the system returns a failed `ToolResult` identifying the missing file
- **AND** it does not create a parsed artifact

### Requirement: Persist parsing output atomically

The system SHALL atomically update the structured `PaperArtifact` after parsing and
register the updated artifact in the task Manifest.

#### Scenario: Parsed artifact is persisted

- **WHEN** PDF extraction completes
- **THEN** the updated JSON is written atomically
- **AND** the task Manifest records the parsed artifact file

#### Scenario: Parsed artifact persistence fails

- **WHEN** the artifact JSON or Manifest update fails
- **THEN** the system returns a failed `ToolResult` containing the persistence error
- **AND** it does not report parsing success
