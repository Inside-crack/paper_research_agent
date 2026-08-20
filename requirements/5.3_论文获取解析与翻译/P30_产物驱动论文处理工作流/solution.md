# P30 产物驱动论文处理工作流 - 实现方案

**需求ID**：P30
**需求名称**：产物驱动论文处理工作流
**创建日期**：2026-08-19
**最后更新**：2026-08-19
**优先级**：P0
**依赖需求**：P05-P14、A01-A04、D01-D04、E01-E04

---

## 一、需求背景与目标

### 1.1 背景

当前 `paper_parsing` 阶段由 Research Agent 一次性生成 P10-P14 的完整静态
ExecutionPlan。P10-P14 的输入依赖前一步动态产物，导致真实 DeepSeek 运行时在
计划生成阶段出现非 JSON 输出，尚未执行任何论文处理工具。

### 1.2 目标

1. 保留 `PAPER_PARSING` 顶层阶段，内部拆分五个可恢复子步骤。
2. 由 Orchestrator 固定控制顺序和数据依赖。
3. 每个子步骤完成后将真实 artifact 注入下一子步骤。
4. 每个子步骤独立执行确定性校验和 Evaluation Agent 评估。
5. 单个子步骤最多定向 REVISE 一次，失败后 BLOCKED。

### 1.3 范围

- **In Scope（本次要做的）**：
  - [ ] `download`、`parse`、`glossary`、`translate`、`summary` 子步骤状态。
  - [ ] P10-P14 子步骤数据依赖和上下文注入。
  - [ ] 子步骤级持久化、恢复和质量门禁。
  - [ ] 旧 `PAPER_PARSING` artifact 和 checkpoint 兼容。
- **Out of Scope（明确不做的）**：
  - P15-P29。
  - 新增顶层 TaskPhase。
  - 自动切换候选论文。
  - OCR、外部翻译服务和人工候选确认。

---

## 二、功能规格

### 2.1 核心功能规则

1. 当 `paper_retrieval` 产出候选时，系统必须固定使用第一篇 Agent 选中的候选论文。
2. 系统必须按 `download -> parse -> glossary -> translate -> summary` 顺序执行。
3. 子步骤只能读取已完成前置步骤的产物。
4. 子步骤 PASS 后，后续 REVISE 不得重跑该子步骤。
5. 当前子步骤失败时最多允许一次定向 REVISE。
6. 第二次失败必须将子步骤和任务标记为 BLOCKED。
7. 检索结果为空必须直接 BLOCKED。
8. 任意 artifact 或 Manifest 持久化失败不得报告成功。

### 2.2 阶段流转与状态变更

- 当前阶段：`PAPER_PARSING`
- 内部子步骤：`download`、`parse`、`glossary`、`translate`、`summary`
- 触发条件：`paper_retrieval` PASS 且存在候选论文
- 下一阶段：五个子步骤全部 PASS 后进入现有下一阶段
- 守卫条件：
  - 无候选论文：BLOCKED；
  - 前置子步骤未 PASS：禁止进入下一子步骤；
  - 当前子步骤第二次失败：BLOCKED；
  - 持久化失败：立即失败并保留错误上下文。

### 2.3 边界条件与异常处理

| 场景 | 预期行为 | 错误码/日志关键字 |
|------|----------|------------------|
| 候选为空 | BLOCKED，等待用户重新输入 | `ERROR_NO_PAPER_CANDIDATE` |
| 第一篇下载失败 | REVISE 一次，不切换候选；再次失败 BLOCKED | `ERROR_PAPER_DOWNLOAD` |
| PDF 解析失败 | REVISE 一次；再次失败 BLOCKED | `ERROR_PAPER_PARSE` |
| 术语校验失败 | 只重试 glossary；再次失败 BLOCKED | `ERROR_GLOSSARY_INVALID` |
| 翻译章节缺失 | 只重试 translate；保护已通过章节 | `ERROR_TRANSLATION_INVALID` |
| 总结证据缺失 | 只重试 summary；再次失败 BLOCKED | `ERROR_SUMMARY_EVIDENCE` |
| artifact/Manifest 写入失败 | 终止并记录错误上下文 | `ERROR_PERSISTENCE` |
| 任务中断 | 保存子步骤边界，支持恢复 | `TASK_INTERRUPTED` |
| 旧任务无子步骤字段 | 按兼容模式读取旧状态 | `LEGACY_PAPER_PARSING` |

### 2.4 与双 Agent 质量门禁的适配

- **是否需要 Evaluation Agent 评估**：是，每个子步骤独立评估。
- **确定性检查项**：
  - [ ] 子步骤输入 artifact 存在且路径在任务目录内。
  - [ ] 子步骤输出 JSON 合法且已登记 Manifest。
  - [ ] 子步骤状态、artifact 和 Manifest 状态一致。
  - [ ] P10-P14 各自的既有确定性校验通过。
- **LLM 评估判断标准**：
  - PASS：确定性检查全部通过，内容满足当前子步骤契约。
  - REVISE：仅当前子步骤内容需要定向修正。
  - BLOCKED：输入缺失、第二次修正失败或核心持久化失败。
- **REVISE 修正边界**：只允许修改当前子步骤；不允许重新选论文或重跑已通过前置步骤。

### 2.5 数据结构与产物

- 新增/修改模型：`TaskState` 增加可选 `paper_processing_steps`；每项包含
  `status`、`revision_count`、`input_artifacts`、`output_artifacts`、`error`、
  `started_at`、`completed_at`。
- 新增 Manifest 子步骤记录：与 `PAPER_PARSING` 阶段关联。
- 既有产物继续使用：
  - `data/artifacts/<task_id>/papers/<arxiv_id>.pdf`
  - `data/artifacts/<task_id>/papers/<arxiv_id>.json`
- 子步骤结果和错误上下文继续写入任务 artifact 目录。
- 所有 JSON 写入必须使用原子写入流程。

### 2.6 验收标准

- [ ] 离线 P10-P14 E2E 验证五个子步骤按顺序执行。
- [ ] Orchestrator E2E 验证真实产物在子步骤间传递。
- [ ] 检索为空返回 BLOCKED。
- [ ] 第一篇下载失败不切换候选。
- [ ] 当前子步骤只 REVISE 一次。
- [ ] 翻译失败不污染已通过章节。
- [ ] 持久化失败不返回成功。
- [ ] 历史 artifact 和 checkpoint 仍可读取。
- [ ] 现有 P10-P14、检索、任务生命周期回归测试通过。

---

## 三、技术方案

### 3.1 整体思路

Orchestrator 负责 P10-P14 的固定顺序、输入输出映射和子步骤状态；Research Agent
在每个子步骤边界生成内容候选；工具负责确定性校验和持久化；Evaluation Agent
在每个子步骤结束后独立评估。

### 3.2 架构设计

```text
paper_retrieval.candidates[0]
  -> download -> PaperArtifact/pdf
  -> parse -> sections/full_text_original
  -> glossary -> glossary
  -> translate -> translated sections/full_text_translated
  -> summary -> summary_evidence
```

每个箭头都是一次持久化和上下文注入边界，不再由单次静态 ExecutionPlan 猜测后续
动态参数。

### 3.3 接口设计

子步骤执行接口必须接收：

```text
task_id
substep
input_artifacts
revision
```

并返回：

```text
status
output_artifacts
deterministic_checks
error
```

### 3.4 影响面分析

- 需要修改：
  - `src/paper_agent/orchestrator/orchestrator.py`
  - `src/paper_agent/common/models/task_state.py`
  - `src/paper_agent/common/persistence/manifest.py`
  - `src/paper_agent/common/persistence/state_persistence.py`
  - `src/paper_agent/evaluation_agent/agent.py`
- 需要新增：
  - 子步骤状态模型和 P30 测试脚本。
- 需要回归：
  - P10-P14 工具测试；
  - Orchestrator E2E；
  - 任务初始化、阶段隔离、REVISE、Manifest 和 checkpoint 测试。
- Breaking change：不得改变现有顶层 `TaskPhase` 和旧 artifact 读取格式。

### 3.5 风险评估与应对

| 风险点 | 影响等级 | 应对措施 |
|--------|----------|----------|
| TaskState 新字段影响旧 checkpoint | 高 | 可选字段和旧状态兼容读取 |
| 子步骤增加 LLM 调用成本 | 中 | 每步限定一次 REVISE，压缩上下文 |
| Manifest 与 TaskState 状态不一致 | 高 | 状态更新统一走持久化服务并测试失败路径 |
| 旧 phase flow 与新子步骤并存 | 中 | 保留兼容入口，明确新旧模式检测 |

---

## 四、实施任务拆分

| 任务ID | 任务描述 | 依赖 | 预计复杂度 | 验收子标准 |
|--------|----------|------|------------|------------|
| T1 | 子步骤模型、TaskState、Manifest 持久化 | 无 | M | 状态可保存、读取、恢复 |
| T2 | Orchestrator P10-P14 子步骤执行器和数据传递 | T1 | L | 五步按顺序执行，前置产物可注入后续 |
| T3 | 子步骤级 Evaluation、REVISE、BLOCKED 和 E2E 回归 | T2 | L | 正向与负向验收全部通过 |

## 实现步骤总览

1. T1：增加兼容的子步骤状态和 Manifest 记录。
2. T2：实现固定 P10-P14 子步骤链路和产物传递。
3. T3：接入独立评估、定向 REVISE、BLOCKED 和恢复测试。
