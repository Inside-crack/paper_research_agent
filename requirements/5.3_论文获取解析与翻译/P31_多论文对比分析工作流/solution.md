# P31 多论文对比分析工作流 - 实现方案

**需求ID**：P31  
**需求名称**：多论文对比分析工作流  
**创建日期**：2026-08-27  
**最后更新**：2026-08-27  
**优先级**：P1  
**依赖需求**：P10-P14、P30、D53 缺陷修复

## 一、需求背景与目标

当前 `PaperProcessingWorkflow` 面向单篇论文。P31 新增独立的
`PaperComparisonWorkflow`，复用论文获取、下载、解析、总结和持久化能力，
将多篇论文的结构化产物组织成对比分析结果。

第一阶段不执行论文代码，不要求论文存在可运行的代码仓库，也不验证论文
实验结果。

## 二、架构设计

```text
ConversationApplicationService
    -> compare_papers capability
    -> waiting_confirmation
    -> Orchestrator
    -> PaperComparisonWorkflow
        -> PaperAcquisitionService
        -> PaperProcessingWorkflow / paper artifacts
        -> comparison analysis
        -> PaperComparisonArtifact
```

职责边界：

- `ConversationApplicationService`：识别对比意图、管理论文选择和用户确认。
- `Orchestrator`：创建任务、管理生命周期、checkpoint、事件和 artifact。
- `PaperComparisonWorkflow`：编排多篇论文的获取、解析和对比。
- 代码：负责论文身份、工具事实、去重、产物合并和 Schema 校验。
- LLM：负责解释共同点、差异、适用场景和技术演进。

`PaperComparisonWorkflow` 与现有 `PaperProcessingWorkflow` 并列，不改变单论文
Workflow 的职责。

## 三、Workflow 流程

```text
comparison_initialization
    -> paper_acquisition
    -> paper_parsing
    -> comparison_analysis
    -> comparison_reporting
```

第一阶段允许串行处理 2-5 篇论文；后续再增加并行、细粒度恢复和限流。

## 四、论文获取策略

统一获取入口按以下优先级选择资源：

```text
已有完整 PaperArtifact
    -> 已有本地 PDF
    -> 已有论文元数据
    -> arxiv_get_paper
    -> paper_download
```

每次复用资源前必须校验论文 ID、URL和版本。不同版本不能静默合并。

建议抽象：

```python
class PaperAcquisitionService:
    async def acquire(self, paper_ref) -> PaperAcquisitionResult:
        ...
```

`PaperAcquisitionResult` 至少包含：

```text
paper_id
metadata
pdf_path
paper_artifact_path
source
reused
version
```

## 五、输入和输出

### 5.1 输入

```text
ComparisonSpec
confirmed_papers
comparison_dimensions
existing_artifacts
existing_pdfs
```

第一版默认比较维度：

```text
研究问题
核心方法
训练策略
数据集与评价指标
实验结果
优点与局限
```

### 5.2 输出

```text
comparison_spec.json
paper_comparison.json
paper_comparison.md（可选）
```

`paper_comparison.json` 是系统主产物，必须经过 Pydantic 校验并原子写入。

建议包含：

```text
comparison_id
papers
dimensions
comparison_matrix
commonalities
differences
conclusion
missing_information
```

## 六、事实与分析边界

代码负责：

- 论文 ID、标题、作者、版本和来源；
- PDF及 PaperArtifact 引用；
- 工具已经确认的数据集、指标和论文报告结果；
- 论文去重、字段合并和结果校验。

LLM 负责：

- 方法差异解释；
- 共同点归纳；
- 适用场景分析；
- 技术演进和局限总结。

LLM 不得覆盖工具或已有 PaperArtifact 中的事实字段。缺少证据时使用
`unknown` 或写入 `missing_information`，不得将缺失证据直接解释为否定事实。

## 七、触发和确认

新增能力：

```text
compare_papers
```

支持：

```text
比较 I3CL、DBNet 和 TextSnake
对比候选论文 1、2、4
分析这几篇论文的方法差异
```

触发链路：

```text
识别 compare_papers
    -> 提取论文引用
    -> 补充或确认论文列表
    -> waiting_confirmation
    -> 用户显式确认
    -> 创建 comparison_analysis 任务
    -> 启动 PaperComparisonWorkflow
```

## 八、实现影响面

预计新增或修改：

- `src/paper_agent/common/models/research_spec.py`
- `src/paper_agent/common/models/paper_comparison.py`
- `src/paper_agent/common/capabilities/`
- `src/paper_agent/orchestrator/`
- `src/paper_agent/workflows/paper_comparison.py`
- `src/paper_agent/common/persistence/`
- `prompts/research_agent/`
- `examples/`

不得破坏既有单论文任务、旧 artifact 和 checkpoint 的读取兼容性。
