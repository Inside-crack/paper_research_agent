# P31 进度

**状态**：模型与 Store 已完成，审查问题已修复
**完成度**：Task 1（模型与 JSON 持久化）100%

- [x] ConversationSession 模型
- [x] ConversationMessage 模型
- [x] ConversationContext 持久化
- [x] session/task/artifact 关联测试
- [x] append_message 双文件失败回滚、原始/回滚错误传播和 failure test
- [x] 拒绝 sessions 根目录 symlink，并保留 session 子目录与文件路径校验
- [x] 以 context.active_task_id 为权威值，同步 session.active_task_id；bind_task 两边保持一致
- [x] 验证：P31 12/12、P30 T1 25/25、compileall、OpenSpec strict、diff check

## 审查边界

- `append_message` 使用旧文件 bytes 快照和原子恢复，第二步失败时恢复第一步，并在恢复失败时同时传播原始错误与回滚错误。
- 当前实现只对单进程内的读-改-写提供尽力的快照变更检测；跨线程/跨进程并发协调不属于 P31 本次范围，不承诺通用并发写入序列化。

Router、Capability Registry、Chat CLI/API 等后续范围仍未实现。
