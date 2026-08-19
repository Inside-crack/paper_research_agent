# 已解决问题及解决方案（2026-08-14）

## 1. Python 3.9 `X | None` 语法不兼容
- **现象**：启动时报SyntaxError，Python 3.9不支持PEP 604 union语法
- **根因**：使用了Python 3.10+的`str | None`类型注解
- **解决方案**：所有受影响文件头部添加 `from __future__ import annotations`
- **涉及文件**：所有使用`X | None`语法的.py文件
- **验证**：✅ 所有模块可正常import

---

## 2. Prompt模板 str.format() 与JSON示例大括号冲突
- **现象**：format()报错KeyError，因为JSON示例中的{...}被当作占位符
- **根因**：prompt模板中包含大量JSON示例，与str.format()的{}占位符语法冲突
- **解决方案**：弃用str.format()，改用简单的 `str.replace("{placeholder}", value)` 逐个替换
- **涉及文件**：agent_base.py _load_phase_prompt()
- **验证**：✅ 所有prompt正常加载替换

---

## 3. DeepSeek无原生function calling，TOOL角色消息报错
- **现象**：添加TOOL角色消息后API返回400错误
- **根因**：我们使用的是非function calling模式，DeepSeek不识别TOOL角色
- **解决方案**：record_step_result()改为no-op，所有工具执行结果通过_build_results_prompt()聚合成User消息传入下一轮
- **涉及文件**：agent_base.py
- **验证**：✅ 工具结果正确传入LLM，LLM能基于结果继续规划

---

## 4. 工具参数名 `name` 与 artifact "name" 参数冲突
- **现象**：调用save_artifact时参数被错误消费，提示缺少参数
- **根因**：registry.execute(tool_name, **kwargs)中第一个参数名是name，而artifact参数也有name字段，kwargs解包时冲突
- **解决方案**：
  1. 第一个参数改名为 `tool_name`
  2. kwargs.pop("name", None)兼容LLM可能传的"name"参数
- **涉及文件**：tools/registry.py execute()
- **验证**：✅ save_artifact调用正常

---

## 5. save_artifact参数名不匹配（LLM传content而非data）
- **现象**：工具提示"Missing required parameter: data"，但LLM传的是content
- **根因**：LLM输出不稳定，有时传data、有时传content、有时传artifact_name、有时传name
- **解决方案**：SaveArtifactTool参数处理使用**kwargs，通过kwargs.get()兼容多种参数名：
  - data/content 都接受作为内容
  - artifact_name/name/artifact_id 都接受作为名称
- **涉及文件**：filesystem/file_tools.py
- **验证**：✅ 不同参数名的调用都能正常保存

---

## 6. task_id未自动传递给工具
- **现象**：工具不知道当前属于哪个task，无法保存到对应目录
- **根因**：_execute_plan()执行工具时未注入上下文
- **解决方案**：执行前显式添加 `args["task_id"] = task_state.id`
- **涉及文件**：orchestrator.py _execute_plan()
- **验证**：✅ 产物正确保存到data/artifacts/<task_id>/

---

## 7. Evaluation Agent输入过大导致400/截断
- **现象**：paper_retrieval阶段评估时API返回400或JSON截断
- **根因**：6次搜索×20篇论文结果太大，超过模型上下文窗口
- **解决方案**：
  1. Research Agent端：_compact_result()截断arXiv结果，只保留关键字段，abstract截到300字
  2. Evaluation Agent端：_trim_evidence()/_trim_output()截断输入
  3. 增加max_tokens到8192
- **涉及文件**：agent_base.py, evaluation_agent/agent.py
- **验证**：✅ 评估请求正常发送

---

## 8. LLM返回list而非dict导致AttributeError
- **现象**：'list' object has no attribute 'get'
- **根因**：LLM有时返回JSON数组而非对象
- **解决方案**：_parse_llm_to_json()检测结果类型：
  - 如果是list且第一个元素是dict，取第一个元素
  - 否则包装为{"items": data, "verdict": "REVISE"}
- **涉及文件**：agent_base.py _parse_llm_to_json()
- **验证**：✅ list结果不再崩溃

---

## 9. JSON截断导致解析失败（Unterminated string）
- **现象**：json.JSONDecodeError: Unterminated string
- **根因**：max_tokens不足或输出过长导致JSON被截断
- **解决方案**：
  1. 添加_try_fix_json()自动修复：补全缺失的}和]括号
  2. 重试prompt更明确要求"valid JSON only, single object"
  3. 增加max_tokens配置
- **涉及文件**：agent_base.py _try_fix_json()
- **验证**：✅ 轻度截断JSON可自动修复解析

---

## 10. arXiv搜索结果跨查询重复
- **现象**：同一篇论文出现在多个搜索结果中，LLM看到大量重复
- **根因**：多组关键词搜索必然有结果重叠
- **解决方案**：Orchestrator端_deduplicate_search_results()在工具执行完成后、传给LLM前做预去重：
  - 按arxiv_id基础版本（去v后缀）去重
  - 同时进一步压缩每个paper字段（abstract截到200字）
- **涉及文件**：orchestrator.py _deduplicate_search_results()
- **验证**：✅ 4×15篇去重后约40-50篇唯一论文
