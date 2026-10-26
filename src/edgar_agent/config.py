"""Runtime configuration, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # python-dotenv is optional at import time so pure modules stay testable
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


# Companies grouped by approximate market capitalization when they were picked, to test
# whether retrieval matters more for companies a model has seen less of. Each tier mixes
# fiscal calendars on purpose (e.g. Apple ends in Sept, Home Depot in early Feb).
# Tiers drift as stock prices move; they are labels for the eval, not live data.
TICKER_TIERS: dict[str, list[str]] = {
    "mega": ["AAPL", "MSFT", "NVDA", "WMT", "HD"],  # $200B+
    "large": ["NKE", "ADBE", "TGT", "GIS", "DE"],  # ~$10B-200B
    "mid": ["TTC", "OLLI", "COLM", "LANC", "SMPL"],  # ~$2B-10B
    "small": ["JOUT", "NATH", "LWAY", "WEYS", "RCKY"],  # ~$300M-2B
}
TIER_ORDER = list(TICKER_TIERS)
DEFAULT_TICKERS = [t for tickers in TICKER_TIERS.values() for t in tickers]


def tier_for(ticker: str) -> str:
    for tier, tickers in TICKER_TIERS.items():
        if ticker.upper() in tickers:
            return tier
    return "custom"


@dataclass(frozen=True)
class Settings:
    sec_user_agent: str
    data_dir: Path
    chroma_dir: Path
    model: str
    embedding_model: str
    top_k: int

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "sec_cache"


def get_settings() -> Settings:
    data_dir = Path(os.getenv("EDGAR_DATA_DIR", "data"))
    return Settings(
        # The SEC blocks requests without a descriptive User-Agent that includes contact info.
        sec_user_agent=os.getenv("SEC_USER_AGENT", ""),
        data_dir=data_dir,
        chroma_dir=Path(os.getenv("CHROMA_DIR", str(data_dir / "chroma"))),
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
        top_k=int(os.getenv("RETRIEVAL_TOP_K", "5")),
    )
