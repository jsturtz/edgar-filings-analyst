"""Minimal, polite client for SEC EDGAR.

- Sends the required descriptive User-Agent header.
- Stays under the SEC's 10 requests/second fair-access limit.
- Caches every response on disk so re-runs (and evals) never re-download.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import requests

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{document}"


@dataclass(frozen=True)
class Filing:
    cik: int
    form: str
    accession: str
    filing_date: str
    report_date: str  # period end date, YYYY-MM-DD
    primary_document: str

    @property
    def url(self) -> str:
        return ARCHIVE_URL.format(
            cik=self.cik,
            accession_nodash=self.accession.replace("-", ""),
            document=self.primary_document,
        )


class SECClient:
    def __init__(self, user_agent: str, cache_dir: Path, min_interval: float = 0.15):
        if not user_agent or "@" not in user_agent:
            raise ValueError(
                "SEC_USER_AGENT must identify you with a contact email, "
                "e.g. 'Jane Doe jane@example.com'"
            )
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self._last_request = 0.0
        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        )

    # -- transport ---------------------------------------------------------
    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()[:24]
        return self.cache_dir / digest

    def get_bytes(self, url: str) -> bytes:
        path = self._cache_path(url)
        if path.exists():
            return path.read_bytes()
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        resp = self._session.get(url, timeout=60)
        self._last_request = time.monotonic()
        resp.raise_for_status()
        path.write_bytes(resp.content)
        return resp.content

    def get_json(self, url: str) -> dict:
        return json.loads(self.get_bytes(url))

    # -- lookups -----------------------------------------------------------
    def ticker_map(self) -> dict[str, dict]:
        raw = self.get_json(TICKERS_URL)
        return {row["ticker"].upper(): row for row in raw.values()}

    def cik_for(self, ticker: str) -> tuple[int, str]:
        row = self.ticker_map().get(ticker.upper())
        if row is None:
            raise KeyError(f"Unknown ticker: {ticker}")
        return int(row["cik_str"]), row["title"]

    def submissions(self, cik: int) -> dict:
        return self.get_json(SUBMISSIONS_URL.format(cik=cik))

    def annual_reports(self, cik: int, limit: int = 3) -> list[Filing]:
        """Most recent original 10-K filings (amendments excluded), newest first."""
        recent = self.submissions(cik)["filings"]["recent"]
        out: list[Filing] = []
        for i, form in enumerate(recent["form"]):
            if form != "10-K":
                continue
            out.append(
                Filing(
                    cik=cik,
                    form=form,
                    accession=recent["accessionNumber"][i],
                    filing_date=recent["filingDate"][i],
                    report_date=recent["reportDate"][i],
                    primary_document=recent["primaryDocument"][i],
                )
            )
            if len(out) >= limit:
                break
        return out

    def filing_html(self, filing: Filing) -> str:
        return self.get_bytes(filing.url).decode("utf-8", errors="replace")

    def companyfacts(self, cik: int) -> dict:
        return self.get_json(COMPANYFACTS_URL.format(cik=cik))
