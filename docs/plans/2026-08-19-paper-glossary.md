# P12 术语表生成执行计划

> **Agent execution guide:** use the `ss-coding` skill to execute these tasks in order.

**Goal:** 校验并持久化 P11 论文原文中的中英文术语映射。
**Architecture:** Research Agent 生成候选 JSON，`PaperGlossaryTool` 做确定性证据校验、
去重和排序，复用 `StatePersistence.update_paper_artifact()` 原子更新 artifact。
**Tech Stack:** Python, Pydantic, existing PaperArtifact, ToolRegistry and StatePersistence.
**Scope:** `tools/paper_processing`、解析阶段 prompt、P12 测试和需求记录。
**Source:** `requirements/5.3_论文获取解析与翻译/P12_术语表生成/`
**Date:** 2026-08-19
**OpenSpec Change:** `openspec/changes/add-paper-glossary/`
**User-Confirmed Scope Adjustments:** 不实现外部翻译服务、全文翻译和总结。

## File Map

- Create: `src/paper_agent/tools/paper_processing/paper_glossary.py`
- Modify: `src/paper_agent/tools/paper_processing/__init__.py`
- Modify: `src/paper_agent/tools/__init__.py`
- Modify: `prompts/research_agent/phases/paper_parsing.txt`
- Create: `examples/test_p12_paper_glossary.py`
- Modify: `requirements/5.3_论文获取解析与翻译/P12_术语表生成/solution.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P12_术语表生成/progress.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P12_术语表生成/resolutions.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P12_术语表生成/blockers.md`
- Modify: `requirements/requirements_summary.md`

## Dependency Graph

```text
P11 PaperArtifact
  -> Task 1: glossary validation/persistence tests
  -> Task 2: PaperGlossaryTool
  -> Task 3: registry/prompt/docs/regression
```

## Task List

### Task 1: Define glossary validation tests

**Depends on:** None
**Parallel group:** A

**Files:**
- Create: `examples/test_p12_paper_glossary.py`

**Steps:**

- [x] Step 1: Write failing tests for valid terms, duplicate terms, empty glossary, missing evidence, invalid fields, unparsed artifact, persistence failure, and registry registration.
- [x] Step 2: Run `PYTHONPATH=src python3 examples/test_p12_paper_glossary.py` and confirm the import fails before implementation.

**Covers Scenarios:** `paper-acquisition/Valid terminology candidates are persisted`, `paper-acquisition/Duplicate source terms are provided`, `paper-acquisition/No terminology candidates are found`, `paper-acquisition/Source term has no paper evidence`, `paper-acquisition/Candidate fields are invalid`, `paper-acquisition/Artifact is not parsed`, `paper-acquisition/Glossary persistence fails`
**Acceptance:** The test command fails only because `PaperGlossaryTool` has not been implemented.

### Task 2: Implement validated glossary persistence

**Depends on:** Task 1
**Parallel group:** B

**Files:**
- Create: `src/paper_agent/tools/paper_processing/paper_glossary.py`
- Test: `examples/test_p12_paper_glossary.py`

**Steps:**

- [x] Step 1: Implement safe task-relative artifact loading and `PaperArtifact` validation.
- [x] Step 2: Reject missing original text, empty source/target terms, confidence outside `[0, 1]`, and terms absent from original text.
- [x] Step 3: Normalize terms, keep the highest-confidence duplicate, sort deterministically, and construct `TermEntry` objects.
- [x] Step 4: Call `update_paper_artifact()` and propagate persistence errors without reporting success.
- [x] Step 5: Run the focused tests and confirm all glossary scenarios pass.

**Covers Scenarios:** `paper-acquisition/Valid terminology candidates are persisted`, `paper-acquisition/Duplicate source terms are provided`, `paper-acquisition/No terminology candidates are found`, `paper-acquisition/Source term has no paper evidence`, `paper-acquisition/Candidate fields are invalid`, `paper-acquisition/Artifact is not parsed`, `paper-acquisition/Glossary persistence fails`
**Acceptance:** `PYTHONPATH=src python3 examples/test_p12_paper_glossary.py` passes all tests.

### Task 3: Register, prompt, document, and regress

**Depends on:** Task 2
**Parallel group:** C

**Files:**
- Modify: `src/paper_agent/tools/paper_processing/__init__.py`
- Modify: `src/paper_agent/tools/__init__.py`
- Modify: `prompts/research_agent/phases/paper_parsing.txt`
- Modify: `requirements/5.3_论文获取解析与翻译/P12_术语表生成/solution.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P12_术语表生成/progress.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P12_术语表生成/resolutions.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P12_术语表生成/blockers.md`
- Modify: `requirements/requirements_summary.md`
- Test: `examples/test_p12_paper_glossary.py`

**Steps:**

- [x] Step 1: Register `paper_glossary` and update the parsing prompt with the candidate JSON contract.
- [x] Step 2: Record implementation status, constraints, and verification commands in P12 docs.
- [x] Step 3: Run P12, P11, P10, retrieval, OpenSpec, compile, and diff checks.

**Covers Scenarios:** `paper-acquisition/Valid terminology candidates are persisted`, `paper-acquisition/Glossary persistence fails`
**Acceptance:** Registry, focused tests, regressions, `openspec validate --all --strict`, and `git diff --check` pass.
