## ADDED Requirements

### Requirement: Translate every parsed paper section

The system SHALL accept one non-empty translation for every parsed paper section,
SHALL reject unknown or missing section IDs, and SHALL persist translated section
text together with the concatenated translated paper text.

#### Scenario: All sections have valid translations

- **WHEN** the caller provides exactly one non-empty translation for every parsed section
- **THEN** the system updates each section's `translated_text`
- **AND** updates `PaperArtifact.full_text_translated` in section order

#### Scenario: A section is missing or duplicated

- **WHEN** the translations omit a parsed section or provide duplicate section IDs
- **THEN** the system returns a failed `ToolResult` identifying the coverage problem
- **AND** it does not update any translated section

#### Scenario: An unknown section is provided

- **WHEN** a translation references a section ID absent from the parsed artifact
- **THEN** the system returns a failed `ToolResult` identifying the unknown section
- **AND** it does not update the artifact

### Requirement: Preserve protected paper content during translation

The system SHALL reject translations that remove original numeric tokens, citation
tokens, required formula markers, or glossary target terms used by the section.

#### Scenario: Protected content is preserved

- **WHEN** a translation retains all original numeric and citation tokens, required formula markers, and applicable glossary targets
- **THEN** the system accepts the translation for persistence

#### Scenario: Numeric or citation content is changed

- **WHEN** a translation removes or changes an original numeric token or citation token
- **THEN** the system returns a failed `ToolResult` naming the affected section and token
- **AND** it does not update the artifact

#### Scenario: Formula or glossary content is lost

- **WHEN** a section marked with formula evidence loses its formula marker, or an applicable glossary target is absent
- **THEN** the system returns a failed `ToolResult`
- **AND** it does not update the artifact

### Requirement: Persist translations atomically

The system SHALL atomically update the translated paper artifact and SHALL propagate
artifact or Manifest persistence failures as unsuccessful tool results.

#### Scenario: Translation persistence fails

- **WHEN** the artifact or Manifest update fails after validation
- **THEN** the system returns a failed `ToolResult` containing the persistence error
- **AND** it does not report translation success
