# P05 研究主题拆解 - 实现方案

## 方案概述
研究主题拆解作为task_initialization阶段的一部分，由Research Agent通过LLM理解用户自然语言query，拆解为可检索的结构化关键词和约束。

## 设计思路
1. **Prompt驱动拆解**：在task_initialization阶段prompt中明确要求提取domain/keywords/focus_areas
2. **中英文关键词**：同时生成中文和英文检索关键词（arxiv需要英文）
3. **关键词扩展**：LLM自动补充同义词、相关术语
4. **约束识别**：提取时间范围、论文类型、关注重点等约束条件
5. **结构化输出**：拆解结果保存到ResearchSpec.keywords字段

## 拆解维度
- 研究领域（domain）
- 核心关键词（中英文）
- 子主题/关注点（focus_areas）
- 时间约束（time_range）
- 排除项（如果有）

## 相关文件
- `prompts/research_agent/phases/task_initialization.txt`
- `src/paper_agent/common/models/research_spec.py` - ResearchSpec.keywords字段
