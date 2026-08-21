# 全文与版本获取 - 实现方案

**需求ID**：P10  
**需求名称**：全文与版本获取  
**创建日期**：2026-08-14  
**最后更新**：2026-08-19

## 需求描述

Research Agent 获取论文全文并记录 arXiv ID、版本、DOI 和发布日期；Evaluation
Agent 后续检查论文版本、来源和用户指定对象是否一致。

## 方案设计

### 整体思路

P10 首版只处理 arXiv PDF。`paper_download` 工具接受 arXiv ID、arXiv PDF URL
或候选论文对象，先获取缺失的 arXiv 元数据，再校验 HTTP 响应、Content-Type、
非空内容和 `%PDF-` 文件头。校验通过后，PDF 和结构化 `PaperArtifact` 使用临时
文件、flush、fsync 和 os.replace 写入任务 artifact 目录，并更新 Manifest。

### 架构设计

```text
PaperCandidate/arXiv ID
  -> PaperDownloadTool
  -> arXiv metadata + PDF validation
  -> StatePersistence.save_paper_artifact
  -> papers/{arxiv_id}.pdf + papers/{arxiv_id}.json
  -> task Manifest files
```

工具复用现有 `ToolRegistry`、`ArxivGetPaperTool`、`PaperArtifact` 和
`StatePersistence`，不在 Orchestrator 中增加下载专用逻辑。

### 接口设计

工具名：`paper_download`

输入：

```json
{"task_id": "task-id", "arxiv_id": "1706.03762v1"}
```

或：

```json
{"task_id": "task-id", "paper": {"arxiv_id": "1706.03762v1", "pdf_url": "https://arxiv.org/pdf/1706.03762v1"}}
```

成功返回 `paper_artifact_id`、`arxiv_id`、`version`、相对 `pdf_path`、
`artifact_path`、`size_bytes` 和 `source`。任何输入、网络、PDF 校验或 Manifest
失败都返回 `ToolResult.fail`，不报告成功。

### 数据结构

`PaperArtifact` 保存任务 ID、候选 ID、arXiv ID、标题、作者、DOI、发布日期、
版本、相对 PDF 路径和来源。Manifest 同时登记 PDF 和 JSON 两个文件。

## 实现步骤

1. 新增 `StatePersistence.save_paper_artifact()`，原子写入 PDF/JSON 并登记 Manifest。
2. 新增 `PaperDownloadTool`，完成输入规范化、元数据补全、下载和 PDF 校验。
3. 注册工具，补充正向、非法输入、非 PDF、临时文件和持久化失败测试。

## 依赖项

- [x] 现有 `PaperArtifact`、`StatePersistence` 和 `ToolRegistry`
- [x] `httpx` 与 arXiv 元数据工具

## 风险评估

| 风险点 | 影响等级 | 应对措施 |
|---|---|---|
| 非 arXiv 来源 | 中 | 当前拒绝并返回明确错误，DOI/HTML 后续需求单独设计 |
| 下载中断或返回 HTML | 高 | 只写临时文件，检查内容类型、文件头和非空内容 |
| Manifest 更新失败 | 高 | 删除本次产物并返回持久化错误，禁止静默成功 |
