# P33 Workflow 模块抽离

**目标**：将论文业务流程从 Orchestrator 中抽成可复用 Workflow。

## 范围

- 新增 `PaperProcessingWorkflow`。
- 接管 P30 T2 的 `download -> parse -> glossary -> translate -> summary`。
- 定义 Workflow 输入、输出、依赖、恢复和失败契约。
- Orchestrator 收敛为生命周期控制器。
- 保持旧 `TaskState`、Manifest、Checkpoint 和 P10-P14 工具兼容。

## 验收标准

- [x] P30 T2 流程通过 Workflow 执行。
- [x] Orchestrator 不再包含论文业务细节分支。
- [x] Orchestrator 通过可注入的 `PaperProcessingWorkflow` 边界调用论文流程。
- [x] Workflow 可单独测试和恢复。
- [x] 已通过子步骤不重复执行。
- [x] Workflow 失败不会伪造成功产物。
