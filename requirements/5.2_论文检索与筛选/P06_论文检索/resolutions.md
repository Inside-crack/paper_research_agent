# 论文检索 - 解决方案

**需求ID**：P06  
**需求名称**：论文检索  
**所属模块**：论文检索与筛选  

---

## 解决方案记录

| 序号 | 对应卡点 | 解决日期 | 解决人 | 方案简述 |
|------|----------|----------|--------|----------|
| 1 | 非正 `max_results` 未校验 | 2026-08-19 | | 在 `src/paper_agent/tools/retrieval/arxiv_tool.py` 中于构造 arXiv 客户端前增加输入校验；由 `examples/test_paper_retrieval_validation.py` 验证精确错误、正数检索路径及缺少 query 的既有行为 |

---

## 方案详情

### 1. 非正 `max_results` 输入校验

实现文件：`src/paper_agent/tools/retrieval/arxiv_tool.py`。

测试文件：`examples/test_paper_retrieval_validation.py`，验证 `0` 和 `-1`
返回精确错误 `max_results must be greater than 0`，且不会构造 arXiv 客户端；
正数 `max_results` 继续进入检索路径，缺少 `query` 时仍返回
`Missing required parameter: query`。

验证命令：
`PYTHONPATH=src python3 -m pytest -q examples/test_paper_retrieval_validation.py`
通过，3 个测试全部通过。
