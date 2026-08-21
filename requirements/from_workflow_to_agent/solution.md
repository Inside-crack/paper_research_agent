# From Workflow To Agent：架构需求总览

本文件只记录总体背景、需求依赖和拆分原则。每个可实现需求必须进入独立目录，
避免把“对话机器人”作为一个无法验收的大需求。

## 当前判断

项目当前是任务型论文研究工作流：

```text
一次任务 -> Orchestrator -> Research Agent -> Tools -> Evaluation -> JSON/artifacts
```

已有执行内核包括：

- Research Agent、Evaluation Agent、Orchestrator；
- TaskState、Manifest、Checkpoint、上下文管理和错误持久化；
- P05-P08 论文检索；
- P10-P14 论文获取、解析、术语表、翻译和总结；
- P30 T1 子步骤状态持久化；
- P30 T2 产物驱动的 P10-P14 固定执行。

当前缺少的是会话层、能力路由层、用户交互状态和面向用户的输出层。

## 独立需求拆分

| 需求 | 目标 | 依赖 | 优先级 | 目录 |
|------|------|------|--------|------|
| P31 | 会话、消息和对话上下文 | 无 | P0 | [P31](P31_会话与消息模型/) |
| P32 | 能力契约、Adapter、Registry 与 Intent Router | P31 | P0 | [P32](P32_能力注册与意图路由/) |
| P33 | PaperProcessingWorkflow 抽离 | P32 | P0 | [P33](P33_Workflow模块抽离/) |
| P34 | 对话应用服务与用户交互状态 | P31-P33 | P0 | [P34](P34_用户交互状态/) |
| P35 | 事件流与 ResponseComposer | P31、P33、P34 | P1 | [P35](P35_事件流与回复编排/) |
| P36 | Chat CLI 与 HTTP API | P31、P34、P35 | P1 | [P36](P36_对话入口/) |

## 拆分原则

- 每个需求有独立输入输出契约、验收测试和恢复策略。
- P31-P36 不改变 P10-P14 工具契约。
- 已有 Tool 必须先通过 Capability Adapter 暴露为完整能力单元，不能让 Router 直接拼接 Tool 参数。
- 新增能力必须声明输入、输出和前置条件，不能让 LLM 猜 artifact 路径或状态。
- 保留现有 Task/Manifest/Checkpoint，逐步增加会话相关数据。
- 先完成会话和能力执行契约，再抽离 Workflow，接着打通应用服务，最后提供用户入口。

## 目标架构

```text
Conversation Gateway
  -> Conversation Manager
  -> Intent Router
  -> Capability Registry / Preconditions
  -> ConversationApplicationService
  -> Capability Adapter / Workflow
  -> Deterministic Tool
  -> Artifact / Evaluation / Persistence
  -> Event / Response Composer
```

核心职责：

```text
Conversation Manager：管理用户交流
Intent Router：识别意图和参数
Capability：声明业务能力和前置条件
Workflow：处理动态依赖和顺序
Tool：执行确定性动作
Orchestrator：管理生命周期和恢复
Evaluation：判断结果可信度
ResponseComposer：生成用户可理解的回复
```
