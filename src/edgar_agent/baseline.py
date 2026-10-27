"""No-retrieval baseline: the same model and output schema, answering from memory.

This is the control in every eval: the agent has to beat it to justify its existence.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from .llm import chat_model, structured_output_method
from .schemas import AgentAnswer

BASELINE_PROMPT = """You are a financial analyst. Answer the question about a US public \
company's SEC 10-K filings from your own knowledge. Give your best single number when one \
is asked for, in base units (whole dollars, not millions; percentages as percent). \
Cite source as model_knowledge."""


def build_baseline(model: str | None = None):
    llm = chat_model(model, max_tokens=1024)
    structured = llm.with_structured_output(AgentAnswer, method=structured_output_method())

    def answer(question: str) -> AgentAnswer:
        return structured.invoke([SystemMessage(BASELINE_PROMPT), HumanMessage(question)])

    return answer
