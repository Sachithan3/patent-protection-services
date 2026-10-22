"""Graph-layer persistence models for the patent knowledge graph."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.patent import Base


class ConceptCache(Base):
    """Cached concept-extraction result per patent.

    Stores the list of bigram/trigram technical concepts extracted from a
    patent's title, abstract, and first claim so we avoid repeating the
    extraction on every graph request.  Each row maps one patent_id (the
    string publication identifier, not the integer PK) to the JSON list of
    concept strings that were extracted for it.
    """

    __tablename__ = "concept_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patent_id: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    concepts: Mapped[list] = mapped_column(JSON, nullable=False)
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def to_dict(self) -> dict:
        return {
            "patent_id": self.patent_id,
            "concepts": self.concepts,
            "cached_at": self.cached_at.isoformat() if self.cached_at else None,
        }
