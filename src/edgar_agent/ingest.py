"""Download recent 10-Ks + XBRL facts for a set of tickers and index them.

    uv run python -m edgar_agent.ingest --tickers AAPL MSFT NVDA --years 3
"""

from __future__ import annotations

import argparse
import hashlib
import json

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from . import xbrl
from .config import DEFAULT_TICKERS, get_settings
from .parse_10k import parse_10k
from .sec_client import SECClient
from .store import get_store

SKIP_ITEMS = {"5", "6", "9", "9B", "9C", "10", "11", "12", "13", "14", "15", "16"}


def ingest(tickers: list[str], years: int) -> None:
    settings = get_settings()
    client = SECClient(settings.sec_user_agent, settings.cache_dir)
    splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)
    store = get_store()
    manifest: dict[str, list[dict]] = {}

    for ticker in tickers:
        cik, company = client.cik_for(ticker)
        facts = client.companyfacts(cik)  # cached on disk for the agent's XBRL tool
        manifest[ticker] = []
        for filing in client.annual_reports(cik, limit=years):
            fy = xbrl.fiscal_year_for_period_end(facts, filing.report_date)
            if fy is None:
                fy = int(filing.report_date[:4])
            sections = parse_10k(client.filing_html(filing))
            docs, ids = [], []
            for section in sections:
                if section.item in SKIP_ITEMS:
                    continue
                for i, chunk in enumerate(splitter.split_text(section.text)):
                    docs.append(
                        Document(
                            page_content=chunk,
                            metadata={
                                "ticker": ticker,
                                "company": company,
                                "cik": cik,
                                "fiscal_year": fy,
                                "period_end": filing.report_date,
                                "item": section.item,
                                "section": section.title,
                                "accession": filing.accession,
                                "url": filing.url,
                            },
                        )
                    )
                    key = f"{filing.accession}:{section.item}:{i}"
                    ids.append(hashlib.sha1(key.encode()).hexdigest())
            if docs:
                store.add_documents(docs, ids=ids)  # stable ids -> re-runs upsert, no duplicates
            manifest[ticker].append(
                {"fiscal_year": fy, "period_end": filing.report_date, "accession": filing.accession,
                 "url": filing.url, "sections": [s.item for s in sections], "chunks": len(docs)}
            )
            print(f"{ticker} FY{fy} ({filing.report_date}): {len(sections)} sections, {len(docs)} chunks")

    (settings.data_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--years", type=int, default=3)
    args = parser.parse_args()
    ingest([t.upper() for t in args.tickers], args.years)


if __name__ == "__main__":
    main()
