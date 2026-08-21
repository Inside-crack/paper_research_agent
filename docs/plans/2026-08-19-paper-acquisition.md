# P10 全文与版本获取执行计划

> **Agent execution guide:** use the `ss-coding` skill to execute these tasks in order.

**Goal:** 获取并校验 arXiv 论文 PDF，将 PDF 与 `PaperArtifact` 原子持久化并登记任务 Manifest。
**Architecture:** 新增独立 `paper_download` 工具，复用现有 arXiv 元数据工具、原子 JSON 写入和
Manifest 更新接口；工具只返回结构化 artifact 引用，不把下载实现塞入 Orchestrator。
**Tech Stack:** Python 3.10+, Pydantic, httpx, existing ToolRegistry and StatePersistence.
**Scope:** `src/paper_agent/tools/paper_processing/`、现有文件工具/持久化接口、P10 文档和 examples 测试。
**Source:** `requirements/5.3_论文获取解析与翻译/P10_全文与版本获取/`
**Date:** 2026-08-19
**OpenSpec Change:** `openspec/changes/add-paper-download/`
**User-Confirmed Scope Adjustments:** 只支持 arXiv PDF；DOI、HTML、源码包和人工确认不在本次范围。

## File Map

- Create: `src/paper_agent/tools/paper_processing/paper_download.py` - 输入规范化、下载、PDF 校验和 artifact 生成。
- Modify: `src/paper_agent/tools/paper_processing/__init__.py` - 导出工具。
- Modify: `src/paper_agent/tools/__init__.py` - 注册 `paper_download`。
- Modify: `src/paper_agent/common/persistence/state_persistence.py` - 提供论文文件登记所需的持久化入口。
- Create: `examples/test_p10_paper_download.py` - 正向、非法输入、非 PDF、原子写和 Manifest 失败测试。
- Modify: `requirements/5.3_论文获取解析与翻译/P10_全文与版本获取/solution.md` - 记录方案。
- Modify: `requirements/5.3_论文获取解析与翻译/P10_全文与版本获取/progress.md` - 记录进度和验收。
- Modify: `requirements/5.3_论文获取解析与翻译/P10_全文与版本获取/resolutions.md` - 记录决策。
- Modify: `requirements/5.3_论文获取解析与翻译/P10_全文与版本获取/blockers.md` - 记录实际阻塞。

## Dependency Graph

```text
Task 1: 持久化登记接口
  -> Task 2: paper_download 工具契约和实现
     -> Task 3: registry 集成与端到端验证
```

## Task List

### Task 1: Add atomic paper artifact registration

**Depends on:** None
**Parallel group:** A

**Files:**
- Modify: `src/paper_agent/common/persistence/state_persistence.py`
- Test: `examples/test_p10_paper_download.py`

**Steps:**

- [x] Step 1: Write a failing test proving a PDF and `PaperArtifact` are registered in the task Manifest.
- [x] Step 2: Run `PYTHONPATH=src python3 examples/test_p10_paper_download.py` and confirm the registration test fails because the API is absent.
- [x] Step 3: Add the smallest persistence method that writes the JSON atomically and updates the task Manifest using existing helpers.
- [x] Step 4: Run the focused test and confirm the registration assertion passes.

**Covers Scenario:** `paper-acquisition/Metadata is persisted after download`
**Acceptance:** `PYTHONPATH=src python3 examples/test_p10_paper_download.py` reports the registration test as passed.

### Task 2: Implement validated arXiv PDF acquisition

**Depends on:** Task 1
**Parallel group:** B

**Files:**
- Create: `src/paper_agent/tools/paper_processing/paper_download.py`
- Modify: `src/paper_agent/tools/paper_processing/__init__.py`
- Test: `examples/test_p10_paper_download.py`

**Steps:**

- [x] Step 1: Add failing tests for valid identifier, candidate URL, missing identifier, non-PDF response, empty response, and temporary-file cleanup.
- [x] Step 2: Run the focused test and confirm all new behavior tests fail before implementation.
- [x] Step 3: Implement input normalization, arXiv metadata lookup, HTTP download, `%PDF-` and non-empty validation, temporary-file replacement, and structured `PaperArtifact` creation.
- [x] Step 4: Preserve the original network or validation error in `ToolResult.fail` and never return success when persistence fails.
- [x] Step 5: Run the focused test and confirm all P10 behavior tests pass.

**Covers Scenarios:** `paper-acquisition/Valid arXiv identifier is acquired`, `paper-acquisition/Candidate PDF URL is acquired`, `paper-acquisition/Input has no usable paper identifier`, `paper-acquisition/Response is not a PDF`, `paper-acquisition/Interrupted or invalid download`
**Acceptance:** `PYTHONPATH=src python3 examples/test_p10_paper_download.py` reports all P10 behavior tests as passed.

### Task 3: Register the tool and update legacy requirement records

**Depends on:** Task 2
**Parallel group:** C

**Files:**
- Modify: `src/paper_agent/tools/__init__.py`
- Modify: `requirements/5.3_论文获取解析与翻译/P10_全文与版本获取/solution.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P10_全文与版本获取/progress.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P10_全文与版本获取/resolutions.md`
- Modify: `requirements/5.3_论文获取解析与翻译/P10_全文与版本获取/blockers.md`
- Test: `examples/test_p10_paper_download.py`

**Steps:**

- [x] Step 1: Add a failing registry assertion that `get_default_registry()` exposes `paper_download`.
- [x] Step 2: Run the focused test and confirm the registry assertion fails.
- [x] Step 3: Register `PaperDownloadTool` and update the four P10 records with implemented behavior and remaining blockers.
- [x] Step 4: Run import, focused tests, regression examples, OpenSpec validation, and `git diff --check`.

**Covers Scenarios:** `paper-acquisition/Valid arXiv identifier is acquired`, `paper-acquisition/Manifest persistence fails`
**Acceptance:** `PYTHONPATH=src python3 -c "from paper_agent.tools import get_default_registry; assert 'paper_download' in get_default_registry().list_tools()"` succeeds, and `openspec validate --all --strict` succeeds.
