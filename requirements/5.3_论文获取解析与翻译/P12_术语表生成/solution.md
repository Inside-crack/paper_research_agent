# 术语表生成 - 实现方案

**需求ID**：P12  
**需求名称**：术语表生成  
**创建日期**：2026-08-14  
**最后更新**：2026-08-19

## 需求描述

Research Agent 根据 P11 原文生成中英文术语候选，系统校验术语原文证据、译词、
上下文和置信度，并保存为结构化 `TermEntry`。Evaluation Agent 后续检查准确性、
歧义和全文一致性。

## 方案设计

### 整体思路

LLM 只负责提出候选映射，`paper_glossary` 工具不调用 LLM，只执行确定性检查：
源术语必须出现在 `full_text_original` 中，置信度必须在 `[0, 1]`，然后按源术语
大小写不敏感去重并保留最高置信度项。

### 架构设计

```text
P11 PaperArtifact
  + Research Agent term candidates
  -> PaperGlossaryTool validation/deduplication
  -> PaperArtifact.glossary
  -> atomic JSON update + Manifest
```

### 接口设计

工具名：`paper_glossary`

```json
{
  "task_id": "task-id",
  "artifact_path": "papers/1706.03762v1.json",
  "terms": [
    {
      "source_term": "chain-of-thought",
      "target_term": "思维链",
      "context": "Chain-of-thought reasoning",
      "confidence": 0.95
    }
  ]
}
```

成功返回 `paper_artifact_id`、`artifact_path`、`term_count` 和去重后的 `terms`。

## 实现步骤

1. 使用 P11 的原文 artifact 作为术语证据源。
2. 新增 `PaperGlossaryTool`，完成字段校验、证据校验、去重和排序。
3. 复用 `update_paper_artifact()` 原子持久化并接入解析阶段 Prompt。

## 依赖项

- [x] P11 `PaperArtifact.full_text_original`
- [x] `TermEntry`、`StatePersistence` 和 `ToolRegistry`

## 风险评估

| 风险点 | 影响等级 | 应对措施 |
|---|---|---|
| LLM 生成原文不存在的术语 | 高 | 工具拒绝无原文证据的 source_term |
| 同一术语存在多个译法 | 中 | 保留最高置信度项并稳定排序 |
| 未完成 P11 解析 | 高 | `full_text_original` 为空时明确要求先完成 P11 |
| artifact 持久化失败 | 高 | 传播错误，不返回成功 |
