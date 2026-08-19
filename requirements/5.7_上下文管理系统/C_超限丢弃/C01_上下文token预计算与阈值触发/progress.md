# 需求实现进展

**需求ID**：C01  
**需求名称**：上下文token预计算与阈值触发  
**优先级**：P0  
**当前状态**：✅ 已完成（与C02/C03同步实现）
**创建日期**：2026-08-14
**完成日期**：2026-08-17

---

## 需求描述

每次LLM调用前，预估当前message_history总token数，在70%/85%/95%窗口位置分别触发不同级别的压缩，不要等API报错后被动处理。

## 核心验收点

- [x] 预估token：使用4chars≈1token近似估算（estimate_tokens函数），不需要极度精确，快速且无依赖
- [x] 三级阈值：70%→WARNING日志；85%→COMPRESS按priority丢弃非锚点；95%→CRITICAL激进压缩（保留锚点+最后2条）
- [x] 每次压缩后重新计算token数，直到降到target(75%)以下或无更多可丢弃消息
- [x] 压缩事件结构化日志：压缩前token/压缩后token/触发级别/丢弃N条消息

## 实现方案

### Token估算

```python
CHARS_PER_TOKEN_ESTIMATE = 4
def estimate_tokens(messages) -> int:
    # sum(len(content) // 4) per message, min 1 token per message
```

### 阈值配置

| 级别 | 比例 | 动作 |
|------|------|------|
| WARNING | 70% | 日志info级别记录，不修改messages |
| COMPRESS | 85% | 按priority从低到高丢弃非锚点消息，降到75%目标 |
| CRITICAL | 95% | 激进丢弃：只保留锚点+SYSTEM+最后2条消息 |

Context window默认128K tokens（deepseek-v4-flash），预留4096 tokens给输出。

### 关键文件

- **src/paper_agent/common/llm/base.py**：
  - `estimate_tokens()`：token估算
  - `compress_messages()`：核心压缩逻辑（三级触发+priority排序丢弃+notice注入）
  - `BaseLLM._prepare_messages()`：agenerate前调用的统一入口
  - `DEFAULT_CONTEXT_WINDOW/RESERVED_OUTPUT_TOKENS`：常量配置
- **src/paper_agent/common/llm/openai_llm.py**：agenerate开头调用`self._prepare_messages(messages)`

## 测试覆盖（test_c01_c02_c03_context_overflow.py）

- 基础token估算（空/单条/多条）
- 低于阈值不压缩
- COMPRESS后token数降到75%以下
- 压缩后注入notice消息
- 边界情况（空列表/单条消息/全锚点无法压缩）

## 进度概览

- [x] 方案设计确认（grill-me确认7个维度）
- [x] 接口/模型定义（LLMMessage.metadata字段）
- [x] 核心逻辑实现
- [x] 单元测试通过（15/15）
- [x] 旧测试无回归（A01/A03/A04/B01+B02共46个全过）
- [x] 需求验收

## 进展记录

### 2026-08-14

- 需求文档生成，等待实现

### 2026-08-17

- 与C02/C03同步grill-me确认7个维度
- 实现estimate_tokens/compress_messages/_prepare_messages
- OpenAILLM.agenerate前调用_prepare_messages
- 单元测试15/15通过，旧测试无回归
