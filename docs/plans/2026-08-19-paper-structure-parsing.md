# P11 论文结构解析执行计划

> **Agent execution guide:** use the `ss-coding` skill to execute these tasks in order.

**Goal:** 从 P10 论文 artifact 提取全文和结构化章节，原子更新 `PaperArtifact` 并登记 Manifest。
**Architecture:** 使用 `pdfplumber` 做页级文本提取，使用确定性标题/证据规则构建 `PaperSection`，
通过 `StatePersistence` 原子更新已有 JSON artifact；不调用 LLM，不修改原始 PDF。
**Tech Stack:** Python, pdfplumber, Pydantic, existing StatePersistence and ToolRegistry.
**Scope:** `tools/paper_processing`、`PaperArtifact` 持久化、P11 测试和需求记录。
**Source:** `requirements/5.3_论文获取解析与翻译/P11_论文结构解析/`
**Date:** 2026-08-19
**OpenSpec Change:** `openspec/changes/add-paper-structure-parsing/`
**User-Confirmed Scope Adjustments:** 暂不实现 OCR、视觉公式恢复、翻译、代码定位和实验复现。

## File Map

- Create: `src/paper_agent/tools/paper_processing/paper_parse.py` - PDF 提取、章节识别和内容线索检测。
- Modify: `src/paper_agent/tools/paper_processing/__init__.py` - 导出解析工具。
- Modify: `src/paper_agent/tools/__init__.py` - 注册 `paper_parse`。
- Modify: `src/paper_agent/common/persistence/state_persistence.py` - 原子更新已存在的 `PaperArtifact`。
- Create: `examples/test_p11_paper_structure_parsing.py` - 正向和负向测试。
- Modify: `requirements/5.3_论文获取解析与翻译/P11_论文结构解析/solution.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P11_论文结构解析/progress.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P11_论文结构解析/resolutions.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P11_论文结构解析/blockers.md`

## Dependency Graph

```text
Task 1: Artifact 更新持久化
  -> Task 2: 确定性 PDF 解析工具
     -> Task 3: 工具注册、需求记录和回归验证
```

## Task List

### Task 1: Add atomic parsed artifact update

**Depends on:** None
**Parallel group:** A

**Files:**
- Modify: `src/paper_agent/common/persistence/state_persistence.py`
- Test: `examples/test_p11_paper_structure_parsing.py`

**Steps:**

- [x] Step 1: Write a failing test for atomic update and Manifest file registration.
- [x] Step 2: Run `PYTHONPATH=src python3 examples/test_p11_paper_structure_parsing.py` and confirm the update API is absent.
- [x] Step 3: Add `update_paper_artifact(task_id, artifact_path, artifact)` using existing atomic JSON and Manifest helpers.
- [x] Step 4: Return the updated path, propagate JSON/Manifest failures, and run the focused test.

**Covers Scenario:** `paper-acquisition/Parsed artifact is persisted`
**Acceptance:** The focused test verifies updated `sections` and Manifest registration.

### Task 2: Implement deterministic PDF structure parsing

**Depends on:** Task 1
**Parallel group:** B

**Files:**
- Create: `src/paper_agent/tools/paper_processing/paper_parse.py`
- Modify: `src/paper_agent/tools/paper_processing/__init__.py`
- Test: `examples/test_p11_paper_structure_parsing.py`

**Steps:**

- [x] Step 1: Write failing tests for heading extraction, fallback Document section, formula/table/figure/citation flags, page error recording, missing input, traversal, missing files, and persistence failure.
- [x] Step 2: Run the focused test and confirm the parser behavior fails before implementation.
- [x] Step 3: Implement safe artifact path resolution and `pdfplumber` page extraction.
- [x] Step 4: Implement numbered/whitelisted heading detection and ordered `PaperSection` construction.
- [x] Step 5: Implement deterministic evidence flags, citation extraction, parsing error recording, and structured result output.
- [x] Step 6: Run the focused test and confirm all P11 behavior tests pass.

**Covers Scenarios:** `paper-acquisition/Valid persisted PDF is parsed`, `paper-acquisition/PDF has no recognizable headings`, `paper-acquisition/A page cannot be extracted`, `paper-acquisition/Artifact path is missing`, `paper-acquisition/Artifact path escapes the task directory`, `paper-acquisition/Paper artifact or PDF is missing`, `paper-acquisition/Parsed artifact persistence fails`
**Acceptance:** `PYTHONPATH=src python3 examples/test_p11_paper_structure_parsing.py` passes all parser scenarios.

### Task 3: Register tool and update P11 records

**Depends on:** Task 2
**Parallel group:** C

**Files:**
- Modify: `src/paper_agent/tools/__init__.py`
- Modify: `requirements/5.3_论文获取解析与翻译/P11_论文结构解析/solution.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P11_论文结构解析/progress.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P11_论文结构解析/resolutions.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P11_论文结构解析/blockers.md`
- Test: `examples/test_p11_paper_structure_parsing.py`

**Steps:**

- [x] Step 1: Add a failing assertion that the default registry exposes `paper_parse`.
- [x] Step 2: Register `PaperParseTool` and update the four P11 requirement records.
- [x] Step 3: Run focused tests, P10/retrieval regressions, OpenSpec validation, and `git diff --check`.

**Covers Scenarios:** `paper-acquisition/Valid persisted PDF is parsed`, `paper-acquisition/Parsed artifact is persisted`
**Acceptance:** Registry assertion, focused tests, regressions, and `openspec validate --all --strict` pass.
