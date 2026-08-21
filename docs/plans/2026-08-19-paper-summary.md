# P14 论文总结与解释执行计划

> **Agent execution guide:** use the `ss-coding` skill to execute these tasks in order.

**Goal:** 校验并持久化带章节证据的结构化论文总结。
**Architecture:** Research Agent 生成 summary JSON，`PaperSummaryTool` 做字段和 section
证据校验，复用 `StatePersistence.update_paper_artifact()` 原子更新 artifact。
**Tech Stack:** Python, Pydantic, existing PaperArtifact, ToolRegistry and StatePersistence.
**Scope:** `PaperArtifact`、`tools/paper_processing`、解析阶段 prompt、P14 测试和需求记录。
**Source:** `requirements/5.3_论文获取解析与翻译/P14_论文总结与解释/`
**Date:** 2026-08-19
**OpenSpec Change:** `openspec/changes/add-paper-summary/`
**User-Confirmed Scope Adjustments:** 不实现外部知识补充、语义最终评估和复现功能。

## File Map

- Modify: `src/paper_agent/common/models/paper_artifact.py`
- Create: `src/paper_agent/tools/paper_processing/paper_summary.py`
- Modify: `src/paper_agent/tools/paper_processing/__init__.py`
- Modify: `src/paper_agent/tools/__init__.py`
- Modify: `prompts/research_agent/phases/paper_parsing.txt`
- Create: `examples/test_p14_paper_summary.py`
- Modify: `requirements/5.3_论文获取解析与翻译/P14_论文总结与解释/solution.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P14_论文总结与解释/progress.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P14_论文总结与解释/resolutions.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P14_论文总结与解释/blockers.md`
- Modify: `requirements/requirements_summary.md`

## Dependency Graph

```text
P11 sections + P13 translation
  -> Task 1: summary model/tool tests
  -> Task 2: PaperSummaryTool
  -> Task 3: registry/prompt/docs/regression
```

## Task List

### Task 1: Define evidence-linked summary tests

**Depends on:** None
**Parallel group:** A

**Files:**
- Create: `examples/test_p14_paper_summary.py`

**Steps:**

- [x] Step 1: Write failing tests for valid summary, empty optional lists, unknown evidence sections, invalid fields, unparsed artifact, persistence failure, and registry registration.
- [x] Step 2: Run `PYTHONPATH=src python3 examples/test_p14_paper_summary.py` and confirm the import fails before implementation.

**Covers Scenarios:** `paper-acquisition/Valid summary with section evidence is persisted`, `paper-acquisition/Optional summary lists are empty`, `paper-acquisition/Evidence references an unknown section`, `paper-acquisition/Summary field is invalid`, `paper-acquisition/Artifact is not parsed`, `paper-acquisition/Summary persistence fails`
**Acceptance:** The test command fails only because `PaperSummaryTool` has not been implemented.

### Task 2: Implement evidence-linked summary persistence

**Depends on:** Task 1
**Parallel group:** B

**Files:**
- Modify: `src/paper_agent/common/models/paper_artifact.py`
- Create: `src/paper_agent/tools/paper_processing/paper_summary.py`
- Test: `examples/test_p14_paper_summary.py`

**Steps:**

- [x] Step 1: Add backward-compatible `summary_evidence` to `PaperArtifact`.
- [x] Step 2: Implement safe artifact loading and parsed-artifact validation.
- [x] Step 3: Validate required string/list fields, optional empty lists, and evidence section IDs.
- [x] Step 4: Update summary fields and evidence mapping only after all validation passes.
- [x] Step 5: Call `update_paper_artifact()` and propagate persistence errors.
- [x] Step 6: Run the focused tests and confirm all summary scenarios pass.

**Covers Scenarios:** `paper-acquisition/Valid summary with section evidence is persisted`, `paper-acquisition/Optional summary lists are empty`, `paper-acquisition/Evidence references an unknown section`, `paper-acquisition/Summary field is invalid`, `paper-acquisition/Artifact is not parsed`, `paper-acquisition/Summary persistence fails`
**Acceptance:** `PYTHONPATH=src python3 examples/test_p14_paper_summary.py` passes all tests.

### Task 3: Register, prompt, document, and regress

**Depends on:** Task 2
**Parallel group:** C

**Files:**
- Modify: `src/paper_agent/tools/paper_processing/__init__.py`
- Modify: `src/paper_agent/tools/__init__.py`
- Modify: `prompts/research_agent/phases/paper_parsing.txt`
- Modify: `requirements/5.3_论文获取解析与翻译/P14_论文总结与解释/solution.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P14_论文总结与解释/progress.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P14_论文总结与解释/resolutions.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P14_论文总结与解释/blockers.md`
- Modify: `requirements/requirements_summary.md`
- Test: `examples/test_p14_paper_summary.py`

**Steps:**

- [x] Step 1: Register `paper_summary` and update the parsing prompt with the summary/evidence JSON contract.
- [x] Step 2: Record implementation status, constraints, and verification commands in P14 docs.
- [x] Step 3: Run P14, P13, P12, P11, P10, retrieval, OpenSpec, compile, and diff checks.

**Covers Scenarios:** `paper-acquisition/Valid summary with section evidence is persisted`, `paper-acquisition/Summary persistence fails`
**Acceptance:** Registry, focused tests, regressions, `openspec validate --all --strict`, and `git diff --check` pass.
