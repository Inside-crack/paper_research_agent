# P31 多论文对比分析工作流 - 实现进展

**需求ID**：P31  
**需求名称**：多论文对比分析工作流  
**当前状态**：基础骨架已完成，完整解析接入待开发  
**开始日期**：2026-08-27  
**实际完成**：未完成

## 进度概览

- [x] 明确独立 `PaperComparisonWorkflow` 方案
- [x] 明确与 `PaperProcessingWorkflow` 的职责边界
- [x] 明确本地 PaperArtifact/PDF 复用策略
- [x] 明确在线论文获取回退策略
- [x] 明确 `compare_papers` 触发和确认链路
- [x] 明确 `PaperComparisonArtifact` 作为主产物
- [x] 新增 `ComparisonSpec`
- [x] 新增 `PaperComparisonArtifact`
- [x] 实现本地论文资源查询
- [x] 实现 `PaperAcquisitionService`
- [x] 实现 `PaperComparisonWorkflow`
- [x] 注册 `compare_papers` 能力
- [x] 接入基础确认和任务启动链路
- [x] 实现基础对比结果持久化
- [x] 增加基础单元、Workflow 和路由测试
- [x] 接入已有 P10-P14 解析产物的完整跨任务查询
- [x] 实现多论文来源冲突检测与确定性合并
- [x] 实现 Markdown、HTML 和 CSV 展示导出
- [ ] 接入 LLM 对比分析
- [ ] 增加完整 CLI 对比任务验收

## 当前可复用能力

- `ConversationApplicationService`
- `Orchestrator`
- `PaperProcessingWorkflow`
- `arxiv_get_paper`
- `paper_download`
- `paper_parse`
- `paper_summary`
- `PaperArtifact`
- `StatePersistence`
- Manifest、checkpoint 和事件流
- Pydantic artifact 校验

## 本批实现文件

- `src/paper_agent/common/models/paper_comparison.py`
- `src/paper_agent/common/comparison_export.py`
- `src/paper_agent/common/paper_acquisition.py`
- `src/paper_agent/workflows/paper_comparison.py`
- `src/paper_agent/common/capabilities/paper_comparison.py`
- `src/paper_agent/common/conversation_application_service.py`
- `src/paper_agent/common/capabilities/router.py`
- `src/paper_agent/common/capabilities/catalog.py`
- `src/paper_agent/common/capabilities/registry.py`
- `examples/test_p31_paper_comparison_foundation.py`
- `examples/test_p31_compare_papers_capability.py`
- `examples/test_p31_comparison_export.py`

## 跨任务产物复用实现

`PaperAcquisitionService` 默认扫描配置的 artifact/workspace 根目录，
按以下顺序复用：

```text
完整 PaperArtifact > 部分 PaperArtifact > 本地 PDF > 在线元数据 > 下载 PDF
```

历史 `PaperArtifact` 按 P10-P14 完成度排序，完整度信息写入：

```text
reuse_level
reused_from_task_id
available_stages
```

对比产物中的每篇论文会保留上述复用信息以及原始 artifact/PDF 路径。

## 冲突检测与合并实现

- 显式本地 artifact 与目标论文 ID 不一致：阻断，不回退到其他来源。
- 同一论文的多个历史 artifact：按 P10-P14 完整度和文件更新时间选择主来源。
- 标题、版本、方法总结和结论不一致：记录 `PaperConflict`，主来源优先。
- 主来源字段为空：仅从低优先级来源补齐，不覆盖已有事实。
- 对比 artifact 保存论文级和任务级冲突记录。

## 可视化展示与导出实现

对比任务完成后自动生成：

```text
paper_comparison.json
paper_comparison.md
paper_comparison.html
paper_comparison.csv
```

JSON 是主产物，HTML 提供横向矩阵展示并高亮 `unknown` 字段，Markdown
适合 CLI/IDE 阅读，CSV 适合表格工具和后续分析。HTML 内容统一进行转义，
导出文件采用原子写入。

## 当前验证情况

基础实现验证：

- P31 focused tests：12/12 通过
- 会话、路由和既有 D53 回归测试：23/23 通过
- 当前仅保留项目已有的 LibreSSL 警告

## 本批验收结果

```text
P31 focused tests: 12 passed
会话、路由和 D53 回归测试: 23 passed
全量测试: 416 passed
```

全量测试仍有项目既有的 LibreSSL 和 Pydantic 弃用警告。

## 对比产物有效性修复

真实 CLI 验收发现：仅下载 PDF 的论文没有 P10-P14 `PaperArtifact` 时，
对比 Workflow 会把所有字段置为 `unknown`，且没有注入 analyzer，最终生成
空的 `commonalities`、`differences` 和 `conclusion`。这属于错误的成功状态。

已修复：

- 没有历史解析产物时，使用 arXiv abstract/summary 提取研究问题、方法、
  训练策略、数据集与指标、实验结果和局限性候选事实；
- 没有 LLM analyzer 时提供证据受限的确定性 fallback 分析；
- 结论明确标注缺失证据，不根据缺失字段进行推断；
- 保留 `arxiv.abstract` 作为基础事实来源。

验证：

```text
comparison/retrieval tests: 23 passed
```

## P14 总结与比较分析 LLM 接入

- 对比 Workflow 新增 `artifact_enricher` 注入点。
- 缺少 P10-P14 产物时，先执行 `paper_parse`，再调用 LLM 生成带 section evidence
  的 P14 summary，并通过 `paper_summary` 工具校验后持久化。
- 已有完整 `PaperArtifact` 时直接复用，不重复解析和总结。
- 新增比较分析 LLM 调用，输入仅包含规范化论文事实和证据，不允许改写论文身份、
  实验数值或来源。
- LLM 输出经过字段白名单、列表类型和长度限制；解析失败时回退到确定性分析。
- 最终结果继续通过 `PaperComparisonArtifact` 校验并生成 JSON、Markdown、HTML、CSV。

验证：

```text
P31 comparison tests: 10 passed
全量测试: 417 passed
```

## 真实 CLI 端到端验收

使用 CLI 对 `2112.15093v2` 和 `2402.13643v1` 重新执行对比任务，任务 ID：

```text
2049b1c6933a4a7f90194536e1b29e32
```

验收结果：

- 两篇论文均完成 `download -> parse -> summary`；
- 每篇论文均包含 5 类 P14 `summary_evidence`；
- DeepSeek 比较分析调用成功；
- `commonalities`、`differences`、`conclusion` 均非空；
- 缺失训练参数、评估协议和不可直接横向比较的数据被记录到
  `missing_information`；
- JSON、Markdown、HTML、CSV 均成功生成。
