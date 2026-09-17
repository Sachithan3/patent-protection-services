"""Patent persistence model with a pgvector embedding column."""

from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for ClaimGuard ORM models."""


class Patent(Base):
    """Patent document indexed for semantic retrieval."""

    __tablename__ = "patents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patent_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    abstract: Mapped[str] = mapped_column(Text)
    claims: Mapped[list[str]] = mapped_column(JSON)
    category: Mapped[str] = mapped_column(String(128), index=True)
    searchable_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(384))

    def to_dict(self, distance: float | None = None) -> dict[str, Any]:
        """Serialize the model into the retrieval response shape."""
        payload: dict[str, Any] = {
            "patent_id": self.patent_id,
            "title": self.title,
            "category": self.category,
            "abstract": self.abstract,
            "claims": self.claims,
        }
        if distance is not None:
            payload["cosine_distance"] = float(distance)
            payload["cosine_similarity"] = float(1.0 - distance)
        return payload
