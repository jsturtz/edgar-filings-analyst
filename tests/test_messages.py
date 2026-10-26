from edgar_agent.messages import strip_thinking_blocks


def test_removes_thinking_keeps_text_and_tool_use():
    content = [
        {"type": "thinking", "thinking": "Need fiscal years first", "signature": "abc"},
        {"type": "redacted_thinking", "data": "xyz"},
        {"type": "text", "text": "Checking fiscal years."},
        {"type": "tool_use", "id": "t1", "name": "list_fiscal_years", "input": {"ticker": "HD"}},
    ]
    assert [b["type"] for b in strip_thinking_blocks(content)] == ["text", "tool_use"]


def test_string_content_unchanged():
    assert strip_thinking_blocks("plain answer") == "plain answer"
