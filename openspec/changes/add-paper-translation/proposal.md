# P13 分章节翻译

## Summary

为 P11 解析出的论文章节增加分章节中文翻译持久化能力。Research Agent 生成译文，
`paper_translate` 工具执行章节覆盖、内容保护和术语一致性校验。

**Repositories Involved:** `paper_research_agent`

## Scope

### In scope

- 接受 P11 `PaperArtifact.sections` 和逐章节译文。
- 要求每个 section 恰好有一份非空译文。
- 校验数字、引用和公式线索未被删除。
- 校验已确认 glossary 术语在对应译文中保持目标译法。
- 更新 `PaperSection.translated_text` 和 `full_text_translated`。
- 原子保存 artifact 并登记 Manifest。

### Out of scope

- 外部翻译服务或独立翻译模型调用。
- OCR、视觉公式恢复和人工翻译编辑器。
- 论文总结和复现相关功能。

## Design

Research Agent 负责生成译文候选，工具不调用 LLM。工具根据 artifact 中的原文、
section、glossary 和内容标记执行确定性检查，失败时不更新 artifact。

```text
P11 sections + glossary
  + Research Agent translations
  -> PaperTranslateTool protection/coverage checks
  -> translated sections + full_text_translated
  -> atomic JSON update + Manifest
```

## Contract

输入：

```json
{
  "task_id": "task-id",
  "artifact_path": "papers/1706.03762v1.json",
  "translations": [
    {"section_id": "section_1", "translated_text": "这是章节译文，公式 (1) 和引用 [1] 保持不变。"}
  ]
}
```

成功返回 artifact ID、翻译章节数、译文字符数和 artifact 路径。缺失章节、未知
章节、空译文、数字/引用/公式线索丢失、术语译法丢失和持久化失败均返回失败。

## Risks and rollback

| Risk | Mitigation |
|---|---|
| 译文遗漏数字或引用 | 工具比较原文和译文的数字 token、引用 token |
| 公式被自然语言改写 | 对标记为含公式的章节要求译文保留公式线索 |
| 术语前后不一致 | 对 glossary 中出现于章节原文的术语要求目标译法出现 |
| 部分章节成功、后续失败 | 所有章节先校验，全部通过后一次性原子更新 |
