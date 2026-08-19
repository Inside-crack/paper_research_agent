# A01 阶段间上下文隔离 - 遭遇卡点

## 当前卡点
无 ✅ 实现完成，所有测试通过。

---

## 实现过程中遇到并已解决的卡点（详见resolutions.md）

### ~~1. EvaluationIssue Pydantic模型不能用.get()访问~~ ✅ 已解决
- **影响**：_record_phase_failure中用`i.get("severity")`访问EvaluationIssue属性导致AttributeError
- **解决**：改为属性访问`issue.severity.value`，兼容枚举值提取
- **涉及文件**：orchestrator.py _record_phase_failure()

### ~~2. _build_phase_summary_card中issues severity访问类型不兼容~~ ✅ 已解决
- **影响**：_build_phase_summary_card中检查high/critical issues时用`.get()`访问，但issues可能是Pydantic对象也可能是dict
- **解决**：新增_get_severity()辅助函数，兼容Pydantic模型和dict两种类型
- **涉及文件**：orchestrator.py _build_phase_summary_card()

### ~~3. setup_logging()不接受level参数~~ ✅ 已解决（测试脚本问题）
- **影响**：测试脚本传了level="WARNING"导致TypeError
- **解决**：移除测试脚本中的level参数，用默认配置
- **涉及文件**：test_phase_isolation.py

---

## 已知风险点（实现前预判，均已验证无问题）

1. ~~is_revision判断逻辑需精确~~ ✅ 代码已加一致性检查，不一致直接抛RuntimeError
2. ~~懒初始化移除可能影响其他调用点~~ ✅ 保留initialize()方法，只移除懒初始化自动调用；严格检查下未初始化直接抛错
3. ~~摘要卡key_info字段各阶段结构不同~~ ✅ key_info设计为dict透传，格式化为文本时简单key=value输出，兼容所有阶段
