# P32 能力契约、Adapter、注册与意图路由

**目标**：让 Agent 选择经过契约校验的业务 Capability，而不是直接猜测或调用底层 Tool。

P32 负责把已有 Tool 包装成完整的业务能力单元，并生成经过契约校验的“待执行能力决策”。
P32 不负责长流程编排、用户交互状态迁移或对外 Chat 接口。

## 实现拆分

P32 不一次性实现。按以下子需求顺序推进：

```text
T32-0 最小执行契约 + 已有 Tool 的 Capability Adapter 封装
  -> T32-1 CapabilityRegistry
  -> T32-2 Preconditions
  -> T32-3 IntentDecision 与确定性路由
  -> T32-4 LLM IntentRouter
  -> T32-5 P31 Session 集成
```

复杂意图识别已进一步拆分为可独立验收的 T32-4 子需求，详见：

[T32-4_complex_intent_routing.md](T32-4_complex_intent_routing.md)

当前 T32-0 至 T32-4.11 均已实现；P33 负责后续 Workflow 生命周期与执行编排。

T32-0 的详细能力清单见：

[T32-0_capability_inventory.md](T32-0_capability_inventory.md)

## 依赖与边界

```text
ConversationMessage + ConversationContext
  -> IntentRouter
  -> IntentDecision
  -> CapabilityRegistry.resolve()
  -> Preconditions.check()
  -> CapabilityDecision
  -> 交给 P34 ConversationApplicationService 执行
```

其中：

- `CapabilityRegistry` 可以独立于 P31 实现；
- `IntentRouter` 的会话上下文集成依赖 P31；
- Router 不直接调用 Tool；
- Capability Adapter 负责调用单个 Tool；Capability Workflow 负责调用 P33；
- P34 负责确认、暂停、恢复和取消等状态迁移。

## 一、Capability 数据模型

每个能力至少声明：

```text
Capability
  - name: str
  - version: str
  - description: str
  - enabled: bool
  - input_schema: JSON Schema
  - output_schema: JSON Schema
  - preconditions: list[Precondition]
  - execution_kind: tool | workflow
  - confirmation_required: bool
  - retry_policy: dict
  - handler: ToolAdapter | WorkflowAdapter
```

`execution_kind` 用于区分：

```text
paper_parse       -> tool
paper_translate   -> tool
paper_processing  -> workflow
```

P32 只声明和解析该字段，不执行对应对象。

## 二、Capability Adapter 与结果契约

已有 P10-P14 Tool 不直接暴露给 Router。每个 Tool 先包装为一个完整能力单元：

```text
Capability Adapter
  -> 校验输入
  -> 检查前置条件
  -> 将业务参数转换为 Tool 参数
  -> 调用 Tool 或 Workflow
  -> 校验输出
  -> 返回 CapabilityResult
```

统一接口：

```python
class CapabilityAdapter:
    capability: Capability

    async def execute(
        self,
        context: ExecutionContext,
        arguments: dict,
    ) -> CapabilityResult: ...
```

统一结果：

```text
CapabilityResult
  - success: bool
  - status: succeeded | waiting | failed | blocked
  - data: dict | None
  - artifact_refs: list[str]
  - error: str | None
  - next_actions: list[str]
```

MVP 先包装：

```text
paper_search
paper_download
paper_parse
paper_glossary
paper_translate
paper_summary
```

Adapter 不改变底层 P10-P14 Tool 的输入输出契约，只提供面向 Agent 的稳定边界。

## 三、T32-0：已有能力清单与 Adapter 契约

### T32-0.1 论文检索能力

**Capability 名称**：`paper_search`

**底层 Tool**：

```text
arxiv_search
arxiv_get_paper
```

**输入**：

```text
query: str                    # 必填
max_results: int = 10         # 必须 > 0
categories: list[str] = []
sort_by: str = "relevance"
sort_order: str = "descending"
arxiv_id: str | None = None   # 指定论文时调用 arxiv_get_paper
```

**处理**：

```text
有 arxiv_id -> 获取单篇论文元数据
无 arxiv_id  -> 执行 arxiv_search
```

**输出**：

```text
data:
  query
  total
  candidates: list[PaperCandidate]
  selected_paper: None
artifact_refs: []
```

检索结果只保存候选，不在该能力内自动选择论文。`paper_select` 不是当前已有
Tool，后续由 P34 的用户确认流程负责。

### T32-0.2 全文获取能力

**Capability 名称**：`paper_download`

**底层 Tool**：`paper_download`

**输入**：

```text
task_id: str                  # 由 ExecutionContext 提供
paper: dict                   # 至少包含 arxiv_id 或 pdf_url
arxiv_id: str | None = None
pdf_url: str | None = None
```

**前置条件**：

```text
selected_paper 存在
```

**输出**：

```text
data:
  paper_artifact_id
  arxiv_id
  version
  pdf_path
  artifact_path
  size_bytes
  source
artifact_refs:
  artifact_path
  pdf_path
```

### T32-0.3 论文结构解析能力

**Capability 名称**：`paper_parse`

**底层 Tool**：`paper_parse`

**输入**：

```text
task_id: str
artifact_path: str           # paper_download 输出的相对 artifact 路径
```

**前置条件**：

```text
paper artifact 存在
artifact.pdf_path 存在且 PDF 文件可读
```

**输出**：

```text
data:
  paper_artifact_id
  artifact_path
  page_count
  section_count
  text_length
  parsing_errors
artifact_refs:
  artifact_path
```

### T32-0.4 术语表能力

**Capability 名称**：`paper_glossary`

**底层 Tool**：`paper_glossary`

**输入**：

```text
task_id: str
artifact_path: str
terms: list[{
  source_term: str,
  target_term: str,
  context: str,
  confidence: float
}]
```

**前置条件**：

```text
P11 已完成
artifact.full_text_original 非空
```

**输出**：

```text
data:
  paper_artifact_id
  artifact_path
  term_count
  terms
artifact_refs:
  artifact_path
```

术语候选由后续 Agent 内容生成步骤提供；Adapter 只负责参数校验、调用和结果统一。

### T32-0.5 分章节翻译能力

**Capability 名称**：`paper_translate`

**底层 Tool**：`paper_translate`

**输入**：

```text
task_id: str
artifact_path: str
translations: list[{
  section_id: str,
  translated_text: str
}]
```

**前置条件**：

```text
P11 已完成
sections 非空
```

如果翻译能力要求术语生成已完成，Adapter 必须检查 artifact.glossary，
不能在缺失时自行生成或猜测术语。

**输出**：

```text
data:
  paper_artifact_id
  artifact_path
  section_count
  translated_text_length
artifact_refs:
  artifact_path
```

### T32-0.6 论文总结能力

**Capability 名称**：`paper_summary`

**底层 Tool**：`paper_summary`

**输入**：

```text
task_id: str
artifact_path: str
summary: {
  research_questions: list[str],
  methodology_summary: str,
  contributions: list[str],
  conclusions: list[str],
  limitations: list[str],
  evidence: dict[str, list[str]]
}
```

**前置条件**：

```text
P11 已完成
sections 非空
```

**输出**：

```text
data:
  paper_artifact_id
  artifact_path
  evidence_categories
  summary_fields
artifact_refs:
  artifact_path
```

### T32-0.7 不纳入本轮封装的 Tool

以下是基础设施 Tool，不直接暴露为对话能力：

```text
save_artifact
load_artifact
download_file
```

它们只能被其他 Capability Adapter 或 Workflow 内部调用。

## 四、CapabilityRegistry 契约

```python
class CapabilityRegistry:
    def register(self, capability: Capability) -> None: ...
    def resolve(self, name: str) -> Capability: ...
    def list_enabled(self) -> list[Capability]: ...
```

MVP 规则：

- 同名 Capability 只能注册一次；
- 重复注册直接报错；
- disabled Capability 不得被 Router 选择；
- 不存在的 Capability 返回明确错误；
- Registry 只负责注册、查询和启停，不负责执行；
- 版本先作为元数据保存，不实现多版本协商。

当前已封装并可注册的确定能力：

```text
paper_search
paper_download
paper_parse
paper_glossary
paper_translate
paper_summary
```

`paper_select` 当前没有独立 Tool，仍属于后续 P34 的用户确认流程，
不注册为虚假 Capability。

## 五、IntentDecision 契约

Router 的输入：

```python
async def route(
    message: ConversationMessage,
    context: ConversationContext,
) -> IntentDecision: ...
```

输出：

```text
IntentDecision
  - matched: bool
  - intent: str | None
  - capability_name: str | None
  - execution_kind: tool | workflow
  - confidence: float
  - arguments: dict
  - references: list[ContextReference]
  - missing_arguments: list[str]
  - clarification_question: str | None
  - reason: str | None
  - source: deterministic | llm | fallback
```

T32-4.0 已将该契约实现为严格 Pydantic Schema：

- `matched=true` 必须包含 `intent` 和 `capability_name`；
- `matched=true` 不允许存在 `missing_arguments`；
- `execution_kind` 和 `source` 只能取允许值；
- 未知字段、非法置信度和无效上下文引用会被拒绝；
- `ContextReference` 只表示类型化引用，不代表已经解析为真实业务对象。

`intent` 表示用户想做什么，`capability_name` 表示系统用哪个能力完成，两者不能混为一个字段。例如：

```text
intent: translate_paper_section
capability_name: paper_translate
```

低置信度、能力不存在或参数不完整时，`matched` 必须为 `false`，
不得产生可执行的能力决策。

当前先实现确定性路由骨架。对于 `paper_parse`、`paper_glossary`、
`paper_translate` 和 `paper_summary`，如果消息没有携带所需的
`artifact_path` 或业务内容，Router 只返回 `missing_arguments`，
不扫描文件系统、不生成伪造参数。

## 六、前置条件契约

前置条件检查器读取统一上下文，不扫描文件系统猜测 artifact：

```text
PreconditionContext
  - session
  - task_state
  - artifact_refs
```

接口：

```python
class Preconditions:
    def check(
        self,
        capability: Capability,
        context: PreconditionContext,
        arguments: dict,
    ) -> PreconditionResult: ...
```

结果：

```text
PreconditionResult
  - satisfied: bool
  - missing: list[str]
  - reason: str | None
  - suggested_action: str | None
```

示例：

```text
paper_translate:
  - selected_paper 存在
  - PaperArtifact 存在
  - sections 非空
```

缺失前置条件时应返回下一步建议，不得猜测路径、创建伪造上下文或直接执行能力。

## 七、Router 策略

优先使用确定性规则处理低风险、格式明确的指令：

```text
task_status
task_resume
task_cancel
明确的论文编号选择
明确的 arXiv ID / PDF URL
```

模糊表达再交给 LLM：

```text
论文检索
翻译
总结
追问
```

LLM 输出必须经过 JSON Schema 校验。解析失败时只重试当前 Router 调用；
重试仍失败则返回澄清，不启动任何 Capability。

## 八、验收标准

### Registry

- [x] 能力可以注册、查询和列出；
- [x] 重复注册被拒绝；
- [x] disabled 能力不能被解析；
- [x] 不存在的能力返回明确错误；
- [x] 输入输出 Schema 和执行类型可读取。

### Adapter

- [x] P10-P14 Tool 均有统一 Capability Adapter；
- [x] Adapter 能接受统一 `ExecutionContext` 和业务参数；
- [x] Tool 错误不会被转换成伪成功；
- [x] 输出统一转换为 `CapabilityResult`；
- [x] Adapter 不让调用方直接拼接 artifact 绝对路径。

### Router

- [x] 输出严格符合 `IntentDecision`；
- [x] 低置信度不返回可执行决策；
- [x] 缺少参数时返回澄清信息；
- [x] `"翻译第 3 篇方法部分"`在有候选上下文时解析出论文编号和章节范围；
- [x] 无候选上下文时返回缺失参数，不猜测论文；
- [x] Router 不执行 Tool；
- [x] LLM 输出非法时不会启动能力；
- [x] 简单论文选择和任务操作支持确定性解析。

### Preconditions

- [x] 缺少论文时不能执行翻译；
- [x] 缺少 sections 时不能执行总结；
- [x] 缺少 artifact 时返回明确缺失项；
- [x] 不扫描文件系统猜测 artifact；
- [x] 前置条件结果可以转换为用户可理解的澄清或下一步建议。

## 九、明确不做

- 不执行 Tool 或 Workflow；
- 不负责长流程的顺序编排；
- 不实现 P33 Workflow 抽离；
- 不实现 P34 确认、暂停、恢复、取消；
- 不实现 P35 事件流和 ResponseComposer；
- 不实现 P36 Chat CLI/API；
- 不实现 Capability 多版本协商；
- 不实现长期记忆、权限和多用户隔离。
