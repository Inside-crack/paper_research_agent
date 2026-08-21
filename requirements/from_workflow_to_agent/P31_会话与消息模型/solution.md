# P31 会话与消息模型

**目标**：建立独立于 `TaskState` 的多轮会话数据模型。

## 范围

- `ConversationSession`：session_id、状态、当前 task、selected_paper、context_summary。
- `ConversationMessage`：message_id、session_id、role、content、时间、artifact 引用。
- `ConversationContext`：当前意图、候选论文、选中章节、用户偏好和活动任务。
- 原子持久化、checkpoint 兼容和按 session 查询。

## 不做

- 不实现意图识别；
- 不实现 Chat CLI/API；
- 不修改 P10-P14 工具。

## 验收标准

- [ ] 同一 session 可追加用户和 Agent 消息。
- [ ] session 可关联和解除 task。
- [ ] selected_paper、artifact 引用和 context summary 可恢复。
- [ ] 损坏消息或越权 session 访问会报错。
- [ ] 旧 TaskState 无 session 字段时仍可读取。
