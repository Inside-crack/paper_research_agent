# 项目文档索引

本文档是项目文档入口。文档按生命周期和用途组织，现有固定路径保持不变，
避免影响 SuperSpec/OpenSpec 工作流。

## 目录

| 目录 | 用途 | 生命周期 |
|---|---|---|
| [`DEVELOPMENT_WORKFLOW.md`](./DEVELOPMENT_WORKFLOW.md) | 标准研发流程 | 长期维护 |
| [`REQUIREMENTS_AUDIT.md`](./REQUIREMENTS_AUDIT.md) | 需求与代码实现对账 | 定期更新 |
| [`plans/`](./plans/) | 可执行开发计划 | 按需求长期留档 |
| [`proposals/`](./proposals/) | 技术提案和架构决策前置文档 | 按需求长期留档 |
| [`decisions/`](./decisions/) | 跨需求、跨模块的长期设计决策 | 长期维护 |
| [`archive/`](./archive/) | 已废弃或被新文档替代的普通文档 | 只读归档 |

## 需求文档

需求的权威过程文档位于 [`../requirements/`](../requirements/)：

```text
requirements/
├── requirements_summary.md
├── 5.1_任务管理/P01_任务创建/
├── 5.2_论文检索与筛选/P05_研究主题拆解/
├── 5.3_论文获取解析与翻译/P10_全文与版本获取/
├── 5.4_代码数据与复现资源/P15_官方代码定位/
├── 5.5_复现规划与实验执行/P19_复现目标定义/
├── 5.6_结果分析与报告/P25_实验指标提取/
├── 5.7_上下文管理系统/
└── 非功能需求/N01_安全隔离/
```

每个具体需求目录固定保留：

```text
solution.md       方案和接口
progress.md       实现进度和验证记录
blockers.md       卡点、风险和环境限制
resolutions.md    卡点解决方案和决策记录
```

## OpenSpec 文档

OpenSpec 文档不移动到 `docs/`：

- `openspec/specs/`：当前生效的 baseline。
- `openspec/changes/<change-id>/`：进行中的 proposal 和 delta spec。
- `openspec/changes/archive/`：已完成并归档的 change。

执行计划仍统一放在 [`plans/`](./plans/)；计划通过后，相关 OpenSpec change
再按工作流归档。

## 命名规则

- 计划：`YYYY-MM-DD-<feature-name>.md`
- 提案：`YYYY-MM-DD-<feature-name>.md`
- 决策：`YYYY-MM-DD-<decision-name>.md`
- 归档：保留原文件名，并移动到对应的 `archive/` 子目录。
- 不删除历史文档；文档失效时增加状态说明或移动归档。

## 当前计划

- [P10 全文与版本获取](./plans/2026-08-19-paper-acquisition.md)
- [检索输入校验](./plans/2026-08-19-validate-paper-retrieval-inputs.md)
