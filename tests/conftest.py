"""pytest configuration: stub out heavy / unavailable dependencies.

This allows the pure-unit tests and API-shape tests to run without
downloading ML models, connecting to PostgreSQL, or installing google-genai.
"""
import sys
import types
from unittest.mock import AsyncMock, MagicMock


def _make_stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


# ── google namespace ─────────────────────────────────────────────────────────
google = sys.modules.get("google") or _make_stub("google")

# google.genai
genai_mod = _make_stub("google.genai")
genai_mod.Client = MagicMock()  # type: ignore[attr-defined]

# google.genai.types  (imported as `from google.genai import types`)
genai_types = _make_stub("google.genai.types")
genai_mod.types = genai_types  # type: ignore[attr-defined]

# Attach to google namespace
google.genai = genai_mod  # type: ignore[attr-defined]
sys.modules["google"] = google
sys.modules["google.genai"] = genai_mod
sys.modules["google.genai.types"] = genai_types

# ── sentence_transformers (embedding model) ──────────────────────────────────
if "sentence_transformers" not in sys.modules:
    st = _make_stub("sentence_transformers")

    import numpy as np

    class _FakeST:
        def __init__(self, *a, **kw):
            pass
        def encode(self, texts, **kw):
            if isinstance(texts, str):
                return np.zeros(384)
            return np.zeros((len(texts), 384))
        def get_sentence_embedding_dimension(self):
            return 384

    st.SentenceTransformer = _FakeST  # type: ignore[attr-defined]

# ── torch ────────────────────────────────────────────────────────────────────
if "torch" not in sys.modules:
    _make_stub("torch")

# ── Environment defaults so Settings() doesn't fail ─────────────────────────
import os
os.environ.setdefault("DATABASE_HOST", "localhost")
os.environ.setdefault("DATABASE_PORT", "5433")
os.environ.setdefault("DATABASE_USER", "test_user")
os.environ.setdefault("DATABASE_PASSWORD", "test_pass")
os.environ.setdefault("DATABASE_NAME", "test_db")
os.environ.setdefault("GEMINI_API_KEY", "test_key")
os.environ.setdefault("SEED_DATA_PATH", "data/Patents_data_withclaims.csv")
