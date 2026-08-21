# P12 术语表生成

## Summary

为已完成 P11 解析的 `PaperArtifact` 增加术语表生成和持久化能力。Research Agent
负责根据论文原文提出中英文术语映射，系统工具负责确定性校验、去重、排序和保存。

**Repositories Involved:** `paper_research_agent`

## Scope

### In scope

- 接受 P11 解析后的 `PaperArtifact` 和 Research Agent 生成的术语候选。
- 校验术语源词确实出现在论文原文中。
- 校验目标译词、上下文和置信度字段。
- 按源术语大小写不敏感去重，保留最高置信度项。
- 原子更新 `PaperArtifact.glossary` 并登记 Manifest。

### Out of scope

- 自动调用外部翻译服务。
- 没有原文证据时凭空生成术语。
- 分章节全文翻译和论文总结。

## Design

新增 `paper_glossary` 工具。LLM 只负责生成候选 JSON，工具不调用 LLM；工具将
候选映射成 `TermEntry`，执行证据和字段检查后更新 P11 artifact。

```text
P11 PaperArtifact
  + Research Agent term candidates
  -> PaperGlossaryTool validation/deduplication
  -> PaperArtifact.glossary
  -> atomic JSON update + Manifest
```

## Contract

输入：

```json
{
  "task_id": "task-id",
  "artifact_path": "papers/1706.03762v1.json",
  "terms": [
    {
      "source_term": "chain-of-thought",
      "target_term": "思维链",
      "context": "reasoning traces",
      "confidence": 0.95
    }
  ]
}
```

成功输出包含 artifact ID、术语数量和去重后的术语列表。空列表是合法结果，
表示当前论文没有新增术语。非法字段、低置信度、源术语无原文证据和持久化失败
必须返回失败。

## Risks and rollback

| Risk | Mitigation |
|---|---|
| LLM 生成不存在于原文的术语 | 工具执行大小写不敏感原文证据校验 |
| 同一术语多种译法 | 以最高置信度保留一项，并按稳定规则排序 |
| 术语上下文过长 | 限制 context 长度，完整原文仍由 sections 保存 |
| artifact 更新失败 | 复用原子更新并传播 Manifest 错误 |
