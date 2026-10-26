"""Entry point for LangGraph Server / LangSmith Deployment (see langgraph.json).

    uv run langgraph dev     # local API + LangGraph Studio in the browser

Send input as {"messages": [{"role": "user", "content": "<question>"}]}.
"""

from edgar_agent.graph import build_graph

graph = build_graph()
