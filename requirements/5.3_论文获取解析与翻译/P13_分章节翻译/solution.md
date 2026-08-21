# 分章节翻译 - 实现方案

**需求ID**：P13  
**需求名称**：分章节翻译  
**创建日期**：2026-08-14  
**最后更新**：2026-08-19

## 需求描述

Research Agent 在保留公式、数字、引用和术语译法的前提下生成中文分章节译文；
Evaluation Agent 后续检查语义忠实度、信息遗漏和保护内容变化。

## 方案设计

### 整体思路

Research Agent 生成译文候选，`paper_translate` 工具不调用 LLM，只执行确定性
章节覆盖和内容保护检查。全部章节验证通过后，更新 `PaperSection.translated_text`
和 `PaperArtifact.full_text_translated`。

### 架构设计

```text
P11 sections + P12 glossary
  + Research Agent translations
  -> PaperTranslateTool protection/coverage checks
  -> translated sections + full_text_translated
  -> atomic JSON update + Manifest
```

### 接口设计

工具名：`paper_translate`

```json
{
  "task_id": "task-id",
  "artifact_path": "papers/1706.03762v1.json",
  "translations": [
    {"section_id": "section_1", "translated_text": "章节译文，公式 (1) 和引用 [1] 保持不变。"}
  ]
}
```

成功返回 `paper_artifact_id`、`artifact_path`、`section_count` 和译文字符数。
缺失章节、未知章节、空译文、数字/引用/公式/术语保护失败或持久化失败均返回
`ToolResult.fail`。

## 实现步骤

1. 校验译文与 P11 sections 一一对应。
2. 校验数字 token、引用 token、公式标记和适用 glossary 目标译词。
3. 全部通过后原子更新 artifact，并生成按章节顺序拼接的全文译文。

## 依赖项

- [x] P11 `PaperArtifact.sections` 和原文
- [x] P12 `PaperArtifact.glossary`
- [x] `StatePersistence.update_paper_artifact()` 和 `ToolRegistry`

## 风险评估

| 风险点 | 影响等级 | 应对措施 |
|---|---|---|
| 译文遗漏数字或引用 | 高 | 比较原文和译文的 token 计数 |
| 公式被自然语言改写 | 高 | 对含公式章节要求译文保留公式标记 |
| 术语前后不一致 | 中 | 对章节中出现的 glossary 术语要求目标译法出现 |
| 部分章节成功、后续失败 | 高 | 所有章节先校验，通过后一次性更新 |
