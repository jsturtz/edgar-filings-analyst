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


# Mix of fiscal calendars on purpose: Apple ends in Sept, Microsoft in June, NVIDIA and
# Walmart in late January, Home Depot in early February, Nike in May, Costco around Labor Day.
DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA", "WMT", "COST", "NKE", "HD", "ADBE", "JNJ", "XOM"]


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
