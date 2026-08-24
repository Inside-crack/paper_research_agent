# From Workflow To Agent 进度跟踪

**状态**：P31/P32 已完成，P33 抽离工作进行中
**完成度**：P31 100%，P32 100%，P33 100%，P34/P35 待开始，P36 最小 CLI 已完成
**最后更新**：2026-08-24

## 已有基础

- [x] 双 Agent + Orchestrator 执行内核
- [x] TaskState、Manifest、Checkpoint
- [x] P10-P14 论文处理能力
- [x] P30 T1 子步骤状态和持久化
- [x] P30 T2 产物驱动论文处理顺序
- [x] P32 Capability Adapter、Registry 和混合意图路由
- [x] P32 路由安全、评测与可观测性

## 待实现

| 需求 | 内容 | 状态 |
|------|------|------|
| P31 | Conversation Session 与消息模型 | 已完成 |
| P32 | Capability 契约、Adapter、Registry 与 Intent Router | 已完成 |
| P33 | PaperProcessingWorkflow 抽离 | 方案讨论中 |
| P34 | 对话应用服务与用户交互状态 | 待开始 |
| P35 | 事件流与 ResponseComposer | 待开始 |
| P36 | Chat CLI 与 HTTP API | 最小 Chat CLI 已完成，HTTP/API 待开始 |

## 当前边界

本目录记录从工作流向对话 Agent 演进的架构需求与实现进度；各子目录的
`progress.md` 记录对应模块的详细状态。
