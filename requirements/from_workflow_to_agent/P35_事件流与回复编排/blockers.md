# P35 卡点

| 卡点 | 描述 | 状态 |
|------|------|------|
| B35-1 | 需要确定 CLI 与 HTTP 共同使用的事件序列化格式 | 已解决：统一使用 AgentEvent.model_dump(mode="json") |
| B35-2 | `intent_detected`、`candidate_found` 发生在 Task 创建前，但 R35-1 要求事件必须有 task_id | 已解决：Task 创建前允许 task_id 为空 |
