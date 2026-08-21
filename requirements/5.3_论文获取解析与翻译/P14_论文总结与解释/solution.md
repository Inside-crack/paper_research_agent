# 论文总结与解释 - 实现方案

**需求ID**：P14  
**需求名称**：论文总结与解释  
**创建日期**：2026-08-14  
**最后更新**：2026-08-19

## 需求描述

Research Agent 总结研究问题、方法、创新、实验结论和局限；每类总结必须关联
P11 的一个或多个章节证据。Evaluation Agent 后续检查结论是否忠实于原文。

## 方案设计

### 整体思路

Research Agent 生成结构化 summary 候选，`paper_summary` 工具不调用外部知识源，
只校验字段类型、内容和 section 证据，然后原子更新 `PaperArtifact`。

### 架构设计

```text
P11/P13 PaperArtifact
  + Research Agent summary candidates
  -> PaperSummaryTool field/evidence validation
  -> summary fields + summary_evidence
  -> atomic JSON update + Manifest
```

### 接口设计

工具名：`paper_summary`

```json
{
  "task_id": "task-id",
  "artifact_path": "papers/1706.03762v1.json",
  "summary": {
    "research_questions": ["论文研究如何提升工具调用可靠性？"],
    "methodology_summary": "作者通过受控实验比较不同方法。",
    "contributions": ["提出一种新的方法框架。"],
    "conclusions": ["方法在目标任务上取得改进。"],
    "limitations": ["实验范围仍有限。"],
    "evidence": {
      "research_questions": ["section_1"],
      "methodology_summary": ["section_2"],
      "contributions": ["section_2"],
      "conclusions": ["section_3"],
      "limitations": ["section_3"]
    }
  }
}
```

### 数据结构

`PaperArtifact` 新增向后兼容字段：

```python
summary_evidence: dict[str, list[str]]
```

## 实现步骤

1. 增加 `summary_evidence` 字段。
2. 新增 `PaperSummaryTool`，校验总结字段和章节证据。
3. 注册工具，更新解析 Prompt，并原子持久化总结。

## 依赖项

- [x] P11 `PaperArtifact.sections` 和原文
- [x] `StatePersistence.update_paper_artifact()` 和 `ToolRegistry`

## 风险评估

| 风险点 | 影响等级 | 应对措施 |
|---|---|---|
| 总结混入论文外知识 | 高 | 每个非空总结类别必须提供 section 证据 |
| 引用不存在章节 | 高 | 工具拒绝未知 section ID |
| 字段格式不一致 | 中 | 逐字段校验字符串和字符串列表 |
| 持久化失败 | 高 | 原子更新并传播错误 |
