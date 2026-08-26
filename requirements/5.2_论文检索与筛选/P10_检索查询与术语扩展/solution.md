# P10：检索查询与术语扩展

> **需求来源：使用过程中发现的缺陷对应的修复需求**

## 1. 问题背景

在实际 CLI 试用中发现，用户使用中文描述检索主题时，系统会将中文口语直接发送给 arXiv。例如：

```text
找一下与 AI 和防火墙结合的论文
```

当前实现存在以下问题：

- arXiv 英文论文语料对中文查询支持有限，可能返回 0 篇结果；
- 中文查询中的口语和连接词会降低检索精度；
- 静态中英词表覆盖范围有限；
- LLM 翻译结果如果未经验证直接写入词表，可能污染后续检索；
- 单次查询无法覆盖同一学术概念的不同英文表达；
- arXiv 返回结果可能包含泛相关论文，需要进一步重排。

## 2. 需求边界

本需求属于论文检索流程中的：

```text
用户查询
  -> 查询理解
  -> 学术术语处理
  -> 跨语言查询扩展
  -> arXiv 检索
  -> 候选论文去重与重排
```

不负责：

- 修改 arXiv API；
- 替换现有论文下载、解析和处理 Workflow；
- 自动确认或自动启动论文处理任务；
- 未经验证将 LLM 输出永久写入正式术语库。

## 3. 子需求清单

### P10-1：查询语句规范化

清理“请、帮我、找一下、相关的、论文”等口语噪声，保留用户真正的研究主题。

验收示例：

```text
找一下与 AI 和防火墙结合的论文
-> AI 防火墙 结合
```

### P10-2：中英文学术术语映射

维护可版本化的中英文学术术语映射，至少支持：

```text
防火墙 -> firewall
网络安全 -> cybersecurity
入侵检测 -> intrusion detection
机器学习 -> machine learning
人工智能 -> artificial intelligence
多智能体协作 -> multi-agent collaboration
```

词表不能只保存字符串映射，还应支持领域、上下文、来源和置信度。

### P10-3：术语未命中检测

当用户查询中出现词表未覆盖的学术词汇时，系统应识别为 OOV 术语，并决定是否调用 LLM。

普通连接词和口语不应触发 LLM 术语翻译。

### P10-4：LLM 术语翻译兜底

对 OOV 学术术语调用 LLM，要求返回结构化结果：

```json
{
  "source_term": "源术语",
  "translations": [
    {
      "term": "candidate translation",
      "confidence": 0.92,
      "usage": "适用领域和语境"
    }
  ],
  "domain": "academic domain",
  "ambiguity": false
}
```

LLM 不应直接返回一段无法验证的自然语言。

### P10-5：动态术语缓存

LLM 产生的新术语先写入动态缓存，状态为：

```text
pending
```

只有经过验证或人工确认后，才能升级为：

```text
verified
```

还应支持：

```text
rejected
deprecated
```

### P10-6：术语冲突与领域消歧

同一个中文术语可能有多个英文翻译，应根据领域和上下文选择，而不是覆盖旧映射。

例如：

```text
载体 -> carrier / vector / vehicle
```

需要保留多个候选及其适用语境。

### P10-7：多路查询扩展

检索时保留原始查询，并生成有限数量的英文扩展查询：

```text
原始查询
AI firewall
artificial intelligence firewall
network security firewall
```

扩展查询需要设置数量上限，避免请求爆炸和 arXiv 限流。

### P10-8：候选结果去重

多个查询返回的论文需要按 arXiv ID 去重，保留：

- 首次出现的论文信息；
- 所有命中的查询；
- 最高相关性分数；
- 相关性解释。

### P10-9：候选结果相关性重排

对候选论文的标题、摘要和术语命中情况进行重排：

```text
标题命中 > 摘要命中 > 仅作者或元数据命中
```

保留 arXiv 原始排序作为兜底，避免重排结果不可解释。

### P10-10：术语和检索过程可观测

记录但不泄露敏感信息：

- 原始查询；
- 规范化查询；
- 命中的词表条目；
- LLM 新增术语；
- 查询扩展列表；
- 每个候选的命中查询；
- 结果重排原因；
- 词表命中率；
- OOV 率；
- LLM 翻译成功率。

### P10-11：安全与成本控制

需要限制：

- 单次 OOV 术语数量；
- 单次 LLM 调用次数；
- 单个术语的候选翻译数量；
- 查询扩展数量；
- 术语条目长度；
- LLM 结果写入大小。

LLM 返回内容必须经过 Schema 校验、敏感信息过滤和持久化错误处理。

### P10-12：检索效果评测

新增检索回归集，覆盖中文、英文、混合语言和歧义术语，评估：

```text
Recall@K
MRR
nDCG@K
OOV 识别率
术语翻译准确率
查询延迟
LLM 调用次数
```

至少对比：

```text
原始中文查询
静态词表查询
静态词表 + LLM 扩展
静态词表 + LLM 扩展 + 重排
```

## 4. 推荐技术方案

```text
QueryNormalizer
  -> TerminologyStore
  -> OOVDetector
  -> LLMTermTranslator
  -> TermValidator
  -> DynamicTermCache
  -> SearchPlanner
  -> ArxivSearchTool
  -> Deduplicator
  -> ResultReranker
```

术语条目建议包含：

```text
term_id
source_term
target_terms
domain
context
aliases
source
confidence
status
usage_count
created_at
updated_at
```

## 5. 重要设计原则

1. 保留用户原始查询，不用翻译结果完全替换原始意图。
2. 词表查询优先，LLM 只处理未命中的学术术语。
3. LLM 结果先进入 `pending`，不能直接成为 `verified`。
4. 术语库使用结构化条目，不采用简单的永久字符串覆盖。
5. 多路查询必须限流、去重并保持可解释性。
6. 搜索相关性排序不能依赖 LLM 自由生成的理由，必须保留可验证特征。
7. 词表和动态缓存应独立于 Router，供检索、翻译和总结流程复用。

## 6. 验收标准

- 中文检索请求可以生成有效英文术语查询；
- 已知术语不会重复调用 LLM；
- 未知学术术语可以触发结构化 LLM 翻译；
- LLM 翻译失败时仍可使用原始查询继续检索；
- 新术语不会未经审核进入正式词表；
- 多路查询结果按 arXiv ID 去重；
- 相关论文排序不低于当前单路查询基线；
- 术语冲突可以按领域和上下文区分；
- 检索过程、术语来源和重排原因可追踪；
- 旧有论文检索、候选选择、确认和 Workflow 测试全部通过。
