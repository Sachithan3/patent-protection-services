#!/usr/bin/env python3
"""Import title-and-abstract patent records from a CSV file."""

import argparse
import asyncio
import csv
import logging
import sys
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import AsyncSessionLocal, close_database, init_database
from app.models.patent import Patent
from app.services.pipeline import get_embedding_engine

logger = logging.getLogger("import_patent_csv")


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        required = {"publication_number", "title", "abstract"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")

        rows = []
        for row in reader:
            patent_id = (row.get("publication_number") or "").strip()
            title = (row.get("title") or "").strip()
            abstract = (row.get("abstract") or "").strip()
            if patent_id and title and abstract:
                rows.append(
                    {
                        "patent_id": patent_id,
                        "title": title[:500],
                        "abstract": abstract,
                    }
                )
        return rows


async def import_rows(path: Path, batch_size: int) -> int:
    rows = read_rows(path)
    embedding_engine = get_embedding_engine()
    imported = 0

    async with AsyncSessionLocal() as session:
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            searchable_texts = [f"{row['title']}\n{row['abstract']}" for row in batch]
            vectors = embedding_engine.embed_batch(searchable_texts)
            values = [
                {
                    "patent_id": row["patent_id"],
                    "title": row["title"],
                    "abstract": row["abstract"],
                    "claims": [],
                    "category": "CSV Import",
                    "searchable_text": text,
                    "embedding": vector,
                }
                for row, text, vector in zip(batch, searchable_texts, vectors)
            ]
            statement = insert(Patent).values(values)
            statement = statement.on_conflict_do_update(
                index_elements=[Patent.patent_id],
                set_={
                    "title": statement.excluded.title,
                    "abstract": statement.excluded.abstract,
                    "claims": statement.excluded.claims,
                    "category": statement.excluded.category,
                    "searchable_text": statement.excluded.searchable_text,
                    "embedding": statement.excluded.embedding,
                },
            )
            await session.execute(statement)
            await session.commit()
            imported += len(batch)
            logger.info("Imported %d of %d records", imported, len(rows))
    return imported


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=256)
    args = parser.parse_args()
    if not args.input.exists():
        raise FileNotFoundError(f"CSV file does not exist: {args.input}")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        await init_database()
        imported = await import_rows(args.input, args.batch_size)
        logger.info("Imported %d CSV patent records", imported)
    finally:
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
