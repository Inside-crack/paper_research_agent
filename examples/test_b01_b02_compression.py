import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.agent_base import BaseAgent, _summarize_value
from paper_agent.common.models.execution_plan import ExecutionPlan, PlanStep
from paper_agent.common.models.base import TaskPhase


def _make_research_agent():
    agent = MagicMock(spec=BaseAgent)
    agent._compact_result = lambda tool_name, result: BaseAgent._compact_result(agent, tool_name, result)
    agent._build_results_prompt = lambda plan: BaseAgent._build_results_prompt(agent, plan)
    return agent


def _make_paper(arxiv_id, title="Test Paper", authors=None, abstract="A" * 400,
                published_date="2024-01-15", categories=None, code_available_hint=False,
                code_url_hint=None):
    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "authors": authors or ["Alice", "Bob", "Charlie"],
        "abstract": abstract,
        "published_date": published_date,
        "categories": categories or ["cs.AI", "cs.LG"],
        "code_available_hint": code_available_hint,
        "code_url_hint": code_url_hint,
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
    }


# ==================== B01: arxiv_search 字段精简 ====================

def test_b01_compact_arxiv_fields():
    """B01: arxiv_search压缩后字段精简：authors[:1], abstract[:150], 去掉published_date/categories"""
    agent = _make_research_agent()
    raw = {
        "query": "RAG agents",
        "total_found": 42,
        "results": [_make_paper("2401.00001", authors=["X", "Y", "Z"], abstract="B" * 400)],
    }
    compact = agent._compact_result("arxiv_search", raw)
    paper = compact["results"][0]

    assert set(paper.keys()) == {"arxiv_id", "title", "authors", "year", "code_available", "code_url", "abstract"}
    assert paper["authors"] == ["X"]
    assert len(paper["abstract"]) == 150
    assert paper["year"] == "2024"
    assert "published_date" not in paper
    assert "categories" not in paper
    assert "code_available_hint" not in paper
    assert paper["code_available"] is False
    assert compact["query"] == "RAG agents"
    assert compact["total_found"] == 42


def test_b01_compact_arxiv_code_available():
    """B01: code_available字段正确映射code_available_hint"""
    agent = _make_research_agent()
    raw = {"query": "q", "total_found": 1, "results": [
        _make_paper("2401.00002", code_available_hint=True, code_url_hint="https://github.com/x/repo")
    ]}
    compact = agent._compact_result("arxiv_search", raw)
    paper = compact["results"][0]
    assert paper["code_available"] is True
    assert paper["code_url"] == "https://github.com/x/repo"


# ==================== B01: results_prompt 跨步骤去重+30篇上限 ====================

def test_b01_results_prompt_cross_step_dedup():
    """B01: 跨arxiv_search步骤的论文按arxiv_id去重"""
    agent = _make_research_agent()
    p1 = _make_paper("2401.00001")
    p2 = _make_paper("2401.00002")
    p1_dup = _make_paper("2401.00001", title="Duplicate")

    plan = ExecutionPlan(phase=TaskPhase.PAPER_RETRIEVAL, objective="test", steps=[
        PlanStep(step_id="s1", description="search 1", tool_name="arxiv_search",
                 arguments={"query": "q1"}, executed=True, success=True,
                 result={"query": "q1", "total_found": 2, "results": [p1, p2]}),
        PlanStep(step_id="s2", description="search 2", tool_name="arxiv_search",
                 arguments={"query": "q2"}, executed=True, success=True,
                 result={"query": "q2", "total_found": 2, "results": [p1_dup, _make_paper("2401.00003")]}),
    ])
    prompt = agent._build_results_prompt(plan)
    assert "Deduplicated Paper List" in prompt
    assert "3 unique papers after deduplication" in prompt
    dedup_section = prompt.split("Deduplicated Paper List")[1].split("Other Step Results")[0] if "Other Step Results" in prompt else prompt.split("Deduplicated Paper List")[1]
    assert dedup_section.count("2401.00001") == 1


def test_b01_results_prompt_30_paper_limit():
    """B01: 论文超过30篇时只展示30篇，提示完整列表在artifact"""
    agent = _make_research_agent()
    papers = [_make_paper(f"2401.{i:05d}") for i in range(1, 46)]
    plan = ExecutionPlan(phase=TaskPhase.PAPER_RETRIEVAL, objective="test", steps=[
        PlanStep(step_id="s1", description="big search", tool_name="arxiv_search",
                 arguments={"query": "q"}, executed=True, success=True,
                 result={"query": "q", "total_found": 50, "results": papers},
                 artifact_id="paper_retrieval_s1_arxiv_search_result.json"),
    ])
    prompt = agent._build_results_prompt(plan)
    assert "45 unique papers after deduplication, showing top 30" in prompt
    assert "load_artifact for complete list" in prompt


def test_b01_results_prompt_other_steps_section():
    """B01: 非arxiv步骤在Other Step Results区域展示"""
    agent = _make_research_agent()
    plan = ExecutionPlan(phase=TaskPhase.PAPER_RETRIEVAL, objective="test", steps=[
        PlanStep(step_id="s1", description="search", tool_name="arxiv_search",
                 arguments={"query": "q"}, executed=True, success=True,
                 result={"query": "q", "total_found": 1, "results": [_make_paper("2401.00001")]}),
        PlanStep(step_id="s2", description="save candidates", tool_name="save_artifact",
                 arguments={"artifact_name": "candidates", "data": {}}, executed=True, success=True,
                 result={"artifact_name": "candidates", "path": "/tmp/candidates.json", "saved": True},
                 artifact_id="candidates.json"),
    ])
    prompt = agent._build_results_prompt(plan)
    assert "Other Step Results" in prompt
    assert "Step: s2 (save_artifact)" in prompt
    assert "Persisted artifact: `candidates.json`" in prompt


def test_b01_results_prompt_no_duplicate_dedup_instruction():
    """B01: 去重已在prompt层面完成，synthesize不再要求LLM自己去重"""
    agent = _make_research_agent()
    plan = ExecutionPlan(phase=TaskPhase.PAPER_RETRIEVAL, objective="test", steps=[
        PlanStep(step_id="s1", description="search", tool_name="arxiv_search",
                 arguments={"query": "q"}, executed=True, success=True,
                 result={"query": "q", "total_found": 0, "results": []}),
    ])
    prompt = agent._build_results_prompt(plan)
    assert "Deduplicate papers by arxiv_id" not in prompt


# ==================== B02: arxiv_get_paper 压缩 ====================

def test_b02_compact_arxiv_get_paper():
    """B02: arxiv_get_paper单篇论文压缩，abstract[:500], authors[:3]"""
    agent = _make_research_agent()
    raw = _make_paper("2401.00001", authors=["A", "B", "C", "D", "E"], abstract="X" * 1000,
                      categories=["cs.AI", "cs.CL", "cs.LG"])
    compact = agent._compact_result("arxiv_get_paper", raw)
    assert compact["arxiv_id"] == "2401.00001"
    assert len(compact["authors"]) == 3
    assert len(compact["abstract"]) == 500
    assert compact["pdf_url"] is not None
    assert "categories" in compact
    assert "published_date" not in compact


# ==================== B02: load_artifact 压缩 ====================

def test_b02_compact_load_artifact_dict():
    """B02: load_artifact加载dict时，返回keys列表+preview而非完整数据"""
    agent = _make_research_agent()
    big_dict = {f"key_{i}": f"value_{i}" * 50 for i in range(50)}
    raw = {"artifact_name": "big_data.json", "data": big_dict, "format": "json"}
    compact = agent._compact_result("load_artifact", raw)
    assert compact["loaded"] is True
    assert compact["type"] == "dict"
    assert compact["total_keys"] == 50
    assert len(compact["keys"]) == 20
    assert "preview" in compact
    for k in compact["preview"]:
        assert len(compact["preview"][k]) <= 103


def test_b02_compact_load_artifact_list():
    """B02: load_artifact加载list时，返回length+first_item"""
    agent = _make_research_agent()
    raw = {"artifact_name": "items.json", "data": [{"id": i, "name": f"item_{i}"} for i in range(100)]}
    compact = agent._compact_result("load_artifact", raw)
    assert compact["type"] == "list"
    assert compact["length"] == 100
    assert compact["first_item"] is not None


def test_b02_compact_load_artifact_scalar():
    """B02: load_artifact加载scalar时原样返回"""
    agent = _make_research_agent()
    raw = {"artifact_name": "count.json", "data": 42}
    compact = agent._compact_result("load_artifact", raw)
    assert compact["data"] == 42


# ==================== B02: 未知工具通用压缩 ====================

def test_b02_compact_unknown_tool_dict():
    """B02: 未知工具返回dict时，通用压缩为type/keys/size/preview"""
    agent = _make_research_agent()
    raw = {"status": "ok", "items": list(range(100)), "metadata": {"a": 1, "b": 2}, "raw_output": "X" * 500}
    compact = agent._compact_result("some_new_tool", raw)
    assert compact["_type"] == "tool_result"
    assert compact["tool"] == "some_new_tool"
    assert "size" in compact
    assert len(compact["keys"]) <= 10
    assert "preview" in compact


def test_b02_compact_unknown_tool_non_dict():
    """B02: 未知工具返回非dict时原样返回"""
    agent = _make_research_agent()
    assert agent._compact_result("some_tool", "hello") == "hello"
    assert agent._compact_result("some_tool", 42) == 42
    assert agent._compact_result("some_tool", None) is None


def test_b02_save_artifact_passthrough():
    """B02: save_artifact/download_file原样返回（结果小）"""
    agent = _make_research_agent()
    raw = {"artifact_name": "x.json", "path": "/tmp/x", "saved": True}
    assert agent._compact_result("save_artifact", raw) == raw
    dl = {"filename": "f.pdf", "path": "/tmp/f", "size_bytes": 1024}
    assert agent._compact_result("download_file", dl) == dl


# ==================== B02: 其他步骤大结果截断 ====================

def test_b02_other_step_large_result_truncated():
    """B02: 非arxiv步骤结果json>4000字符时截断，提示完整结果在artifact"""
    agent = _make_research_agent()

    big_data = {"sections": [{"title": f"section_{i}", "content": "X" * 200} for i in range(30)]}
    compact = agent._compact_result("paper_parser", big_data)
    text = json.dumps(compact, ensure_ascii=False, indent=2)
    print(f"  compact size for big_data: {len(text)}")

    plan = ExecutionPlan(phase=TaskPhase.PAPER_PARSING, objective="test", steps=[
        PlanStep(step_id="s1", description="parse result", tool_name="paper_parser",
                 arguments={}, executed=True, success=True,
                 result=big_data, artifact_id="paper_parsing_s1_result.json"),
    ])
    prompt = agent._build_results_prompt(plan)
    if len(text) > 4000:
        assert "truncated, full result in artifact" in prompt, f"Expected truncation msg, prompt size={len(prompt)}"
    else:
        assert "Result:" in prompt


def test_b02_failed_step_shows_error_and_artifact():
    """B02: 失败step显示错误信息+error artifact引用"""
    agent = _make_research_agent()
    plan = ExecutionPlan(phase=TaskPhase.PAPER_RETRIEVAL, objective="test", steps=[
        PlanStep(step_id="s1", description="broken search", tool_name="arxiv_search",
                 arguments={"query": "q"}, executed=True, success=False,
                 error="Connection timeout after 30s", artifact_id="paper_retrieval_s1_arxiv_search_error.json"),
    ])
    prompt = agent._build_results_prompt(plan)
    assert "FAILED: Connection timeout" in prompt
    assert "Error details persisted to: `paper_retrieval_s1_arxiv_search_error.json`" in prompt


# ==================== _summarize_value 辅助函数 ====================

def test_summarize_value_basic_types():
    assert _summarize_value(None) is None
    assert _summarize_value(True) is True
    assert _summarize_value(42) == 42
    assert _summarize_value(3.14) == 3.14


def test_summarize_value_string_truncation():
    assert _summarize_value("short") == "short"
    long_str = "x" * 200
    result = _summarize_value(long_str)
    assert len(result) <= 103
    assert result.endswith("...")


def test_summarize_value_list_truncation():
    assert _summarize_value([]) == []
    short_list = [1, 2]
    assert _summarize_value(short_list) == [1, 2]
    long_list = list(range(10))
    result = _summarize_value(long_list)
    assert len(result) == 2
    assert "10 items total" in result[1]


def test_summarize_value_dict_truncation():
    d = {f"k{i}": i for i in range(10)}
    result = _summarize_value(d)
    assert len(result) == 5


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL {t.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    sys.exit(0 if failed == 0 else 1)
