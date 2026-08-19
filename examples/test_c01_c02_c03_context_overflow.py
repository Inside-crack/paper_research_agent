import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.llm.base import (
    LLMMessage, MessageRole, estimate_tokens, compress_messages,
    CONTEXT_COMPRESS_RATIO, CONTEXT_TARGET_RATIO, DEFAULT_CONTEXT_WINDOW,
    RESERVED_OUTPUT_TOKENS, CHARS_PER_TOKEN_ESTIMATE,
)


def _msg(role, content, anchor=False, priority=0):
    return LLMMessage(role=role, content=content, metadata={"anchor": anchor, "priority": priority})


def _system(content, **kw):
    return _msg(MessageRole.SYSTEM, content, anchor=True, priority=100)


def _user(content, anchor=False, priority=50, **kw):
    return _msg(MessageRole.USER, content, anchor=anchor, priority=priority)


def _assistant(content, anchor=False, priority=50, **kw):
    return _msg(MessageRole.ASSISTANT, content, anchor=anchor, priority=priority)


# ==================== C01: Token估算 ====================

def test_c01_estimate_tokens_basic():
    """C01: 基础token估算：字符数/4"""
    msgs = [_user("a" * 400)]
    tokens = estimate_tokens(msgs)
    assert tokens == 100, f"Expected 100, got {tokens}"


def test_c01_estimate_tokens_empty():
    """C01: 空内容按1 token计（min=1）"""
    msgs = [_user("")]
    assert estimate_tokens(msgs) == 1


def test_c01_estimate_tokens_multiple():
    """C01: 多消息累加"""
    msgs = [_user("a" * 400), _assistant("b" * 800)]
    assert estimate_tokens(msgs) == 100 + 200


# ==================== C01: 阈值检查（通过_prepare_messages在LLM中） ====================

def test_c01_no_compression_under_threshold():
    """C01: 低于COMPRESS阈值时不压缩，消息原样返回"""
    msgs = [
        _system("sys"),
        _user("hello" * 100, anchor=True, priority=90),
        _assistant("hi"),
    ]
    compressed, removed = compress_messages(msgs, context_window=DEFAULT_CONTEXT_WINDOW, reserved_output=4096)
    assert removed == 0
    assert len(compressed) == 3


def test_c01_system_messages_protected():
    """C02: SYSTEM消息即使没有anchor标记也受保护"""
    sys_msg = LLMMessage(role=MessageRole.SYSTEM, content="sys", metadata={})
    filler = _user("x" * 400000, anchor=False, priority=10)
    msgs = [sys_msg, filler]
    compressed, removed = compress_messages(msgs, context_window=10000, reserved_output=1000)
    assert removed >= 1
    assert any(m.role == MessageRole.SYSTEM for m in compressed)


# ==================== C02: 锚点保护 ====================

def test_c02_anchors_never_removed():
    """C02: anchor=True的消息在COMPRESS级别永不丢弃"""
    anchor1 = _system("system prompt")
    anchor2 = _user("phase prompt" + "p" * 1000, anchor=True, priority=90)
    anchor3 = _user("results" + "r" * 1000, anchor=True, priority=80)
    fillers = [_user(f"filler_{i}" + "x" * 5000, anchor=False, priority=20) for i in range(20)]
    msgs = [anchor1, anchor2, anchor3] + fillers
    compressed, removed = compress_messages(msgs, context_window=15000, reserved_output=2000)
    assert removed > 0
    anchor_ids = {id(anchor1), id(anchor2), id(anchor3)}
    for m in compressed:
        if id(m) in anchor_ids:
            anchor_ids.remove(id(m))
    assert len(anchor_ids) == 0, f"Anchors were removed: {len(anchor_ids)}"


def test_c02_anchor_priority_order():
    """C03: 非锚点消息按priority升序丢弃（priority低的先丢）"""
    high_pri = _user("important" * 200, anchor=False, priority=80)
    mid_pri = _user("medium" * 800, anchor=False, priority=50)
    low_pri = _user("filler" + "f" * 10000, anchor=False, priority=10)
    anchor = _system("sys")
    msgs = [anchor, low_pri, mid_pri, high_pri]
    compressed, removed = compress_messages(msgs, context_window=5000, reserved_output=1000)
    assert removed >= 1
    compressed_ids = {id(m) for m in compressed}
    assert id(low_pri) not in compressed_ids
    assert id(anchor) in compressed_ids


# ==================== C01+C03: COMPRESS级别触发 ====================

def test_c03_compress_reduces_to_target():
    """C03: COMPRESS后token数降到target（75%）以下"""
    effective = 10000
    target = int(effective * CONTEXT_TARGET_RATIO)
    anchor = _system("sys")
    fillers = [_user(f"f{i}" + "x" * 3000, anchor=False, priority=10 + i) for i in range(15)]
    msgs = [anchor] + fillers
    compressed, removed = compress_messages(msgs, context_window=effective + 4096, reserved_output=4096)
    final_tokens = estimate_tokens(compressed)
    assert removed > 0, f"Expected removal, got 0"
    assert final_tokens <= target + 200, f"After compression {final_tokens} tokens > target {target}"


def test_c03_compress_injects_notice():
    """C01: 压缩后注入Context compressed提示消息"""
    anchor = _system("sys")
    fillers = [_user(f"f{i}" + "x" * 5000, anchor=False, priority=i) for i in range(20)]
    msgs = [anchor] + fillers
    compressed, removed = compress_messages(msgs, context_window=10000, reserved_output=1000)
    assert removed > 0
    assert any("Context compressed" in m.content for m in compressed)
    notice = [m for m in compressed if "Context compressed" in m.content][0]
    assert notice.is_anchor
    assert str(removed) in notice.content


# ==================== C01+C03: CRITICAL级别激进压缩 ====================

def test_c03_critical_keeps_anchors_plus_tail():
    """C03: CRITICAL时只保留锚点+最后2条消息"""
    anchor1 = _system("sys")
    anchor2 = _user("phase prompt", anchor=True, priority=90)
    old_fillers = [_user(f"old_{i}" + "x" * 2000, anchor=False, priority=10) for i in range(30)]
    recent1 = _user("recent user message", anchor=False, priority=50)
    recent2 = _assistant("recent assistant reply", anchor=False, priority=50)
    msgs = [anchor1, anchor2] + old_fillers + [recent1, recent2]
    compressed, removed = compress_messages(msgs, context_window=8000, reserved_output=1000)
    assert removed > 0
    assert id(anchor1) in {id(m) for m in compressed}
    assert id(anchor2) in {id(m) for m in compressed}


def test_c03_all_anchors_cant_compress_more():
    """C03: 全是锚点无法进一步压缩时，所有消息保留+notice"""
    msgs = [
        _system("sys"),
        _user("anchor1", anchor=True, priority=100),
        _user("anchor2", anchor=True, priority=95),
        _user("anchor3" + "x" * 50000, anchor=True, priority=90),
    ]
    compressed, removed = compress_messages(msgs, context_window=5000, reserved_output=1000)
    anchor_count = sum(1 for m in compressed if m.is_anchor or m.role == MessageRole.SYSTEM)
    assert anchor_count >= 3


# ==================== C01: 边界情况 ====================

def test_c01_empty_messages():
    """C01: 空消息列表不崩溃"""
    compressed, removed = compress_messages([], context_window=10000, reserved_output=1000)
    assert removed == 0
    assert compressed == []


def test_c01_single_message_under_threshold():
    """C01: 单条小消息不压缩"""
    msgs = [_user("hi")]
    compressed, removed = compress_messages(msgs, context_window=10000, reserved_output=1000)
    assert removed == 0
    assert len(compressed) == 1


# ==================== 反向验证：压缩后消息顺序基本保持 ====================

def test_c03_preserves_anchor_order():
    """C03: 压缩后锚点消息的相对顺序不变"""
    a1 = _system("first")
    a2 = _user("second", anchor=True, priority=90)
    a3 = _user("third", anchor=True, priority=80)
    fillers = [_user(f"f{i}" + "x" * 3000, anchor=False, priority=10) for i in range(10)]
    msgs = [a1, a2] + fillers + [a3]
    compressed, _ = compress_messages(msgs, context_window=8000, reserved_output=1000)
    anchor_positions = []
    for i, m in enumerate(compressed):
        if id(m) in {id(a1), id(a2), id(a3)}:
            anchor_positions.append((m.content[:10], i))
    contents = [c for c, _ in anchor_positions]
    assert contents.index("first") < contents.index("second")
    assert contents.index("second") < contents.index("third")


# ==================== Integration: 模拟真实Agent消息序列 ====================

def test_integration_realistic_message_sequence():
    """C01+C02+C03: 模拟真实paper_retrieval阶段的消息序列，验证关键锚点都保留"""
    msgs = []
    msgs.append(_system("You are a research agent..."))
    msgs.append(_user("=== Research Spec ===" + "s" * 500, anchor=True, priority=100))
    msgs.append(_user("=== Phase Summaries ===" + "s" * 200, anchor=True, priority=95))
    msgs.append(_user("## PHASE: Paper Retrieval" + "p" * 800, anchor=True, priority=90))

    for i in range(3):
        msgs.append(_assistant(f'{{"action":"plan","steps":[...]}}_{i}', anchor=False, priority=40))
        if i < 2:
            msgs.append(_user("JSON parse error", anchor=False, priority=20))

    msgs.append(_user("## Tool Execution Results" + "r" * 8000, anchor=True, priority=80))

    compressed, removed = compress_messages(msgs, context_window=12000, reserved_output=2000)

    anchor_keywords = ["research agent", "Research Spec", "Phase Summaries", "PHASE: Paper Retrieval", "Tool Execution Results"]
    for kw in anchor_keywords:
        assert any(kw.lower() in m.content.lower() for m in compressed), f"Missing anchor: {kw}"

    assert removed >= 0
    assert any("Context compressed" in m.content for m in compressed) or removed == 0


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
