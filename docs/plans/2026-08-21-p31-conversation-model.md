# P31：会话与消息模型

## 目标

为对话 Agent 建立独立于 `TaskState` 的会话、消息和上下文模型，并提供基于现有
原子 JSON 机制的最小持久化接口。

## 范围

- `ConversationSession`
- `ConversationMessage`
- `ConversationContext`
- `ConversationStore`
- session、message、task、selected_paper 和 artifact 引用的恢复

## 不做

- Intent Router / Capability Registry；
- Chat CLI / HTTP API；
- 多用户鉴权；
- SQLite/ORM；
- 长期记忆检索；
- 修改 P10-P14 和 Orchestrator。

### Task 1

- [ ] 新增会话、消息、上下文模型。
- [ ] 新增 JSON 会话存储接口。
- [ ] 覆盖创建、追加消息、更新上下文、恢复和错误路径。
- [ ] 保持旧 TaskState、Manifest、Checkpoint 兼容。

**Files:**

- `src/paper_agent/common/models/conversation.py`
- `src/paper_agent/common/models/__init__.py`
- `src/paper_agent/common/persistence/conversation_store.py`
- `src/paper_agent/common/persistence/__init__.py`
- `examples/test_p31_conversation_model.py`
- `requirements/from_workflow_to_agent/P31_会话与消息模型/progress.md`
