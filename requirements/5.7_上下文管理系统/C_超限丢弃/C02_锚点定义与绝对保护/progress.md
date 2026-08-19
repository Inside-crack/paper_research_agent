# 需求实现进展

**需求ID**：C02  
**需求名称**：锚点定义与绝对保护  
**优先级**：P0  
**当前状态**：✅ 已完成（与C01/C03同步实现）
**创建日期**：2026-08-14
**完成日期**：2026-08-17

---

## 需求描述

定义锚点消息清单，任何压缩操作（B层替换/C层丢弃）都不能删除或修改锚点消息。

## 锚点清单与优先级

| 消息类型 | anchor | priority | 说明 |
|---------|--------|----------|------|
| System Prompt | ✅ | 100 | 角色定义，永不丢弃 |
| Research Spec | ✅ | 100 | 用户原始研究需求，永不丢弃 |
| Phase Summaries（前序摘要卡） | ✅ | 95 | 前序阶段关键结论，每卡≤200字 |
| Eval Prompt | ✅ | 90 | Eval Agent当前评估任务指令 |
| Phase Prompt（当前阶段任务指令） | ✅ | 90 | 当前阶段任务说明，含CORRECTION |
| REVISE previous_results | ✅ | 85 | 上一轮可用数据（REVISE场景） |
| Results Prompt（工具执行结果） | ✅ | 80 | synthesize核心输入 |
| Compress Notice（压缩提示） | ✅ | 100 | 压缩后自动注入的提示 |
| Synthesize Response | ❌ | 50 | LLM输出（保留但非锚点） |
| Plan Response（旧plan草稿） | ❌ | 40 | 老轮次plan，优先丢弃 |
| Retry Correction（JSON错误提示） | ❌ | 20 | 解析错误重试，最低优先级 |
| SYSTEM角色消息（即使未标记） | ✅ 保护 | - | 硬编码保护，不丢弃 |

## 核心验收点

- [x] anchor=True的消息在任何压缩级别下都不被丢弃
- [x] role=SYSTEM的消息即使没有anchor标记也受硬保护
- [x] 非锚点消息按priority从低到高丢弃
- [x] 压缩后注入"Context compressed"通知消息（锚点，priority=100）
- [x] 锚点相对顺序在压缩后保持不变
- [x] inject_message()增加anchor/priority参数支持

## 关键实现

- LLMMessage增加metadata字段（anchor:bool, priority:int, msg_type:str）
- LLMMessage增加is_anchor和priority属性
- BaseLLM.system_message/user_message/assistant_message工厂方法增加anchor/priority参数
- compress_messages中candidates过滤掉is_anchor和SYSTEM消息
- CRITICAL级别额外保留最后2条非锚点消息（避免上下文断裂）

## 测试覆盖（test_c01_c02_c03_context_overflow.py）

- 锚点永不丢弃（3个锚点+20个filler，压缩后锚点全部保留）
- SYSTEM消息即使未标记anchor也受保护
- 锚点相对顺序保持不变
- 全锚点场景无法进一步压缩时保留全部+notice

## 进度概览

- [x] 方案设计确认（grill-me）
- [x] LLMMessage.metadata扩展
- [x] Agent层所有消息打标
- [x] 锚点保护逻辑
- [x] 单元测试通过
- [x] 旧测试无回归
- [x] 需求验收
