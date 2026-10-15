"""Async PostgreSQL/pgvector database lifecycle and seed management."""

import json
import csv
import logging
import re
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.models.patent import Base, Patent

logger = logging.getLogger(__name__)
csv.field_size_limit(sys.maxsize)
_CLAIM_START = re.compile(r"(?m)^\s*\d+\s*\.\s*")

settings: Settings = get_settings()
engine: AsyncEngine = create_async_engine(
    settings.async_database_url,
    pool_pre_ping=True,
    pool_recycle=1800,
)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_database() -> None:
    """Create pgvector structures and seed patents when the database is empty."""
    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        existing_patent = await session.scalar(select(Patent.id).limit(1))
        if existing_patent is None:
            await seed_patents(session)


async def seed_patents(session: AsyncSession) -> int:
    """Embed and insert configured JSON or CSV patent data into PostgreSQL."""
    from embeddings import EmbeddingEngine

    seed_path = Path(settings.seed_data_path)
    if not seed_path.exists():
        raise FileNotFoundError(f"Seed data file does not exist: {seed_path}")

    if seed_path.suffix.lower() == ".csv":
        with seed_path.open(newline="", encoding="utf-8-sig") as seed_file:
            reader = csv.DictReader(seed_file)
            required = {"publication_number", "title", "abstract", "claims"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise ValueError(
                    f"Patent CSV is missing required columns: {', '.join(sorted(missing))}"
                )
            patents = [
                {
                    "patent_id": (row.get("publication_number") or "").strip(),
                    "title": (row.get("title") or "").strip(),
                    "abstract": (row.get("abstract") or "").strip(),
                    "claims": _parse_claim_text(row.get("claims") or ""),
                    "category": "Imported Claims",
                }
                for row in reader
                if (row.get("publication_number") or "").strip()
                and (row.get("title") or "").strip()
                and (row.get("abstract") or "").strip()
            ]
    else:
        with seed_path.open("r", encoding="utf-8") as seed_file:
            payload: dict[str, Any] = json.load(seed_file)
        patents = payload.get("patents")
        if not isinstance(patents, list):
            raise ValueError("Seed data must contain a 'patents' list")

    embedding_engine = EmbeddingEngine(settings.embedding_model)
    prepared: list[tuple[dict[str, Any], str]] = []
    for item in patents:
        claims = item.get("claims")
        if not isinstance(claims, list) or not claims:
            raise ValueError(f"Patent {item.get('patent_id')} has no valid claims")

        searchable_text = "\n".join(
            [str(item["title"]), str(item["abstract"]), *[str(claim) for claim in claims]]
        )
        prepared.append((item, searchable_text))

    records: list[Patent] = []
    batch_size = max(1, settings.embedding_batch_size)
    for start in range(0, len(prepared), batch_size):
        batch = prepared[start : start + batch_size]
        vectors = embedding_engine.embed_batch(
            [text for _, text in batch],
            batch_size=batch_size,
        )
        records.extend(
            Patent(
                patent_id=str(item["patent_id"]),
                title=str(item["title"]),
                abstract=str(item["abstract"]),
                claims=[str(claim) for claim in item["claims"]],
                category=str(item.get("category", "Imported Claims")),
                searchable_text=text,
                embedding=vector,
            )
            for (item, text), vector in zip(batch, vectors)
        )
        logger.info("Embedded %d of %d patent records", min(start + batch_size, len(prepared)), len(prepared))

    session.add_all(records)
    await session.commit()
    logger.info("Seeded %d patents into PostgreSQL", len(records))
    return len(records)


def _parse_claim_text(raw_claims: str) -> list[str]:
    """Split numbered multiline patent claims into individual claim strings."""
    normalized = raw_claims.replace("\r\n", "\n").strip()
    if not normalized:
        return []
    starts = list(_CLAIM_START.finditer(normalized))
    if not starts:
        return [normalized]
    claims: list[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(normalized)
        claim = normalized[start.end():end].strip()
        if claim:
            claims.append(claim)
    return claims


async def close_database() -> None:
    """Dispose database connections during application shutdown."""
    await engine.dispose()
