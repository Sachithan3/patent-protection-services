"""Demo CLI: python -m app.providers.demo "<query>" [limit]

Prints normalized patent stubs from the live provider chain. Exit code 0 with at
least one stub; 1 otherwise. Missing credentials surface as visible warnings.
"""

import argparse
import asyncio
import logging

from app.models.plan import QueryVariant
from app.providers.registry import build_registry


async def run(query: str, limit: int) -> int:
    registry = build_registry()
    try:
        variant = QueryVariant(text=query, kind="natural_language", rationale="demo CLI")
        outcome = await registry.search([variant], limit)

        print(f"Query: {query!r}")
        print(f"Providers contacted: {', '.join(outcome.providers_used) or 'none'}")
        for warning in outcome.warnings:
            print(f"  WARNING [{warning.provider}] {warning.message}")
        print(f"Unique candidates: {len(outcome.pool)}\n")

        ranked = list(outcome.pool.values())[:limit]
        for index, stub in enumerate(ranked, start=1):
            score = f" score={stub.provider_score:.3f}" if stub.provider_score is not None else ""
            abstract_flag = "" if stub.abstract else " (no abstract)"
            print(f"  {index}. {stub.patent_id} [{stub.source}]{score}{abstract_flag}")
            print(f"     {stub.title[:90]}")

        return 0 if outcome.pool else 1
    finally:
        await registry.aclose()


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Query live providers and print stubs.")
    parser.add_argument("query", help="Natural-language invention description")
    parser.add_argument(
        "limit", nargs="?", type=int, default=5, help="Results to print (default 5)"
    )
    args = parser.parse_args()
    return asyncio.run(run(args.query, args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
