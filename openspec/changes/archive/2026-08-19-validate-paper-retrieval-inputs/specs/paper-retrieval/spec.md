## MODIFIED Requirements

### Requirement: Search arXiv with validated query input

The system SHALL require a non-empty query and a positive `max_results` value
for arXiv search, SHALL reject invalid inputs before creating an arXiv request,
and SHALL return a structured result set containing the original query, result
count, and paper metadata.

#### Scenario: Valid search request

- **WHEN** the caller provides a non-empty query and `max_results > 0`
- **THEN** the system searches arXiv and returns paper IDs, titles, authors,
  abstracts, URLs, dates, categories, versions, and code availability hints.

#### Scenario: Missing query

- **WHEN** the caller omits or provides an empty query
- **THEN** the tool returns a failed `ToolResult` with a missing-query error.

#### Scenario: Non-positive result limit

- **WHEN** the caller provides `max_results <= 0`
- **THEN** the tool returns a failed `ToolResult` with the exact error
  `max_results must be greater than 0` before creating an arXiv client or
  making a network request.

Evidence: `src/paper_agent/tools/retrieval/arxiv_tool.py`.
