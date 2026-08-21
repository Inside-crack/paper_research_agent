# P11 论文结构解析

## Summary

为 P10 获取的论文 artifact 增加确定性的 PDF 结构解析能力，产出可供术语表、
分章节翻译和总结阶段使用的 `PaperArtifact.sections` 与原文内容。

**Repositories Involved:** `paper_research_agent`

## Scope

### In scope

- 读取 P10 生成的 `PaperArtifact` 和 PDF。
- 提取页级文本和全文原文。
- 识别常见章节标题、章节层级和章节正文。
- 识别公式、表格、图片和引用的文本线索。
- 原子更新 `PaperArtifact`，记录解析文件和解析错误。
- 通过工具返回结构化解析摘要。

### Out of scope

- 翻译、术语表生成和 LLM 总结。
- 对复杂双栏、扫描件 OCR 和数学公式进行视觉级恢复。
- 代码定位、实验执行和复现报告。

## Design

新增 `paper_parse` 工具，使用 `pdfplumber` 完成文本提取，使用确定性正则规则
识别章节和内容线索。完整 PDF 继续由 P10 artifact 保存，解析结果覆盖更新同一
`PaperArtifact` JSON，避免产生多个不一致的论文元数据副本。

```text
PaperArtifact JSON + PDF
  -> PaperParseTool
  -> pdfplumber page text extraction
  -> heading/section/evidence detection
  -> PaperArtifact.sections + full_text_original
  -> atomic JSON update + Manifest
```

## Contract

工具名：`paper_parse`

输入：

```json
{
  "task_id": "task-id",
  "artifact_path": "papers/1706.03762v1.json"
}
```

成功输出：

```json
{
  "paper_artifact_id": "artifact-id",
  "artifact_path": "papers/1706.03762v1.json",
  "page_count": 8,
  "section_count": 6,
  "text_length": 12345,
  "parsing_errors": []
}
```

缺失 artifact、PDF、非法路径或不可读取 PDF 时返回失败；提取成功但部分页面
失败时保留已提取文本并在 `parsing_errors` 中记录页面和错误。

## Risks and rollback

| Risk | Mitigation |
|---|---|
| PDF 双栏文本顺序异常 | 保留原始页文本，并记录解析结果边界，不宣称视觉级还原 |
| 标题识别误判 | 只使用编号标题和白名单标题规则，未识别时保留一个 Document section |
| PDF 部分页面损坏 | 页面级捕获异常，保留已成功页面并写入 parsing_errors |
| 解析结果与 PDF 不一致 | 原 PDF 不修改，PaperArtifact 原子更新并保留完整原文 |
