"""Terminal demonstration of the complete ClaimGuard RAG pipeline."""

import asyncio
import json
import logging

from app.core.database import close_database, init_database
from app.services.pipeline import analyze_draft_infringement


DEMO_DRAFT = (
    "An autonomous indoor drone navigates warehouses without GPS by combining LiDAR "
    "and event-camera streams into a sparse three-dimensional occupancy representation. "
    "An edge FPGA performs sparse convolutional feature extraction and a reinforcement "
    "learning controller selects collision-free trajectories in under ten milliseconds. "
    "The drone coordinates with nearby units through low-latency wireless messages."
)


async def main() -> None:
    """Initialize local infrastructure and execute the RAG demonstration."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("=" * 78)
    print("ClaimGuard AI - RAG Demonstration")
    print("=" * 78)
    print("\n[1/4] Initializing PostgreSQL, pgvector, and seed index...")
    await init_database()
    try:
        print("[2/4] Vector Generation")
        print("      Encoding the autonomous indoor drone draft with all-MiniLM-L6-v2...")
        print("\n[3/4] Cosine Similarity Matching")
        print("      Querying PostgreSQL with pgvector cosine distance (<=>)...")
        print("\n[4/4] RAG Context Formatting and LLM Report Generation")
        result = await analyze_draft_infringement(DEMO_DRAFT, top_k=5)

        print("\nRetrieved patents:")
        for index, patent in enumerate(result["matching_patents"], start=1):
            print(
                f"  {index}. {patent['patent_id']} | "
                f"distance={patent['cosine_distance']:.4f} | {patent['title']}"
            )

        print("\nGrounded infringement report:")
        print(json.dumps(result["llm_infringement_report"], indent=2))
        print("\nDemo completed.")
    finally:
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
