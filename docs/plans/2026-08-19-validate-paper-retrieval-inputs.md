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
- Modify: `requirements/5.2_论文检索与筛选/P06_论文检索/solution.md`
- Modify: `requirements/5.2_论文检索与筛选/P06_论文检索/progress.md`
- Modify: `requirements/5.2_论文检索与筛选/P06_论文检索/blockers.md`
- Modify: `requirements/5.2_论文检索与筛选/P06_论文检索/resolutions.md`
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
    |
    v
Task 4: synchronize legacy P06 documents
```

## Tasks

### Task 1: Add failing validation tests

**Depends on:** None
**Parallel group:** A

**Files:**

- Create: `examples/test_paper_retrieval_validation.py`

**Steps:**

- [x] Step 1: Create the test file with this complete content:

```python
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.tools.retrieval.arxiv_tool import ArxivSearchTool


async def _test_missing_query_keeps_existing_error():
    result = await ArxivSearchTool()._execute(max_results=5)
    assert result.success is False
    assert result.error == "Missing required parameter: query"


def test_missing_query_keeps_existing_error():
    asyncio.run(_test_missing_query_keeps_existing_error())


async def _test_non_positive_max_results_is_rejected_before_request():
    tool = ArxivSearchTool()
    with patch("paper_agent.tools.retrieval.arxiv_tool.arxiv.Client") as client:
        for value in (0, -1):
            result = await tool._execute(query="agent memory", max_results=value)
            assert result.success is False
            assert result.error == "max_results must be greater than 0"
        client.assert_not_called()


def test_non_positive_max_results_is_rejected_before_request():
    asyncio.run(_test_non_positive_max_results_is_rejected_before_request())


async def _test_positive_max_results_keeps_search_path():
    fake_result = SimpleNamespace(
        published=datetime(2024, 1, 15, 12, 0),
        updated=datetime(2024, 2, 1, 8, 30),
        categories=["cs.AI", "cs.LG"],
        authors=[
            SimpleNamespace(name="Ada Lovelace"),
            SimpleNamespace(name="Alan Turing"),
        ],
        pdf_url="https://arxiv.org/pdf/2401.00001v2",
        links=[
            SimpleNamespace(href="https://arxiv.org/abs/2401.00001v2"),
            SimpleNamespace(href="https://github.com/example/paper"),
        ],
        entry_id="https://arxiv.org/abs/2401.00001v2",
        title="Deterministic Paper Retrieval",
        summary="A deterministic\npaper abstract.",
        doi="10.1234/example.0001",
        journal_ref="Example Journal, 2024",
        comment="12 pages",
        primary_category="cs.AI",
        get_short_id=lambda: "2401.00001v2",
    )

    class FakeClient:
        def results(self, search):
            assert search is not None
            return [fake_result]

    with patch(
        "paper_agent.tools.retrieval.arxiv_tool.arxiv.Client",
        return_value=FakeClient(),
    ) as client:
        result = await ArxivSearchTool()._execute(query="agent memory", max_results=3)
        assert result.success is True
        assert result.data["query"] == "agent memory"
        assert result.data["total_found"] == 1
        paper = result.data["results"][0]
        assert paper["arxiv_id"] == "2401.00001v2"
        assert paper["title"] == "Deterministic Paper Retrieval"
        assert paper["authors"] == ["Ada Lovelace", "Alan Turing"]
        assert paper["abstract"] == "A deterministic paper abstract."
        assert paper["pdf_url"] == "https://arxiv.org/pdf/2401.00001v2"
        assert paper["published_date"] == "2024-01-15"
        assert paper["categories"] == ["cs.AI", "cs.LG"]
        assert paper["version"] == "2"
        assert paper["source"] == "arxiv"
        assert paper["url"] == fake_result.entry_id
        assert paper["updated_date"] == "2024-02-01"
        assert paper["code_available_hint"] is True
        assert paper["code_url_hint"] == "https://github.com/example/paper"
        client.assert_called_once()


def test_positive_max_results_keeps_search_path():
    asyncio.run(_test_positive_max_results_keeps_search_path())


def main():
    test_missing_query_keeps_existing_error()
    test_non_positive_max_results_is_rejected_before_request()
    test_positive_max_results_keeps_search_path()
    print("paper retrieval validation tests passed")


if __name__ == "__main__":
    main()
```

- [x] Step 2: Run the new test before implementation.

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

- [x] Step 1: Insert the following check immediately after the existing query
  validation and before `max_results = min(...)`:

```python
        requested_max_results = kwargs.get("max_results", 20)
        if requested_max_results <= 0:
            return ToolResult.fail(error="max_results must be greater than 0")
```

- [x] Step 2: Keep the existing positive-value calculation unchanged:

```python
        max_results = min(requested_max_results, settings.retrieval.arxiv_max_results)
```

- [x] Step 3: Run the new validation test.

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

- [x] Step 1: Run the focused non-network regression scripts:

```bash
PYTHONPATH=src python3 examples/test_paper_retrieval_validation.py
PYTHONPATH=src python3 examples/test_b01_b02_compression.py
PYTHONPATH=src python3 examples/test_d01_d04_indexing.py
PYTHONPATH=src python3 examples/test_e01_e04_error_persistence.py
```

- [x] Step 2: Verify the repository import:

```bash
PYTHONPATH=src python3 -c "import paper_agent; print('paper_agent import: OK')"
```

Expected: every script exits with code `0`, and the import prints
`paper_agent import: OK`.

**Covers Scenario:** `paper-retrieval/Valid search request`,
`paper-retrieval/Missing query`

**Acceptance:** Focused tests and import verification all exit successfully.

### Task 4: Synchronize the legacy P06 requirement record

**Depends on:** Task 2
**Parallel group:** D

**Files:**

- Modify: `requirements/5.2_论文检索与筛选/P06_论文检索/solution.md`
- Modify: `requirements/5.2_论文检索与筛选/P06_论文检索/progress.md`
- Modify: `requirements/5.2_论文检索与筛选/P06_论文检索/blockers.md`
- Modify: `requirements/5.2_论文检索与筛选/P06_论文检索/resolutions.md`

**Steps:**

- [x] Step 1: Update `solution.md` with the 2026-08-19 implementation detail:
  `ArxivSearchTool._execute` rejects `max_results <= 0` with
  `max_results must be greater than 0` before constructing the arXiv client,
  while preserving positive values and missing-query validation.

- [x] Step 2: Add a completed item to `progress.md` stating that non-positive
  `max_results` validation and its negative tests are complete, and add the
  focused verification command and result.

- [x] Step 3: Add a resolved entry to `resolutions.md` linking the input
  validation gap to the implementation and test files.

- [x] Step 4: Keep `blockers.md` truthful: do not add a blocker for this
  completed change; preserve the existing known unresolved P06 issues.

**Covers Scenario:** `paper-retrieval/Non-positive result limit`

**Acceptance:** All four P06 documents mention the change consistently, with
`progress.md` showing completion, `resolutions.md` recording the resolution,
and `blockers.md` retaining only unresolved issues.

## Delivery

After Tasks 1-4 pass, run `ss-code-review` against the change, then commit:

```bash
git add src/paper_agent/tools/retrieval/arxiv_tool.py \
  examples/test_paper_retrieval_validation.py \
  requirements/5.2_论文检索与筛选/P06_论文检索/solution.md \
  requirements/5.2_论文检索与筛选/P06_论文检索/progress.md \
  requirements/5.2_论文检索与筛选/P06_论文检索/blockers.md \
  requirements/5.2_论文检索与筛选/P06_论文检索/resolutions.md \
  openspec/changes/validate-paper-retrieval-inputs \
  docs/plans/2026-08-19-validate-paper-retrieval-inputs.md
git commit -m "fix(paper-retrieval): validate max results"
```
