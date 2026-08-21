# P35 事件流与回复编排

**目标**：将内部执行过程转换为用户可见的进度和自然语言回复。

## 范围

- 统一事件：intent_detected、candidate_found、workflow_started、step_started、
  step_completed、artifact_created、evaluation_completed、response_ready。
- 事件持久化并支持按 session/task 查询。
- `ResponseComposer` 生成成功、失败、澄清、等待和下一步建议。
- 内部异常、密钥和宿主路径不得直接暴露。

## 验收标准

- [ ] 每个 Workflow 边界产生可关联的事件。
- [ ] 事件带 session_id、task_id、timestamp 和 correlation_id。
- [ ] 长任务可输出实时进度。
- [ ] 失败回复包含原因、状态和可执行下一步。
- [ ] 回复可引用 artifact，但不暴露内部绝对路径。
