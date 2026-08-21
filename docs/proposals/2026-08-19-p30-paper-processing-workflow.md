# 需求澄清纪要：P10-P14 产物驱动论文处理工作流

## 1. 需求定位

- 类型：已有功能架构改造
- 模块：论文获取、解析与翻译
- 需求ID：P30
- 优先级：P0（当前真实端到端流程阻塞）
- 范围：只修复 P10-P14，不扩展到 P15-P29

## 2. 用户与场景

- 用户：终端用户通过 CLI 发起论文检索与翻译任务
- 触发阶段：`paper_retrieval` 完成并通过后进入 `paper_parsing`
- 触发条件：检索结果中存在候选论文
- 入口：Orchestrator 阶段流转
- 论文选择：使用 Research Agent 选出的第一篇候选论文，不自动切换其他候选

## 3. 功能规则

- 保留现有 `PAPER_PARSING` 顶层阶段。
- 在该阶段内部增加五个可持久化子步骤：
  `download`、`parse`、`glossary`、`translate`、`summary`。
- Orchestrator 固定控制五个子步骤的顺序和依赖。
- Research Agent 只负责当前子步骤的内容生成。
- 工具负责确定性校验和 artifact 持久化。
- 每一步完成后，真实产物必须注入下一步上下文。
- 当前子步骤允许定向 REVISE 一次，不能重新执行已通过的前置子步骤。

## 4. 边界与异常处理

| 场景 | 处理方式 |
|------|----------|
| 检索结果为空 | 直接 BLOCKED，等待用户重新输入 |
| 第一篇候选论文下载失败 | 定向 REVISE 一次；仍失败则 BLOCKED，不切换论文 |
| PDF 解析失败 | 定向 REVISE 一次；仍失败则 BLOCKED，不执行后续子步骤 |
| 术语候选非法或来源不存在 | 定向 REVISE 一次；仍失败则 BLOCKED |
| 章节翻译缺失或保护 token 丢失 | 只重试翻译子步骤；已通过章节不重译 |
| 总结缺少证据 section | 只重试总结子步骤；仍失败则 BLOCKED |
| artifact 或 Manifest 持久化失败 | 任务失败并保留错误上下文，不报告成功 |
| 任务被中断 | 保留已完成子步骤，支持从子步骤边界恢复 |
| 历史任务没有子步骤字段 | 读取时按旧 `PAPER_PARSING` 结构兼容，不要求迁移 |

## 5. 质量门禁

- 是否需要 Evaluation：是，每个子步骤独立评估
- 确定性检查项：
  - P10 artifact、PDF、版本和 Manifest 存在且一致；
  - P11 全文和 sections 非空；
  - P12 术语字段合法且 source term 出现在原文；
  - P13 section 覆盖完整，数字、引用、公式和术语保护通过；
  - P14 总结字段合法，证据 section 存在；
  - 子步骤状态和产物状态一致。
- PASS：工具成功、确定性检查通过、Evaluation Agent 返回 PASS。
- REVISE：当前子步骤结果有可定向修正的问题，最多一次。
- BLOCKED：输入不可满足、子步骤第二次失败或持久化失败。
- REVISE 修正边界：只修正当前子步骤，不重新选择论文，不重跑通过的前置步骤。

## 6. 验收标准

- [ ] P10-P14 五个子步骤按固定顺序执行并持久化状态。
- [ ] P10 输出的 artifact_path 能传给 P11。
- [ ] P11 输出的 sections 能传给 P12/P13/P14。
- [ ] P12 输出的 glossary 能传给 P13。
- [ ] P13 输出的 translations 能传给 P14。
- [ ] 子步骤 PASS 后不会被后续 REVISE 重跑。
- [ ] 检索为空时任务为 BLOCKED。
- [ ] 第一篇论文下载失败时不自动切换第二篇论文。
- [ ] 当前子步骤最多定向 REVISE 一次。
- [ ] 任意持久化失败都不会报告成功。
- [ ] 历史 `PAPER_PARSING` artifact 和任务仍可读取。
- [ ] 离线 E2E、Orchestrator E2E、现有 P10-P14 回归测试通过。

## 7. Out of Scope

- P15-P29 代码定位、实验复现和结果报告。
- 新增顶层 `TaskPhase`。
- 自动切换第二篇候选论文。
- OCR 和视觉级公式、表格识别。
- 外部翻译服务。
- 人工候选确认界面。
- P10-P14 并行执行。

## 8. 风险与依赖

- 依赖：现有 `PaperArtifact`、`TaskState`、Manifest、StatePersistence 和双 Agent 评估机制。
- 风险：修改 `TaskState` 和 Orchestrator 子步骤状态时可能影响旧 checkpoint。
- 风险：子步骤边界增加 Evaluation Agent 调用次数和 token 成本。
- 回滚：保留旧 `PAPER_PARSING` 字段和 artifact 格式，新字段全部可选。
