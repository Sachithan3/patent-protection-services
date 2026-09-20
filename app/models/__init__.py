"""Application data models.

Submodules are imported directly (`from app.models.patents import PatentStub`) so the
lightweight contract models stay importable without the heavy persistence stack
(sqlalchemy/pgvector) that lives in `app.models.patent`.
"""
