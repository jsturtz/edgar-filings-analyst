"""The LangGraph workflow.

    START -> agent <-> tools            (ReAct loop: retrieve, look up, calculate)
               |
               v (no more tool calls)
            finalize                    (structured AgentAnswer with citations)
               |
               v
             verify --(ungrounded, 1 retry)--> agent
               |
               v
              END
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from .config import get_settings
from .grounding import check
from .schemas import AgentAnswer
from .tools import TOOLS

MAX_VERIFY_RETRIES = 1

SYSTEM_PROMPT = """You are a financial analyst answering questions about US public companies \
strictly from their SEC 10-K filings, using the tools provided.

Rules:
- Never answer a figure from memory. Use get_financial_metric for standard figures and \
search_filings for explanations, risks and anything else.
- Fiscal years are the company's own labels. If a question names a year and the company's \
fiscal year doesn't match the calendar, call list_fiscal_years first.
- Use calculate for every derived number (margins, growth, ratios). Report percentages as \
percent (12.5 means 12.5%).
- If the filings don't contain the answer, say so plainly rather than guessing."""

FINALIZE_PROMPT = """Now give the final answer as structured output, based only on the tool \
results above. `value` must be a number that appeared in a tool result (or a calculate \
output), in base units (whole dollars, not millions). Cite every source you used."""


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    answer: AgentAnswer | None
    grounded: bool | None
    grounding_reason: str | None
    retries: int
    retry: bool


def build_graph(model: str | None = None):
    settings = get_settings()
    # Newer Claude models reject non-default temperature, so we leave sampling at the default.
    llm = ChatAnthropic(model=model or settings.model, max_tokens=2048)
    llm_with_tools = llm.bind_tools(TOOLS)
    structured = llm.with_structured_output(AgentAnswer, method="json_schema")

    def agent(state: State) -> dict:
        response = llm_with_tools.invoke([SystemMessage(SYSTEM_PROMPT), *state["messages"]])
        return {"messages": [response]}

    def finalize(state: State) -> dict:
        answer = structured.invoke(
            [SystemMessage(SYSTEM_PROMPT), *state["messages"], HumanMessage(FINALIZE_PROMPT)]
        )
        return {"answer": answer}

    def verify(state: State) -> dict:
        answer = state["answer"]
        evidence = [m.content for m in state["messages"] if isinstance(m, ToolMessage)]
        evidence = [e if isinstance(e, str) else str(e) for e in evidence]
        result = check(answer.value, answer.unit, evidence)
        update: dict = {"grounded": result.grounded, "grounding_reason": result.reason, "retry": False}
        if not result.grounded and state.get("retries", 0) < MAX_VERIFY_RETRIES:
            update["retry"] = True
            update["retries"] = state.get("retries", 0) + 1
            update["messages"] = [
                HumanMessage(
                    f"Verification failed: {result.reason}. Re-check with the tools and "
                    "answer again using only retrieved or calculated numbers."
                )
            ]
        return update

    def after_verify(state: State) -> str:
        return "agent" if state.get("retry") else END

    graph = StateGraph(State)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_node("finalize", finalize)
    graph.add_node("verify", verify)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: "finalize"})
    graph.add_edge("tools", "agent")
    graph.add_edge("finalize", "verify")
    graph.add_conditional_edges("verify", after_verify, {"agent": "agent", END: END})
    return graph.compile()


def run(question: str, graph=None) -> State:
    graph = graph or build_graph()
    return graph.invoke(
        {"messages": [HumanMessage(question)], "answer": None, "grounded": None,
         "grounding_reason": None, "retries": 0, "retry": False},
        config={"recursion_limit": 30},
    )
