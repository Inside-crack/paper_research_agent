# P34 决策

| 决策 | 结论 |
|------|------|
| R34-1 | 明确论文 ID/URL 可跳过确认；检索候选默认必须确认 |
| R34-2 | pause/cancel 采用协作式控制，在安全点生效，不强制中断当前调用 |
| R34-3 | `Orchestrator.start_task()` 保持兼容，新增 `create_task()` 支持确认后启动 |
| R34-4 | TaskState 增加可选 session_id 和生命周期字段，旧 checkpoint 使用默认值恢复 |
| R34-5 | 明确 arXiv ID/URL 的 `process_selected_paper` 请求跳过候选确认，直接创建并运行 Task |
