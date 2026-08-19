# 决策记录

**需求ID**：A03  
**需求名称**：REVISE重试策略优化

---

## 关键决策

### 1. 推翻A01"REVISE保留history"决策
- **问题**：A01为REVISE做了"不重置history"的特殊处理，实际会导致LLM被上一轮错误plan锚定，且旧results_prompt（3000-8000字）冗余
- **决策**：REVISE时也调用start_new_phase(force=True)重置context，像新阶段一样干净
- **原因**：保留旧历史弊大于利（锚定+冗余），通过精准注入correction_notes和已有数据消息传递必要信息，比保留全量历史更有效

### 2. 不做滑动窗口，改为REVISE策略优化
- **问题**：最初A03定位为"阶段内滑动窗口"，但max_revisions=1（最多2轮），滑动窗口无意义
- **决策**：A03改为REVISE重试策略优化，核心是重置context+精准传递修正信息
- **原因**：用户指出"失败重试应该定位根因、保存断点、超次终止"，滑动窗口是次优方案，正确做法是重置上下文避免锚定，精准传递修正指令

### 3. 不做断点续跑（3c），标记P2
- **问题**：是否自动跳过已成功步骤，避免重复执行工具
- **决策**：第一版不做，LLM自主决定是否复用已有数据
- **原因**：当前阶段（paper_retrieval等）工具多为幂等操作（arxiv_search等），重复执行成本低；断点续跑需要plan diff、参数匹配、缓存管理，复杂度高，ROI低。实验执行阶段（单次实验几分钟）才是断点续跑的刚需场景

### 4. 已有数据传完整compact结果（含abstract），不限量id列表
- **问题**：上一轮成功工具的结果，传给第二轮时是传id列表还是完整compact结果
- **决策**：传完整compact结果（arxiv_id/title/authors/published/categories/abstract_preview[:200]），去重后≤30篇
- **原因**：LLM做筛选需要看abstract判断相关性，只传id/title不够；30篇×300字≈9000字，在128K窗口内安全

### 5. 失败根因落盘但不传给下阶段context
- **问题**：REVISE最终PASS后，失败信息是否传递给下一阶段
- **决策**：失败信息存metadata["phase_failures"]给开发者分析，不进入运行时context
- **原因**：和A01决策一致：失败信息对下一阶段Agent执行是噪音，对开发者优化系统宝贵，分离存储

### 6. 异常降级而非阻断
- **问题**：_build_correction_notes()遇到数据不完整（如无eval_result）是否抛错
- **决策**：catch异常，ERROR日志，降级为"上一轮数据不完整，请重新完整规划"
- **原因**：correction生成失败不应该阻止REVISE重试，最坏情况就是没有精准提示让LLM重规划，比直接BLOCKED好
