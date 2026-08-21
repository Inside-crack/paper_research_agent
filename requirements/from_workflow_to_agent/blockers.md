# From Workflow To Agent 卡点记录

**活跃卡点**：5  
**最后更新**：2026-08-21

| 卡点 | 描述 | 影响 | 状态 |
|------|------|------|------|
| B01 | 缺少 ConversationSession 和 Message 模型 | 无法支持多轮对话 | 开放 |
| B02 | 缺少 Capability Adapter、Intent Router 和 Capability Registry | 已有 Tool 尚未成为可复用的 Agent 能力 | 开放 |
| B03 | Orchestrator 包含论文业务流程 | 新能力扩展成本高 | 开放 |
| B04 | 缺少 ConversationApplicationService | Router 决策没有统一执行者 | 开放 |
| B05 | 缺少 WAITING_USER_INPUT 和确认状态 | 无法支持 P09 和交互式任务 | 开放 |
| B06 | 缺少 Chat Gateway、事件流和自然语言响应 | 用户只能看到一次性 JSON | 开放 |
