# P10 全文与版本获取

## Summary

为论文研究流程增加可验证的论文全文获取能力，将候选论文或 arXiv 标识解析为
一个经过来源、版本和 PDF 内容校验的任务 artifact，并登记到任务 Manifest。

**Repositories Involved:** `paper_research_agent`

## Scope

### In scope

- 接受 `PaperCandidate`、arXiv ID 或 PDF URL。
- 当前版本优先支持 arXiv PDF。
- 校验下载响应、PDF 文件头、非空文件和 arXiv 元数据一致性。
- 将 PDF 写入当前任务的 artifact 目录。
- 生成结构化 `PaperArtifact` 元数据并登记 Manifest。
- 保留下载失败的原始错误，不把无效文件当作成功结果。

### Out of scope

- DOI 解析及非 arXiv 论文来源。
- HTML、LaTeX 源码包和 supplementary material。
- 目标论文的人工确认交互。
- 论文 PDF 的章节解析、翻译和总结。

## Design

新增论文获取工具，复用现有 `ToolRegistry`、`StatePersistence` 和
`PaperArtifact`。工具执行流程为：

```text
输入标识
  -> 规范化 arXiv ID/PDF URL
  -> 获取 arXiv 元数据
  -> 下载到同目录临时文件
  -> 校验 HTTP、Content-Type、PDF magic bytes、非空和版本
  -> 原子替换 PDF
  -> 写 PaperArtifact JSON
  -> 更新 Manifest
  -> 返回 artifact 引用
```

下载文件与 JSON artifact 均使用临时文件、flush、fsync 和原子替换。核心状态或
Manifest 更新失败时工具必须返回失败结果并保留上游错误信息。

## Contract

工具名：`paper_download`

输入：

```json
{
  "paper": {
    "arxiv_id": "1706.03762v1",
    "title": "Attention Is All You Need",
    "pdf_url": "https://arxiv.org/pdf/1706.03762v1"
  },
  "task_id": "task-id"
}
```

也允许使用：

```json
{"arxiv_id": "1706.03762v1", "task_id": "task-id"}
```

输出成功：

```json
{
  "paper_artifact_id": "paper-artifact-id",
  "arxiv_id": "1706.03762v1",
  "version": "1",
  "pdf_path": "papers/1706.03762v1.pdf",
  "artifact_path": "papers/1706.03762v1.json",
  "size_bytes": 12345,
  "source": "arxiv"
}
```

输出失败：`ToolResult.fail`，错误必须说明失败阶段，且不得登记成功 artifact。

## Risks and rollback

| Risk | Mitigation |
|---|---|
| 响应不是 PDF 但状态码为 200 | 同时检查 Content-Type 和 `%PDF-` 文件头 |
| 下载中断留下半文件 | 仅写入临时文件，校验成功后原子替换 |
| 版本元数据不一致 | 以明确版本的 arXiv ID 获取元数据并做 ID 校验 |
| Manifest 更新失败 | 删除本次临时/目标产物并返回失败，阻止流程继续 |

回滚方式：删除新增工具、delta change 和 P10 产物文件；不修改既有检索接口。
