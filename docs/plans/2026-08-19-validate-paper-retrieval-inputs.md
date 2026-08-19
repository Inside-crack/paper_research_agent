# Validate Paper Retrieval Inputs

**Change:** `validate-paper-retrieval-inputs`
**Repo:** `paper_research_agent`
**Mode:** lite
**User-Confirmed Scope Adjustments:** none

## Goal

Reject non-positive `max_results` values in `ArxivSearchTool` before any arXiv
client is created, while preserving the existing query validation and positive
search path.

## Scope

- Modify: `src/paper_agent/tools/retrieval/arxiv_tool.py`
- Create: `examples/test_paper_retrieval_validation.py`
- Delta spec: `openspec/changes/validate-paper-retrieval-inputs/specs/paper-retrieval/spec.md`

## Constraints

- Keep the exact error text: `max_results must be greater than 0`.
- Do not add a validation abstraction for this single field.
- Do not change query construction, date filtering, sorting, or result mapping.
- Invalid input must return a failed `ToolResult` before network access.

## Dependency graph

```text
Task 1: negative tests
    |
    v
Task 2: minimal validation
    |
    v
Task 3: regression verification
```

## Tasks

### Task 1: Add failing validation tests

**Depends on:** None
**Parallel group:** A

**Files:**

- Create: `examples/test_paper_retrieval_validation.py`

**Steps:**

- [ ] Step 1: Create the test file with this complete content:

```python
import asyncio
import sys
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.tools.retrieval.arxiv_tool import ArxivSearchTool


async def test_missing_query_keeps_existing_error():
    result = await ArxivSearchTool()._execute(max_results=5)
    assert result.success is False
    assert result.error == "Missing required parameter: query"


async def test_non_positive_max_results_is_rejected_before_request():
    tool = ArxivSearchTool()
    with patch("paper_agent.tools.retrieval.arxiv_tool.arxiv.Client") as client:
        for value in (0, -1):
            result = await tool._execute(query="agent memory", max_results=value)
            assert result.success is False
            assert result.error == "max_results must be greater than 0"
        client.assert_not_called()


async def test_positive_max_results_keeps_search_path():
    class EmptyClient:
        def results(self, search):
            return []

    with patch(
        "paper_agent.tools.retrieval.arxiv_tool.arxiv.Client",
        return_value=EmptyClient(),
    ) as client:
        result = await ArxivSearchTool()._execute(query="agent memory", max_results=3)
        assert result.success is True
        assert result.data["query"] == "agent memory"
        assert result.data["total_found"] == 0
        client.assert_called_once()


def main():
    asyncio.run(test_missing_query_keeps_existing_error())
    asyncio.run(test_non_positive_max_results_is_rejected_before_request())
    asyncio.run(test_positive_max_results_keeps_search_path())
    print("paper retrieval validation tests passed")


if __name__ == "__main__":
    main()
```

- [ ] Step 2: Run the new test before implementation.

Run:

```bash
PYTHONPATH=src python3 examples/test_paper_retrieval_validation.py
```

Expected: FAIL because `max_results <= 0` currently reaches the arXiv request
path instead of returning the required error.

**Covers Scenario:** `paper-retrieval/Non-positive result limit`,
`paper-retrieval/Missing query`

**Acceptance:** The test file exists; the non-positive test fails before the
implementation change while the existing query validation and positive-path
tests remain independently executable.

### Task 2: Add the minimal `max_results` validation

**Depends on:** Task 1
**Parallel group:** B

**Files:**

- Modify: `src/paper_agent/tools/retrieval/arxiv_tool.py`

**Steps:**

- [ ] Step 1: Insert the following check immediately after the existing query
  validation and before `max_results = min(...)`:

```python
        requested_max_results = kwargs.get("max_results", 20)
        if requested_max_results <= 0:
            return ToolResult.fail(error="max_results must be greater than 0")
```

- [ ] Step 2: Keep the existing positive-value calculation unchanged:

```python
        max_results = min(requested_max_results, settings.retrieval.arxiv_max_results)
```

- [ ] Step 3: Run the new validation test.

Run:

```bash
PYTHONPATH=src python3 examples/test_paper_retrieval_validation.py
```

Expected:

```text
paper retrieval validation tests passed
```

**Covers Scenario:** `paper-retrieval/Non-positive result limit`

**Acceptance:** Zero and negative `max_results` return the exact error without
creating an arXiv client.

### Task 3: Run focused regression verification

**Depends on:** Task 2
**Parallel group:** C

**Files:**

- Read: `examples/test_b01_b02_compression.py`
- Read: `examples/test_d01_d04_indexing.py`
- Read: `examples/test_e01_e04_error_persistence.py`

**Steps:**

- [ ] Step 1: Run the focused non-network regression scripts:

```bash
PYTHONPATH=src python3 examples/test_paper_retrieval_validation.py
PYTHONPATH=src python3 examples/test_b01_b02_compression.py
PYTHONPATH=src python3 examples/test_d01_d04_indexing.py
PYTHONPATH=src python3 examples/test_e01_e04_error_persistence.py
```

- [ ] Step 2: Verify the repository import:

```bash
PYTHONPATH=src python3 -c "import paper_agent; print('paper_agent import: OK')"
```

Expected: every script exits with code `0`, and the import prints
`paper_agent import: OK`.

**Covers Scenario:** `paper-retrieval/Valid search request`,
`paper-retrieval/Missing query`

**Acceptance:** Focused tests and import verification all exit successfully.

## Delivery

After Tasks 1-3 pass, run `ss-code-review` against the change, then commit:

```bash
git add src/paper_agent/tools/retrieval/arxiv_tool.py \
  examples/test_paper_retrieval_validation.py \
  openspec/changes/validate-paper-retrieval-inputs \
  docs/plans/2026-08-19-validate-paper-retrieval-inputs.md
git commit -m "fix(paper-retrieval): validate max results"
```
