# P14 论文总结与解释

## Summary

为 P11/P13 论文 artifact 增加结构化总结与解释能力。Research Agent 生成研究问题、
方法、贡献、结论和局限候选，`paper_summary` 工具校验证据章节并原子持久化。

**Repositories Involved:** `paper_research_agent`

## Scope

### In scope

- 接受已解析论文和结构化总结候选。
- 保存研究问题、方法总结、贡献、结论和局限。
- 要求每类总结提供一个或多个有效 section ID 作为证据来源。
- 保存 `summary_evidence` 以支持后续 Evaluation Agent 复核。
- 原子更新 `PaperArtifact` 和 Manifest。

### Out of scope

- 自动调用外部知识源补充论文未提及的内容。
- 语义事实正确性的最终判定。
- 代码复现、实验结果和最终复现报告。

## Design

Research Agent 生成结构化 JSON，工具只执行字段、证据章节和持久化校验。证据
章节来自 P11 的 `PaperArtifact.sections`，不允许引用不存在的 section。

```text
P11/P13 PaperArtifact
  + Research Agent summary candidates
  -> PaperSummaryTool field/evidence validation
  -> summary fields + summary_evidence
  -> atomic JSON update + Manifest
```

## Contract

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

总结内容为空、字段类型错误、证据 section 缺失或持久化失败必须返回失败。

## Risks and rollback

| Risk | Mitigation |
|---|---|
| 总结混入论文外知识 | 要求所有总结类别提供原文 section 证据 |
| 引用不存在章节 | 工具只接受 artifact 中已存在的 section ID |
| 总结字段格式不一致 | Pydantic artifact 和工具逐字段校验 |
| 持久化失败 | 复用原子 artifact 更新并传播错误 |
