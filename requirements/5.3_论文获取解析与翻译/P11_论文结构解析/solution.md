# 论文结构解析 - 实现方案

**需求ID**：P11  
**需求名称**：论文结构解析  
**创建日期**：2026-08-14  
**最后更新**：2026-08-19

## 需求描述

Research Agent 解析论文章节、公式、算法、表格、图片、引用和附录；Evaluation
Agent 检查章节完整率、阅读顺序、公式表格线索和解析异常。

## 方案设计

### 整体思路

使用 `pdfplumber` 做确定性页级文本提取，使用编号标题和常见章节标题白名单
识别章节层级。完整 PDF 保留在 P10 artifact 中，P11 原子更新同一个
`PaperArtifact` JSON，写入 `full_text_original`、`sections` 和 `parsing_errors`。

当前版本提取文本层面的公式、表格、图片和引用线索，不做 OCR 或视觉级公式恢复。

### 架构设计

```text
PaperArtifact JSON + PDF
  -> PaperParseTool
  -> pdfplumber page extraction
  -> heading/evidence detection
  -> PaperArtifact.sections + full_text_original
  -> atomic JSON update + Manifest
```

### 接口设计

工具名：`paper_parse`

输入：

```json
{"task_id": "task-id", "artifact_path": "papers/1706.03762v1.json"}
```

成功返回 `paper_artifact_id`、`artifact_path`、`page_count`、`section_count`、
`text_length` 和 `parsing_errors`。缺失输入、非法路径、缺失 artifact/PDF、
PDF 打开失败或持久化失败均返回 `ToolResult.fail`。

### 数据结构

每个 `PaperSection` 保存 `section_id`、标题、层级、原文、公式/表格/图片标志和
引用编号。没有可识别标题时保存一个 `Document` section，不能丢弃全文。

## 实现步骤

1. 增加 `StatePersistence.update_paper_artifact()`，原子更新 JSON 并登记 Manifest。
2. 增加 `PaperParseTool`，完成安全路径解析、页级提取、章节识别和证据线索检测。
3. 注册 `paper_parse`，补充正向和负向测试，并同步需求记录。

## 依赖项

- [x] P10 生成的 `PaperArtifact` 和 PDF
- [x] `pdfplumber`、Pydantic、现有持久化和工具注册机制

## 风险评估

| 风险点 | 影响等级 | 应对措施 |
|---|---|---|
| 双栏 PDF 文本顺序异常 | 中 | 保留页级原文和解析错误，不宣称视觉级还原 |
| 标题识别误判 | 中 | 使用编号标题和白名单规则，无标题时回退 Document section |
| 部分页面损坏 | 高 | 页面级捕获异常，保留其他页面文本并记录页码 |
| artifact 路径越界 | 高 | 拒绝绝对路径和 `..` 路径，不读写任务目录外文件 |
