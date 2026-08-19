# 需求实现进展

**需求ID**：C03  
**需求名称**：多维权重打分丢弃  
**优先级**：P1  
**当前状态**：✅ 已完成简化版MVP  
**创建日期**：2026-08-14
**完成日期**：2026-08-17

---

## 需求描述

非锚点内容按权重打分，从最低分开始丢弃；丢弃后注入压缩提示。MVP阶段采用简化版priority权重，完整多维权重（时效性/信息密度/依赖/错误状态）留待后续迭代。

## MVP简化方案

不做复杂的多维权重计算，采用消息类型的静态priority分数：

| priority | 消息类型 | 丢弃顺序 |
|----------|---------|---------|
| 100 | System/Spec/Notice | 永不丢弃（锚点） |
| 95 | Phase Summaries | 永不丢弃（锚点） |
| 90 | Phase Prompt/Eval Prompt | 永不丢弃（锚点） |
| 85 | REVISE previous_results | 永不丢弃（锚点） |
| 80 | Results Prompt | 永不丢弃（锚点） |
| 50 | Synthesize Response（最近输出） | 较晚丢弃 |
| 40 | Plan Response（旧plan草稿） | 较早丢弃 |
| 20 | Retry Correction（解析错误提示） | 最先丢弃 |

## 丢弃算法

1. 过滤出所有非锚点、非SYSTEM的候选消息
2. 按(priority, index)升序排序（priority越低越先丢，同priority越老越先丢）
3. 逐个加入remove_ids集合，每次重算当前token数
4. 降到target(75%)以下则停止
5. CRITICAL时：直接保留锚点+最后2条消息，其余全丢
6. 丢弃后注入"Context compressed"通知（锚点）

## 核心验收点

- [x] 非锚点消息按priority升序丢弃（priority低的先丢）
- [x] 同priority的消息按位置顺序（越老越先丢）
- [x] 每次丢弃后重算token数，降到75%目标即停止
- [x] CRITICAL级别激进丢弃（锚点+最后2条）
- [x] 丢弃N条后注入notice消息说明压缩情况
- [x] 丢弃后锚点相对顺序保持不变

## 后续迭代（完整多维打分）

后续可扩展为4维加权打分：
- 时效性（0-25）：最近2轮满分，老消息衰减
- 信息密度（0-25）：含数据/结论/artifact引用的高分
- 依赖关系（0-25）：其他消息引用的高分
- 错误状态（0-25）：失败/错误信息高分（不可丢弃）

综合分 = 时效性×0.3 + 信息密度×0.25 + 依赖×0.25 + 错误×0.2

当前MVP用静态priority已覆盖核心场景。

## 测试覆盖（test_c01_c02_c03_context_overflow.py）

- priority顺序丢弃验证（low_pri先丢）
- 压缩后降到75%目标以下
- CRITICAL保留锚点+tail
- 锚点顺序保持
- 真实场景模拟（paper_retrieval消息序列）

## 进度概览

- [x] 方案设计确认（grill-me确定MVP简化版）
- [x] priority静态权重方案
- [x] 压缩算法实现（排序+逐个移除+重算）
- [x] CRITICAL激进压缩
- [x] 单元测试通过（15/15）
- [x] 旧测试无回归（46个全过）
- [x] 需求验收
