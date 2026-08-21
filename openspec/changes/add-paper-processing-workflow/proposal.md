# P30 产物驱动论文处理工作流

## Summary

修复 P10-P14 在真实 Orchestrator + Research Agent 运行中的动态上下文缺陷。
保留 `PAPER_PARSING` 顶层阶段，在内部增加五个可持久化子步骤，由 Orchestrator
固定控制依赖和顺序，Research Agent 负责当前步骤的内容生成。

## Scope

### In scope

- `download -> parse -> glossary -> translate -> summary` 子步骤。
- 子步骤状态、输入输出 artifact、revision 和错误持久化。
- 每步完成后的动态上下文注入。
- 每步独立 Evaluation、一次定向 REVISE 和 BLOCKED。
- 第一篇候选固定选择，不自动切换。
- 旧 `PAPER_PARSING` artifact 和 checkpoint 兼容。

### Out of scope

- P15-P29。
- 新增顶层 `TaskPhase`。
- 自动切换第二篇论文。
- OCR、视觉解析、外部翻译服务和人工候选确认。

## Design decision

当前单次静态 ExecutionPlan 无法预先知道 P10-P14 的动态输出。改造为
Orchestrator 驱动的子步骤闭环：

```text
select candidates[0]
 -> execute download
 -> inject artifact_path
 -> execute parse
 -> inject sections
 -> execute glossary
 -> inject glossary
 -> execute translate
 -> inject translations
 -> execute summary
```

Research Agent 不再一次性规划所有 P10-P14 工具调用；它只为当前子步骤生成候选
内容，工具执行确定性校验和持久化。
