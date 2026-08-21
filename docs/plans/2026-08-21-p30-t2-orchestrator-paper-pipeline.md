# P30 T2：Orchestrator 固定论文处理链路

## 目标

在不新增顶层 `TaskPhase` 的前提下，让 `PAPER_PARSING` 阶段由 Orchestrator
固定执行 `download -> parse -> glossary -> translate -> summary`，并在每个
步骤边界从持久化产物读取真实输入。

## 约束

- 不改变 P10-P14 工具的输入输出契约。
- 不自动切换候选论文，固定使用检索结果第一篇。
- 已通过的子步骤恢复时不重跑。
- 子步骤状态使用 P30 T1 的 `TaskState.paper_processing_steps` 和 Manifest。
- 本任务只实现顺序执行和产物传递；子步骤独立 Evaluation/REVISE 属于 T3。

### Task 1

- [ ] 实现 `PAPER_PARSING` 专用 Orchestrator 执行路径。
- [ ] 从 `paper_retrieval` 结果固定选择第一篇论文。
- [ ] 将每一步的真实输出映射为下一步输入：
  - download -> artifact_path
  - parse -> sections/full_text_original
  - glossary -> glossary
  - translate -> translated sections
  - summary -> evidence
- [ ] 每个子步骤开始、完成、失败时更新 TaskState 和 Manifest。
- [ ] 从 checkpoint 恢复时跳过已 PASS 子步骤。
- [ ] 增加正常流程、空候选、前置失败、恢复和数据传递测试。

**Files:**

- `src/paper_agent/orchestrator/orchestrator.py`
- `examples/test_p30_t2_orchestrator_paper_pipeline.py`
- `requirements/5.3_论文获取解析与翻译/P30_产物驱动论文处理工作流/progress.md`
