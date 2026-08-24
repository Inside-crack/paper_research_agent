# T32-4 复杂意图识别与路由

## 目标

在现有确定性关键词路由之上，增加可校验、可澄清、可读取会话上下文的
复杂意图识别能力，使系统能够处理：

```text
“下载刚才检索结果中的第二篇”
“解析这篇论文并生成术语表”
“只翻译方法和实验部分”
“继续完成刚才的论文处理”
```

T32-4 只负责生成经过校验的 `IntentDecision`，不直接执行 Tool，
不负责跨步骤 Workflow 的生命周期管理。

## 当前基础

已完成：

```text
六个 Capability Adapter
CapabilityRegistry
Capability-specific arguments
确定性 IntentRouter
```

确定性路由仍然是第一优先级：

```text
明确命令、明确 ID、明确路径
  -> DeterministicIntentRouter

模糊表达、指代、省略、组合意图
  -> LLM IntentRouter
```

## 子需求总表

| 编号 | 子需求 | 目标 | 依赖 | 状态 |
|------|--------|------|------|------|
| T32-4.0 | Intent Schema 完整化 | 定义意图、能力、参数和澄清契约 | T32-3 | 已完成 |
| T32-4.1 | Capability Catalog | 为 LLM 提供受控能力目录和输入 Schema | T32-4.0、Registry | 已完成 |
| T32-4.2 | Router Provider 抽象 | 隔离 LLM 客户端和 Router 编排 | T32-4.0 | 已完成 |
| T32-4.3 | 上下文投影 | 将消息历史和 Session Context 转为只读 Router 输入 | T32-4.0、P31 | 已完成 |
| T32-4.4 | LLM 结构化决策 | 生成严格 JSON 格式的 IntentDecision | T32-4.1、T32-4.2 | 已完成 |
| T32-4.5 | Schema 与能力校验 | 防止非法、越权或不可执行决策 | T32-4.1、T32-4.4 | 已完成 |
| T32-4.6 | 参数归一化与前置条件 | 将自然语言参数转为业务参数并检查缺失项 | T32-4.5、Preconditions | 已完成 |
| T32-4.7 | 混合路由策略 | 确定性路由优先，LLM 处理复杂表达 | T32-4.3、T32-4.6 | 已完成 |
| T32-4.8 | 澄清与低置信度策略 | 统一处理不确定、缺参和冲突意图 | T32-4.5、T32-4.7 | 已完成 |
| T32-4.9 | Workflow 意图映射 | 将组合意图映射到受控 Workflow | T32-4.7、P33 | 已完成 |
| T32-4.10 | 安全与执行边界 | 限制能力集合、参数和调用权限 | T32-4.5 | 已完成 |
| T32-4.11 | 评测与可观测性 | 验证准确性、负向行为和决策原因 | T32-4.7、T32-4.8 | 部分完成 |

## T32-4.0 Intent Schema 完整化

`IntentDecision` 至少包含：

```text
matched: bool
intent: str | None
capability_name: str | None
execution_kind: tool | workflow
confidence: float
arguments: dict
missing_arguments: list[str]
references: list[ContextReference]
clarification_question: str | None
reason: str | None
source: deterministic | llm | fallback
```

约束：

- `capability_name` 必须与 Registry 中的能力一致；
- `arguments` 只能包含对应能力允许的字段；
- `matched=false` 时不得产生可执行决策；
- 缺少必填参数时必须返回 `missing_arguments`；
- 低置信度时必须进入澄清，不得直接执行；
- `references` 只描述上下文引用，不直接携带未验证的文件路径。

## T32-4.1 Capability Catalog

为每个可路由能力提供：

```text
name
description
execution_kind
input_schema
required_arguments
preconditions
confirmation_required
allowed_intents
```

Catalog 只从 Registry 和 Capability 声明生成，不允许 LLM 自行发明能力名。

## T32-4.2 Router Provider 抽象

定义最小 Provider 接口：

```python
class IntentRouterProvider(Protocol):
    async def decide(
        self,
        request: IntentRouterRequest,
    ) -> dict[str, Any]:
        ...
```

Provider 负责：

- 调用 DeepSeek 或其他模型；
- 传递结构化输出约束；
- 返回原始模型结果和调用元数据。

Provider 不负责：

- 解析 Session；
- 调用 Capability；
- 选择文件；
- 创建 Task。

## T32-4.3 上下文投影

Router 只接收经过裁剪的只读上下文：

```text
recent_messages
current_intent
candidate_papers
candidate_set_id
selected_paper
selected_sections
active_task_id
artifact_refs
session_status
```

必须限制：

- 历史消息长度；
- 单条消息长度；
- 候选论文数量；
- 传给模型的 Artifact 内容；
- 敏感字段和内部绝对路径。

上下文投影器不得扫描文件系统猜测缺失的 Artifact。

## T32-4.4 LLM 结构化决策

LLM 只允许输出 JSON 决策，不允许输出执行代码或 Tool 调用字符串：

```json
{
  "intent": "download_selected_paper",
  "capability_name": "paper_download",
  "confidence": 0.94,
  "arguments": {},
  "references": [
    {
      "type": "candidate_index",
      "value": 2
    }
  ],
  "missing_arguments": [],
  "clarification_question": null
}
```

非法 JSON、截断输出、未知字段、未知能力和类型错误都必须失败。

## T32-4.5 Schema 与能力校验

校验顺序：

```text
JSON 解析
  -> IntentDecision Schema
  -> CapabilityRegistry
  -> capability input_schema
  -> 参数类型和范围
  -> references 类型
  -> 前置条件
```

校验失败处理：

```text
第一次失败 -> 允许当前 Router 调用进行一次修复重试
仍然失败   -> 返回 clarification / failed，不执行能力
```

不得将 LLM 返回的错误能力名自动映射到相似能力。

## T32-4.6 参数归一化与前置条件

参数归一化示例：

```text
“第二篇” -> candidate_index: 2
“方法和实验部分” -> selected_sections: [...]
“刚才那篇” -> selected_paper reference
```

归一化后的引用必须由上下文解析器解析，得到真实业务对象后才能进入 Adapter。

Router 不负责：

- 读取 PDF；
- 生成术语；
- 生成译文；
- 创建任务；
- 静默选择第一篇论文替代用户选择。

## T32-4.7 混合路由策略

```text
1. 消息是否匹配明确确定性规则
2. 是 -> 使用 DeterministicIntentRouter
3. 否 -> 构造受控上下文并调用 LLM IntentRouter
4. LLM 决策经过完整校验
5. 输出统一 IntentDecision
```

确定性规则和 LLM 规则冲突时，明确格式的确定性结果优先。

## T32-4.8 澄清与低置信度策略

必须覆盖：

- 未知意图；
- 多个候选能力冲突；
- 缺少论文选择；
- 缺少 Artifact；
- 缺少章节范围；
- 缺少术语、译文或总结内容；
- 用户表达与当前任务冲突；
- 置信度低于阈值。

澄清响应必须说明缺少的业务信息，不暴露模型原始提示词。

## T32-4.9 Workflow 意图映射

组合意图只映射到已注册 Workflow：

```text
process_selected_paper
  -> paper_processing_workflow
```

Workflow 的步骤、依赖和恢复策略由 P33 定义。
LLM 不得直接返回任意步骤列表来替代 Workflow 定义。

## T32-4.10 安全与执行边界

必须验证：

- 能力白名单；
- Tool/Workflow 执行类型；
- 参数字段白名单；
- 路径只能是任务内相对路径；
- 禁止绝对路径和路径穿越；
- 禁止模型直接指定宿主机命令；
- 禁止模型直接修改 Session 或 Task 状态；
- 禁止未确认的高风险操作自动执行。

已实现 `CapabilityExecutionSecurityPolicy`，在
`ConversationService` 调用 Adapter 前执行能力白名单、Catalog Schema、
执行类型、确认状态和任务内相对路径校验。安全策略拒绝时不会调用
Adapter，也不会将失败伪装成成功。

## T32-4.11 评测与可观测性

评测集至少包含：

```text
明确单能力
自然语言改写
指代和省略
多轮上下文
组合意图
缺参
冲突意图
未知能力
非法模型输出
恶意参数和路径
```

每条决策记录：

```text
session_id
message_id
router_source
selected_intent
capability_name
confidence
missing_arguments
validation_result
clarification_reason
provider_latency
```

禁止记录 API Key、完整提示词中的敏感数据和未脱敏的用户隐私。

已实现：

- `RoutingDecisionEvent`：记录 Session/Message、来源、意图、能力、置信度、
  缺参、澄清原因、校验状态和耗时；
- `InMemoryRoutingObserver`：用于测试和本地诊断；
- `evaluate_router()`：支持正向和负向用例，并输出逐例失败原因、通过数和准确率；
- `PersistentRoutingObserver`：将脱敏路由决策追加写入
  `routing/decisions.jsonl`，支持重新加载、摘要统计和损坏记录检测；
- `ConversationService` 已接入持久化 Observer，确定性和 LLM 路由均会记录；
- 观测异常不会改变路由结果；
- 事件不包含完整 arguments、Prompt 或模型密钥。

### T32-4.11 子任务状态

| 子任务 | 内容 | 状态 |
|--------|------|------|
| T32-4.11a | 内存观测、基础评测和脱敏事件结构 | 已完成 |
| T32-4.11b | 路由过程事件持久化与重新加载 | 已完成 |
| T32-4.11c | 评测报告持久化与查询 | 已完成 |
| T32-4.11d | 历史指标统计与对比 | 待实现 |

## 验收总表

- [x] LLM 输出永远经过 JSON Schema 校验；
- [x] 未注册能力永远不能被执行；
- [x] 缺少参数时只返回澄清，不调用 Adapter；
- [x] 低置信度时只返回澄清，不调用 Adapter；
- [x] 确定性路由优先于 LLM 路由；
- [x] 上下文引用不能绕过 Session/Task 校验；
- [x] LLM 不能直接创建 Tool、Workflow 或命令；
- [x] 组合意图只能映射到已注册 Workflow；
- [x] 正向、负向、多轮和安全评测均有自动化测试；
- [x] 路由决策具备可追踪原因和脱敏日志。
- [x] 路由决策事件可持久化并在进程重启后重新加载；
- [x] 评测报告可持久化并查询；
- [ ] 路由指标支持跨批次历史对比。
