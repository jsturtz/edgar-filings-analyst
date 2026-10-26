"""Structured output contract for every answer (agent and baseline alike)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    source: Literal["xbrl", "filing_text", "calculation", "model_knowledge"]
    ticker: str | None = None
    fiscal_year: int | None = None
    detail: str = Field(
        description="XBRL concept (e.g. us-gaap:NetIncomeLoss), 10-K item (e.g. 'Item 7'), "
        "or the arithmetic expression used."
    )
    url: str | None = None


class AgentAnswer(BaseModel):
    answer: str = Field(description="One or two sentence answer for a human reader.")
    value: float | None = Field(
        default=None,
        description="The single headline number, in base units: whole dollars (not millions), "
        "percentages as percent (12.5 means 12.5%), EPS in dollars per share. "
        "Null when the question has no numeric answer.",
    )
    unit: Literal["USD", "percent", "USD/share", "month", "text"] | None = None
    period_end: str | None = Field(
        default=None, description="Fiscal period end date (YYYY-MM-DD) the answer refers to, if known."
    )
    citations: list[Citation] = Field(default_factory=list)
