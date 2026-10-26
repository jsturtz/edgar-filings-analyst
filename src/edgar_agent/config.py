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


@dataclass(frozen=True)
class Settings:
    sec_user_agent: str
    data_dir: Path

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "sec_cache"


def get_settings() -> Settings:
    data_dir = Path(os.getenv("EDGAR_DATA_DIR", "data"))
    return Settings(
        # The SEC blocks requests without a descriptive User-Agent that includes contact info.
        sec_user_agent=os.getenv("SEC_USER_AGENT", ""),
        data_dir=data_dir,
    )
