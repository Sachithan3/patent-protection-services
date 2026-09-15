"""Async PostgreSQL/pgvector database lifecycle and seed management."""

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.models.patent import Base, Patent

logger = logging.getLogger(__name__)

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
    """Embed and insert the JSON seed patents into PostgreSQL."""
    from embeddings import EmbeddingEngine

    seed_path = Path(settings.seed_data_path)
    if not seed_path.exists():
        raise FileNotFoundError(f"Seed data file does not exist: {seed_path}")

    with seed_path.open("r", encoding="utf-8") as seed_file:
        payload: dict[str, Any] = json.load(seed_file)

    patents = payload.get("patents")
    if not isinstance(patents, list):
        raise ValueError("Seed data must contain a 'patents' list")

    embedding_engine = EmbeddingEngine(settings.embedding_model)
    records: list[Patent] = []
    for item in patents:
        claims = item.get("claims")
        if not isinstance(claims, list) or not claims:
            raise ValueError(f"Patent {item.get('patent_id')} has no valid claims")

        searchable_text = "\n".join(
            [str(item["title"]), str(item["abstract"]), *[str(claim) for claim in claims]]
        )
        records.append(
            Patent(
                patent_id=str(item["patent_id"]),
                title=str(item["title"]),
                abstract=str(item["abstract"]),
                claims=[str(claim) for claim in claims],
                category=str(item["category"]),
                searchable_text=searchable_text,
                embedding=embedding_engine.embed_text(searchable_text),
            )
        )

    session.add_all(records)
    await session.commit()
    logger.info("Seeded %d patents into PostgreSQL", len(records))
    return len(records)


async def close_database() -> None:
    """Dispose database connections during application shutdown."""
    await engine.dispose()
