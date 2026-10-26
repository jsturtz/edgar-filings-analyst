"""Ask the agent one question from the command line.

    uv run python -m edgar_agent.ask "What was Apple's gross margin in fiscal 2024?"
"""

from __future__ import annotations

import sys

from langchain_core.messages import AIMessage

from .graph import run


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    state = run(" ".join(sys.argv[1:]))

    print("\nTool calls:")
    for msg in state["messages"]:
        if isinstance(msg, AIMessage):
            for call in msg.tool_calls:
                print(f"  - {call['name']}({call['args']})")

    answer = state["answer"]
    print(f"\nAnswer: {answer.answer}")
    if answer.value is not None:
        print(f"Value:  {answer.value:,.4g} {answer.unit or ''}")
    print(f"Grounded: {state['grounded']} ({state['grounding_reason']})")
    print("Citations:")
    for c in answer.citations:
        where = f"{c.ticker or ''} FY{c.fiscal_year}" if c.fiscal_year else (c.ticker or "")
        print(f"  - [{c.source}] {where} {c.detail} {c.url or ''}".rstrip())


if __name__ == "__main__":
    main()
