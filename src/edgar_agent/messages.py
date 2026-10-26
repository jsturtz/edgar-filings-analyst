"""Helpers for passing conversation history between differently configured model calls."""

from __future__ import annotations

THINKING_TYPES = {"thinking", "redacted_thinking"}


def strip_thinking_blocks(content):
    """Remove extended-thinking blocks from an assistant message's content.

    Claude's thinking blocks are signed and bound to the request they came from,
    including its tool list. Replaying them into a call with a different tool setup
    (our finalize step) is rejected by the API, so we drop them there. The reasoning
    they carried is already reflected in the tool calls and results that remain.
    """
    if not isinstance(content, list):
        return content
    return [b for b in content if not (isinstance(b, dict) and b.get("type") in THINKING_TYPES)]
