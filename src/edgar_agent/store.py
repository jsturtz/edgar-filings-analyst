"""Vector store over 10-K sections (Chroma + a local open-source embedding model)."""

from __future__ import annotations

from functools import lru_cache

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from .config import get_settings

COLLECTION = "edgar_10k"


@lru_cache(maxsize=1)
def get_store() -> Chroma:
    settings = get_settings()
    embeddings = HuggingFaceEmbeddings(
        model_name=settings.embedding_model,
        encode_kwargs={"normalize_embeddings": True},
    )
    return Chroma(
        collection_name=COLLECTION,
        embedding_function=embeddings,
        persist_directory=str(settings.chroma_dir),
        collection_metadata={"hnsw:space": "cosine"},
    )


def build_filter(ticker: str | None, fiscal_year: int | None, item: str | None) -> dict | None:
    clauses = []
    if ticker:
        clauses.append({"ticker": ticker.upper()})
    if fiscal_year:
        clauses.append({"fiscal_year": int(fiscal_year)})
    if item:
        clauses.append({"item": item.upper().replace("ITEM", "").strip()})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}
