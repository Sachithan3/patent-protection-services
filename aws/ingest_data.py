"""One-shot data ingestion: S3 CSV -> embed -> RDS bulk insert.

Run as an ECS one-shot task or locally with AWS credentials configured.
"""

import asyncio
import csv
import json
import logging
import os
import sys
import re
from io import StringIO
from typing import Any

import boto3
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

csv.field_size_limit(sys.maxsize)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest")

_CLAIM_START = re.compile(r"(?m)^\s*\d+\s*\.\s*")

def get_secret(secret_name: str) -> dict[str, Any]:
    """Retrieve a JSON secret from AWS Secrets Manager."""
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response["SecretString"])

def download_csv_from_s3(bucket: str, key: str) -> str:
    """Download CSV content from S3."""
    s3 = boto3.client("s3")
    logger.info("Downloading s3://%s/%s", bucket, key)
    response = s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read().decode("utf-8-sig")

def parse_claim_text(raw_claims: str) -> list[str]:
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

async def ingest(
    db_url: str,
    bucket: str,
    key: str,
    model_name: str = "all-MiniLM-L6-v2",
    batch_size: int = 128,
) -> int:
    """Ingest patents from S3 CSV into RDS."""
    from embeddings import EmbeddingEngine
    from app.models.patent import Base, Patent

    engine = create_async_engine(db_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        existing = await session.scalar(select(Patent.id).limit(1))
        if existing is not None:
            logger.info("Database already contains %s records -- skipping ingestion", existing)
            return 0

    csv_content = download_csv_from_s3(bucket, key)
    reader = csv.DictReader(StringIO(csv_content))
    required = {"publication_number", "title", "abstract", "claims"}
    missing = required - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"CSV missing required columns: {', '.join(sorted(missing))}")

    patents = [
        {
            "patent_id": (row.get("publication_number") or "").strip(),
            "title": (row.get("title") or "").strip(),
            "abstract": (row.get("abstract") or "").strip(),
            "claims": parse_claim_text(row.get("claims") or ""),
            "category": "Imported Claims",
        }
        for row in reader
        if (row.get("publication_number") or "").strip()
        and (row.get("title") or "").strip()
        and (row.get("abstract") or "").strip()
    ]
    logger.info("Parsed %d patents from CSV", len(patents))

    embedding_engine = EmbeddingEngine(model_name)
    records: list[Patent] = []

    for start in range(0, len(patents), batch_size):
        batch = patents[start : start + batch_size]
        prepared = []
        for item in batch:
            claims = item.get("claims")
            if not isinstance(claims, list) or not claims:
                logger.warning("Skipping %s -- no valid claims", item.get("patent_id"))
                continue
            searchable = "\n".join(
                [str(item["title"]), str(item["abstract"]), *[str(c) for c in claims]]
            )
            prepared.append((item, searchable))

        vectors = embedding_engine.embed_batch(
            [text for _, text in prepared], batch_size=batch_size
        )
        for (item, searchable), vector in zip(prepared, vectors):
            records.append(
                Patent(
                    patent_id=str(item["patent_id"]),
                    title=str(item["title"]),
                    abstract=str(item["abstract"]),
                    claims=[str(c) for c in item["claims"]],
                    category=str(item.get("category", "Imported Claims")),
                    searchable_text=searchable,
                    embedding=vector,
                )
            )
        logger.info("Embedded %d/%d", min(start + batch_size, len(patents)), len(patents))

    async with session_factory() as session:
        session.add_all(records)
        await session.commit()

    logger.info("Ingested %d patents into RDS", len(records))
    await engine.dispose()
    return len(records)

if __name__ == "__main__":
    secret = get_secret(os.environ.get("DB_SECRET_NAME", "claimguard/db-credentials"))
    host = os.environ["DATABASE_HOST"]
    port = os.environ.get("DATABASE_PORT", "5432")
    name = os.environ.get("DATABASE_NAME", "claimguard_db")
    db_url = (
        f"postgresql+asyncpg://{secret['username']}:{secret['password']}"
        f"@{host}:{port}/{name}"
    )
    bucket = os.environ["DATA_BUCKET"]
    key = os.environ.get("DATA_KEY", "Patents_data_withclaims.csv")
    model = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    batch = int(os.environ.get("EMBEDDING_BATCH_SIZE", "128"))

    count = asyncio.run(ingest(db_url, bucket, key, model, batch))
    print(f"Ingested {count} patents")
