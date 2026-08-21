# P13 分章节翻译执行计划

> **Agent execution guide:** use the `ss-coding` skill to execute these tasks in order.

**Goal:** 校验并原子持久化 P11 论文各章节译文。
**Architecture:** Research Agent 生成译文候选，`PaperTranslateTool` 做章节覆盖、数字/引用/
公式/术语保护校验，复用 `StatePersistence.update_paper_artifact()` 更新 artifact。
**Tech Stack:** Python, Pydantic, existing PaperArtifact, ToolRegistry and StatePersistence.
**Scope:** `tools/paper_processing`、解析阶段 prompt、P13 测试和需求记录。
**Source:** `requirements/5.3_论文获取解析与翻译/P13_分章节翻译/`
**Date:** 2026-08-19
**OpenSpec Change:** `openspec/changes/add-paper-translation/`
**User-Confirmed Scope Adjustments:** 不实现外部翻译服务、OCR、总结和复现功能。

## File Map

- Create: `src/paper_agent/tools/paper_processing/paper_translate.py`
- Modify: `src/paper_agent/tools/paper_processing/__init__.py`
- Modify: `src/paper_agent/tools/__init__.py`
- Modify: `prompts/research_agent/phases/paper_parsing.txt`
- Create: `examples/test_p13_paper_translation.py`
- Modify: `requirements/5.3_论文获取解析与翻译/P13_分章节翻译/solution.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P13_分章节翻译/progress.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P13_分章节翻译/resolutions.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P13_分章节翻译/blockers.md`
- Modify: `requirements/requirements_summary.md`

## Dependency Graph

```text
P11 sections + P12 glossary
  -> Task 1: translation validation tests
  -> Task 2: PaperTranslateTool
  -> Task 3: registry/prompt/docs/regression
```

## Task List

### Task 1: Define translation validation tests

**Depends on:** None
**Parallel group:** A

**Files:**
- Create: `examples/test_p13_paper_translation.py`

**Steps:**

- [x] Step 1: Write failing tests for complete translation, missing/duplicate/unknown sections, protected numbers/citations/formulas/glossary, empty input, unparsed artifact, persistence failure, and registry registration.
- [x] Step 2: Run `PYTHONPATH=src python3 examples/test_p13_paper_translation.py` and confirm the import fails before implementation.

**Covers Scenarios:** `paper-acquisition/All sections have valid translations`, `paper-acquisition/A section is missing or duplicated`, `paper-acquisition/An unknown section is provided`, `paper-acquisition/Protected content is preserved`, `paper-acquisition/Numeric or citation content is changed`, `paper-acquisition/Formula or glossary content is lost`, `paper-acquisition/Translation persistence fails`
**Acceptance:** The test command fails only because `PaperTranslateTool` has not been implemented.

### Task 2: Implement protected section translation persistence

**Depends on:** Task 1
**Parallel group:** B

**Files:**
- Create: `src/paper_agent/tools/paper_processing/paper_translate.py`
- Test: `examples/test_p13_paper_translation.py`

**Steps:**

- [x] Step 1: Implement safe artifact loading and parsed-section validation.
- [x] Step 2: Validate exact section coverage and non-empty translation text.
- [x] Step 3: Validate numeric tokens, citation tokens, formula markers, and applicable glossary targets.
- [x] Step 4: Update section translations and concatenated full translation only after all validations pass.
- [x] Step 5: Call `update_paper_artifact()` and propagate persistence errors.
- [x] Step 6: Run the focused tests and confirm all translation scenarios pass.

**Covers Scenarios:** `paper-acquisition/All sections have valid translations`, `paper-acquisition/A section is missing or duplicated`, `paper-acquisition/An unknown section is provided`, `paper-acquisition/Protected content is preserved`, `paper-acquisition/Numeric or citation content is changed`, `paper-acquisition/Formula or glossary content is lost`, `paper-acquisition/Translation persistence fails`
**Acceptance:** `PYTHONPATH=src python3 examples/test_p13_paper_translation.py` passes all tests.

### Task 3: Register, prompt, document, and regress

**Depends on:** Task 2
**Parallel group:** C

**Files:**
- Modify: `src/paper_agent/tools/paper_processing/__init__.py`
- Modify: `src/paper_agent/tools/__init__.py`
- Modify: `prompts/research_agent/phases/paper_parsing.txt`
- Modify: `requirements/5.3_论文获取解析与翻译/P13_分章节翻译/solution.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P13_分章节翻译/progress.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P13_分章节翻译/resolutions.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P13_分章节翻译/blockers.md`
- Modify: `requirements/requirements_summary.md`
- Test: `examples/test_p13_paper_translation.py`

**Steps:**

- [x] Step 1: Register `paper_translate` and update the parsing prompt with the translation JSON contract.
- [x] Step 2: Record implementation status, constraints, and verification commands in P13 docs.
- [x] Step 3: Run P13, P12, P11, P10, retrieval, OpenSpec, compile, and diff checks.

**Covers Scenarios:** `paper-acquisition/All sections have valid translations`, `paper-acquisition/Translation persistence fails`
**Acceptance:** Registry, focused tests, regressions, `openspec validate --all --strict`, and `git diff --check` pass.
