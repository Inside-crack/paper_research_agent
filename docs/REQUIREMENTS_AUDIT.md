# 需求清单审计

**审计日期**：2026-08-19  
**审计依据**：`requirements/`、`src/paper_agent/`、`examples/`、`openspec/specs/`  
**审计原则**：以代码和可执行测试判断当前行为，以需求文档判断目标范围；不把规划项统计为已完成。

## 总体结论

项目的 Research Agent、Evaluation Agent、Orchestrator、上下文管理和持久化基础设施
已经形成可运行框架，论文检索链路已具备基础实现，当前迭代聚焦论文研究和翻译：

```text
任务初始化 -> 论文检索 -> 全文获取 -> 结构解析
                                      -> 术语表 -> 分章节翻译 -> 总结解释

代码定位、复现执行和结果报告保留为后续大规模迭代，不作为当前近期交付目标。
```

当前最适合继续推进的是 **P10 全文与版本获取**。P09 目标论文确认依赖交互入口
决策（CLI、Web 或对话），暂不把它作为下一项实现。

## 1. 已有代码和测试支撑的能力

| 能力 | 需求范围 | 当前判断 | 证据 |
|---|---|---|---|
| 任务生命周期 | P01-P04 | 核心实现存在，恢复和入口仍需补强 | `orchestrator.py`、`task_state.py`、任务/阶段测试 |
| 论文检索 | P05-P08 部分 | arXiv 检索、去重、压缩、基础分类/排序框架存在 | `arxiv_tool.py`、Research/Evaluation Agent、检索测试 |
| 上下文管理 | A01-A04、B01-B02、C01-C03 | 已实现并有测试；部分旧文档状态滞后 | `agent_base.py`、上下文测试、`context_management_summary.md` |
| 索引与持久化 | D01-D04、E01-E04 | MVP 已实现并有测试；E04 明确只做 checkpoint 保留 | `persistence/`、索引/错误持久化测试 |
| 评估门禁 | Evaluation 机制 | PASS/REVISE/BLOCKED、确定性检查和结构化结果存在 | `evaluation_agent/agent.py`、`evaluation_result.py` |

## 2. 尚未形成完整业务能力的部分

| 能力 | 需求范围 | 当前判断 | 主要缺口 |
|---|---|---|---|
| 目标论文确认 | P09 | 未开始 | 缺少交互入口和确认状态协议 |
| 全文与版本获取 | P10 | 首版已完成 | 支持 arXiv PDF 下载、版本/PDF 校验、PaperArtifact 和 Manifest 登记 |
| 论文结构解析 | P11 | 基础版已完成 | `paper_parse.py`、P11 focused tests；文本层章节和证据线索解析 |
| 术语表生成 | P12 | 基础版已完成 | `paper_glossary.py`；候选证据校验、去重和持久化 |
| 分章节翻译 | P13 | 基础版已完成 | `paper_translate.py`；章节覆盖和原始证据保护 |
| 论文总结与解释 | P14 | 基础版已完成 | `paper_summary.py`；结构化总结和 section 证据映射 |
| 代码定位与映射 | P15-P18 | 预留目录 | `tools/code/` 尚无实际工具 |
| 复现规划与执行 | P19-P24 | 模型和 host sandbox 框架存在 | Docker 执行仍是 placeholder，缺少完整实验契约 |
| 结果分析与报告 | P25-P29 | 模型已定义 | 缺少指标提取、对比、差异归因和报告生成流程 |
| 非功能需求 | N01-N08 | N01-N07 有基础设施，N08 未开始 | 安全、真实性、隐私和审计仍需按业务工具补齐 |

## 3. 清单数据质量问题

`requirements/requirements_summary.md` 的统计仍显示“已完成 0”，与代码、测试和
`requirements/5.7_上下文管理系统/context_management_summary.md` 冲突。后续更新时：

- 以代码、测试和可复现命令作为完成证据；
- 以 `progress.md` 记录当前实现状态；
- 不直接把总表百分比当作实现事实；
- 上下文 A-E 的已完成状态需要后续单独同步回总表；
- P09 的交互入口需要先做产品决策。

## 4. 下一里程碑：P11

### 选择原因

1. P11 是全文获取和术语、翻译、总结之间的直接桥梁；
2. P10 已提供经过校验的 PDF 和 `PaperArtifact` 输入；
3. P11 不依赖代码仓库、GPU 或 Docker；
4. 结构化章节产物可以直接支持 B03 PDF 内容压缩；
5. P11 完成后才能稳定推进 P12-P14。

### P11 范围

本次 grill-me 需要确认以下内容，未确认前不写代码：

- 输入为 P10 生成的 `PaperArtifact.pdf_path`；
- 优先解析 PDF 文本、标题、摘要、章节层级、公式、表格、图片和引用；
- 完整原文落盘，Context 只保留结构摘要和章节 artifact 引用；
- 解析失败必须保留 `parsing_errors` 并进入 Evaluation 门禁；
- 不在 P11 中实现翻译、代码定位或实验执行。

## 5. 推荐后续顺序

```text
P11 论文结构解析
  -> P12 术语表
  -> P13 分章节翻译
  -> P14 论文总结
  -> P09 目标论文确认（交互入口确定后并行推进）

后续保留链路：

P15-P18 代码定位
  -> P19-P24 复现规划与执行
  -> P25-P29 结果分析与报告
```
