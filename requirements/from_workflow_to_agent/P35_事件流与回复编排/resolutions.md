# P35 决策

| 决策 | 结论 |
|------|------|
| R35-1 | session_id 和 correlation_id 必填；Task 创建前事件允许 task_id 为空，Workflow 事件必须关联 task_id |
| R35-2 | CLI 与未来 HTTP API 统一使用 AgentEvent 的 JSON 序列化格式 |
| R35-3 | Task 创建前事件持久化到 `_conversation/logs/events.jsonl`，Task 创建后事件按 task_id 分目录持久化 |
| R35-4 | EventStore、EventPublisher 和 ResponseComposer 统一执行敏感信息与宿主路径过滤 |
