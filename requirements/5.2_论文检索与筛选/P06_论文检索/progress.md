# P06 论文检索 - 进展

## 当前状态：arXiv检索基础能力完成，筛选质量待优化

## 已完成
- [x] arXiv API集成（arxiv库）
- [x] ArxivSearchTool工具：
  - 支持关键词搜索
  - 支持分类过滤（cat:cs.AI/cs.CL/cs.LG等）
  - 支持结果数量控制（max_results）
  - [x] 校验非正 `max_results` 并返回 `max_results must be greater than 0`
  - 返回结构化结果：arxiv_id/title/authors/date/categories/abstract/code hint
- [x] ArxivGetPaperTool工具（获取单篇论文详情）
- [x] Orchestrator端跨查询自动去重（_deduplicate_search_results）
- [x] 结果自动压缩（只保留关键字段，abstract截断到200字符）
- [x] paper_retrieval阶段prompt：3-4次搜索→分类→排序→save_artifact
- [x] Research Agent正确生成执行计划（3-4次arxiv_search + 最终save_artifact）
- [x] Evaluation Agent检索质量检查清单

## 核心文件
- `src/paper_agent/tools/retrieval/arxiv_tool.py` - arXiv搜索工具
- `prompts/research_agent/phases/paper_retrieval.txt` - 检索阶段prompt
- `src/paper_agent/orchestrator/orchestrator.py` - _deduplicate_search_results()
- `src/paper_agent/evaluation_agent/agent.py` - PAPER_RETRIEVAL_CHECKS

## 验证情况
- ✅ 2026-08-19 完成非正 `max_results` 校验及保留行为验证：
  `PYTHONPATH=src python3 -m pytest -q examples/test_paper_retrieval_validation.py`
  通过，3 个测试全部通过
- ✅ arXiv API连通，单次返回15-20篇结果
- ✅ 多关键词组合搜索正常（multi-agent/tool-use/framework/survey等）
- ✅ Orchestrator预去重：4次搜索×15篇→去重后约40-50篇唯一论文
- ✅ save_artifact正确保存候选集
- ✅ Evaluation Agent给出质量反馈（指出URL缺失、code_available未验证等问题）

## 已知问题
- [ ] Research Agent忘记在candidates中包含arxiv_url/pdf_url字段（Evaluation已识别）
- [ ] code_available字段全部标记为false，未实际验证（需要GitHub搜索工具）
- [ ] 缺少筛选依据记录（哪篇来自哪个查询、排除理由）
- [ ] 2024年以前的论文未过滤干净
- [ ] 部分arxiv_id年份异常（如2603.xxxxx是2026年3月的，需验证真实性）

## 待完善
- [ ] Semantic Scholar API补充检索（更多元数据、引用数）
- [ ] GitHub代码仓库搜索工具（验证code_available）
- [ ] 年份过滤强制检查
- [ ] 筛选/排除日志记录
- [ ] PDF下载工具（arxiv_get_paper扩展）
