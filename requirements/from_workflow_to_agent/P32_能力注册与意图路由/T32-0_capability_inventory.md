# T32-0：已有能力封装清单

## 目标

将当前已经实现的底层 Tool 包装为 Agent 可调用的完整 Capability。

本清单只覆盖 Adapter 封装，不实现：

- CapabilityRegistry；
- Preconditions 通用框架；
- Intent Router；
- LLM 调用；
- P33 多步骤 Workflow；
- P34 用户确认和交互状态。

## 统一封装契约

### 调用入口

```python
result = await adapter.execute(
    context=execution_context,
    arguments=business_arguments,
)
```

### Adapter 内部调用

```python
tool_result = await tool_registry.execute(
    tool_name,
    **tool_arguments,
)
```

### ExecutionContext 最小字段

```text
session_id: str | None
task_id: str | None
selected_paper: dict | None
artifact_refs: list[str]
metadata: dict
```

### CapabilityResult

```text
success: bool
status: succeeded | failed | blocked
data: dict | None
artifact_refs: list[str]
error: str | None
next_actions: list[str]
```

规则：

- Adapter 从 `ExecutionContext` 注入 `task_id`，调用方不重复传递；
- Adapter 只接受业务参数，不接受宿主机绝对路径；
- 底层 `ToolResult` 的错误必须保留，不能转换成伪成功；
- 成功结果必须经过最小输出校验；
- Adapter 不修改底层 Tool 的既有参数契约；
- 每个 Adapter 都必须有成功、参数缺失、Tool 失败和输出异常测试。

## 实现顺序总表

| 顺序 | Capability | 底层 Tool | 依赖 | 状态 |
|------|------------|-----------|------|------|
| 1 | `paper_search` | `arxiv_search`、`arxiv_get_paper` | 无 | 已完成 |
| 2 | `paper_download` | `paper_download` | `selected_paper` + `task_id` | 已完成 |
| 3 | `paper_parse` | `paper_parse` | `paper_download` artifact | 已完成 |
| 4 | `paper_glossary` | `paper_glossary` | `paper_parse` artifact | 已完成 |
| 5 | `paper_translate` | `paper_translate` | sections、glossary | 已完成 |
| 6 | `paper_summary` | `paper_summary` | sections | 已完成 |

## 1. `paper_search`

### 底层调用

```text
query 未提供 arxiv_id：
  arxiv_search

query 明确指定 arxiv_id：
  arxiv_get_paper
```

### 输入

```text
query: str
max_results: int = 10
categories: list[str] = []
sort_by: str = "relevance"
sort_order: str = "descending"
arxiv_id: str | None = None
```

### 输出

```text
data:
  query: str
  total: int
  candidates: list[PaperCandidate]
artifact_refs: []
```

### 规则

- `query` 不能为空；
- `max_results` 必须大于 0；
- 只返回候选论文，不自动选择；
- 不生成 TaskState；
- 不调用 P10-P14。

## 2. `paper_download`

### 输入

```text
selected_paper: ExecutionContext.selected_paper
arxiv_id: str | None
pdf_url: str | None
```

实际传给底层 Tool：

```text
task_id: ExecutionContext.task_id
paper: selected_paper
arxiv_id
pdf_url
```

### 前置条件

```text
task_id 存在
selected_paper 存在
selected_paper 包含 arxiv_id 或 pdf_url
```

### 输出

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
  - artifact_path
  - pdf_path
```

## 3. `paper_parse`

### 输入

```text
artifact_path: str
```

实际传给底层 Tool：

```text
task_id: ExecutionContext.task_id
artifact_path
```

### 前置条件

```text
task_id 存在
artifact_path 是任务内相对路径
paper artifact 存在
artifact.pdf_path 存在且可读取
```

### 输出

```text
data:
  paper_artifact_id
  artifact_path
  page_count
  section_count
  text_length
  parsing_errors
artifact_refs:
  - artifact_path
```

## 4. `paper_glossary`

### 输入

```text
artifact_path: str
terms: list[{
  source_term: str
  target_term: str
  context: str
  confidence: float
}]
```

### 前置条件

```text
task_id 存在
artifact_path 存在
artifact.full_text_original 非空
```

### 输出

```text
data:
  paper_artifact_id
  artifact_path
  term_count
  terms
artifact_refs:
  - artifact_path
```

### 规则

- Adapter 不生成术语，只转发 Agent 生成的候选；
- 底层 Tool 负责 source term 证据、置信度、去重和持久化校验；
- 失败时不产生部分成功结果。

## 5. `paper_translate`

### 输入

```text
artifact_path: str
translations: list[{
  section_id: str
  translated_text: str
}]
```

### 前置条件

```text
task_id 存在
artifact_path 存在
artifact.sections 非空
```

### 输出

```text
data:
  paper_artifact_id
  artifact_path
  section_count
  translated_text_length
artifact_refs:
  - artifact_path
```

### 规则

- Adapter 不生成译文；
- 底层 Tool 负责章节完整性、数字、引用、公式和术语保护；
- 失败不能污染已持久化的完整译文。

## 6. `paper_summary`

### 输入

```text
artifact_path: str
summary: {
  research_questions: list[str]
  methodology_summary: str
  contributions: list[str]
  conclusions: list[str]
  limitations: list[str]
  evidence: dict[str, list[str]]
}
```

### 前置条件

```text
task_id 存在
artifact_path 存在
artifact.sections 非空
```

### 输出

```text
data:
  paper_artifact_id
  artifact_path
  evidence_categories
  summary_fields
artifact_refs:
  - artifact_path
```

### 规则

- Adapter 不生成总结；
- 底层 Tool 负责字段校验和 section evidence 校验；
- 证据无效时整个操作失败。

## 明确不作为 T32-0 的能力

| 名称 | 原因 | 归属 |
|------|------|------|
| `paper_select` | 当前没有独立 Tool | P34 用户确认流程 |
| `paper_processing` | 多步骤动态依赖 Workflow | P33 |
| `task_status` | 不是论文 Tool | P34/P36 |
| `task_pause` | 需要交互状态迁移 | P34 |
| `task_resume` | 需要交互状态迁移 | P34 |
| `task_cancel` | 需要生命周期控制 | P34 |
| `save_artifact` | 内部持久化基础设施 | Adapter/Workflow 内部 |
| `load_artifact` | 内部持久化基础设施 | Adapter/Workflow 内部 |
| `download_file` | 底层通用下载基础设施 | `paper_download` 内部 |

## T32-0 验收清单

- [x] 最小 Capability 契约和 `paper_search` Adapter 有独立类和统一入口；
- [x] `paper_download` Adapter 有独立类、任务边界校验和 artifact 引用输出；
- [x] 6 个 Capability Adapter 均有独立类和统一入口；
- [x] 每个 Adapter 通过 `ToolRegistry` 调用底层 Tool；
- [ ] `task_id` 从 `ExecutionContext` 注入；
- [ ] 所有相对路径经过任务边界校验；
- [x] 底层 Tool 失败原样转为失败的 `CapabilityResult`；
- [x] 成功输出包含必要的 artifact 引用；
- [ ] 不存在的 `paper_select` 不被注册为虚假 Tool；
- [x] 每个 Adapter 具备正向和负向测试；
- [ ] P10-P14 原有测试全部回归通过。
