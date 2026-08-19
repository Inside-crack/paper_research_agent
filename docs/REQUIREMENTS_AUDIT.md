# 需求清单审计

**审计日期**：2026-08-19  
**审计依据**：`requirements/`、`src/paper_agent/`、`examples/`、`openspec/specs/`  
**审计原则**：以代码和可执行测试判断当前行为，以需求文档判断目标范围；不把规划项统计为已完成。

## 总体结论

项目的 Research Agent、Evaluation Agent、Orchestrator、上下文管理和持久化基础设施
已经形成可运行框架，但主干业务链仍停在“检索结果之后”：

```text
任务初始化 -> 论文检索 -> [全文获取] -> 结构解析 -> 代码定位
                                      -> 复现执行 -> 结果报告
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
| 全文与版本获取 | P10 | 框架存在，功能未闭环 | 下载、版本一致性、来源校验和产物登记未形成稳定契约 |
| 论文结构解析 | P11 | 未开始 | `tools/paper_processing/` 尚无解析工具 |
| 术语、翻译、总结 | P12-P14 | 未开始 | 缺少结构化中间产物和评估规则 |
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

## 4. 下一里程碑：P10

### 选择原因

1. P10 是检索和解析之间的直接桥梁；
2. 已有 `DownloadFileTool`，可以低侵入完成第一版；
3. P10 不依赖 Web UI；
4. P10 的失败路径容易确定性测试；
5. 完成后可以直接为 P11 提供 `PaperArtifact` 输入。

### 初始范围假设

本次 grill-me 需要确认以下内容，未确认前不写代码：

- 输入接受 arXiv ID、PDF URL、DOI，还是只接受 `PaperCandidate`；
- 版本选择规则是指定版本、最新版本还是候选中的版本；
- 下载文件保存到 workspace 还是 artifact；
- PDF、HTML、源码包是否都在本次范围；
- 下载失败、HTTP 错误、空文件、非 PDF 响应如何处理；
- Evaluation Agent 的版本和来源检查如何判定 PASS/REVISE/BLOCKED。

## 5. 推荐后续顺序

```text
P10 全文与版本获取
  -> P11 论文结构解析
  -> P12 术语表
  -> P13 分章节翻译
  -> P14 论文总结
  -> P09 目标论文确认（交互入口确定后并行推进）
  -> P15-P18 代码定位
  -> P19-P24 复现执行
  -> P25-P29 结果报告
```

