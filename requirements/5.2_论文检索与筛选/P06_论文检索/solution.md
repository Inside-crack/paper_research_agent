# 论文检索 - 实现方案

**需求ID**：P06  
**需求名称**：论文检索  
**所属模块**：论文检索与筛选  
**创建日期**：2026-08-14  
**最后更新**：2026-08-19

---

## 需求描述

### Research Agent 职责
优先检索 arXiv，必要时补充会议官网、DOI、作者主页和公开版本。

### Evaluation Agent 职责
检查来源可靠性、结果重复、元数据错误和核心论文遗漏。

## 方案设计

### 整体思路

（阐述实现该需求的整体思路和技术选型）

### 架构设计

（描述相关的架构设计、模块划分、数据流等）

### 接口设计

（如涉及API接口，描述接口定义、输入输出等）

### 2026-08-19 实现补充

`ArxivSearchTool._execute` 在构造 arXiv 客户端前校验
`max_results`：当 `max_results <= 0` 时返回精确错误
`max_results must be greater than 0`。正数 `max_results` 继续进入原有检索流程，
缺少 `query` 时仍返回 `Missing required parameter: query`。

实现文件：`src/paper_agent/tools/retrieval/arxiv_tool.py`。
验证文件：`examples/test_paper_retrieval_validation.py`。
验证命令
`PYTHONPATH=src python3 -m pytest -q examples/test_paper_retrieval_validation.py`
通过，3 个测试全部通过。

### 数据结构

（描述关键数据结构、数据库设计等）

## 实现步骤

1. 
2. 
3. 

## 依赖项

- [ ] 依赖项1
- [ ] 依赖项2

## 风险评估

| 风险点 | 影响等级 | 应对措施 |
|--------|----------|----------|
| | | |
