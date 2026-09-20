# ClaimGuard AI Migration Audit

> This audit maps the current repo to the agentic migration spec in the repo root.
> It is written before any code changes.

## Repo snapshot used for this audit

Current repo is `patent-protection-services/` with:

- `app/main.py`
- `app/core/config.py`
- `app/core/database.py`
- `app/core/rag_prompt.py`
- `app/api/endpoints.py`
- `app/models/patent.py`
- `app/services/pipeline.py`
- `app/services/rag_service.py`
- `embeddings.py`
- `generate_seed.py`
- `demo_rag.py`
- `test_phase1.py`
- `requirements.txt`
- `.env.template`
- `README.md`

There is no existing `docs/`, no `providers/` layer, no planner/agent code, no job/SSE API, no frontend, and no ML track code beyond `embeddings.py`.

---

## Decision translation for this repo

Spec decision → current reality:

- **D1 No hosted database** — In progress, not yet done. DB code still exists and is wired into startup, demo, and tests.
- **D2 Tool-using agent over patent APIs, page fetching only as claims fallback** — Not started. No provider layer exists.
- **D3 US-first, EP/WO optional** — Not started.
- **D4 Embeddings computed in memory, optional local cache** — Partially aligned today. Embeddings exist, but they are used with a DB-backed index instead of an in-memory candidate pool.
- **D5 LLM strategy unchanged behind one interface** — Partially aligned. Today there is a direct Gemini path in `rag_service.py`, not an `LLMClient` interface.
- **D6 Async job API + SSE** — Not started. Current API is synchronous `POST /api/v1/analyze`.
- **D7 Verbatim quote verification** — Not started. Today's report parsing is generic JSON repair, not claim-level quote verification.
- **D8 Heavy ML in a process pool** — Not applicable yet. Current repo has no UMAP/KMeans track.

---

## Change map for the current codebase

### REMOVE

- `app/core/database.py`
  - Remove PostgreSQL/pgvector lifecycle, seeding, and session factory.
- `app/models/patent.py`
  - Remove the ORM patent model and pgvector column.
- `app/api/endpoints.py` synchronous `/analyze` behavior
  - Replace with job API + SSE. If a thin synchronous shim is needed for tests, implement it later as a test-only helper.
- `app/services/pipeline.py` current DB-backed retrieval path
  - Replace with in-memory candidate flow + providers.
- `app/services/rag_service.py` current Gemini-specific direct client usage
  - Keep the report-generation *intent*, but move it behind an LLM client interface and add claim/quote verification.
- `app/core/config.py` database-only settings that become irrelevant
  - Remove Postgres-specific fields that the migration spec no longer needs, or neutralize them.
- `.env.template` database block
- `README.md` pgvector/PostgreSQL/docker compose instructions
- `requirements.txt` SQLAlchemy/pgvector/asyncpg entries if they are no longer needed after migration.
- `generate_seed.py` as a runtime seed tool
  - Spec says remove ingestion scripts but keep trimmed copies as test fixtures.
- `demo_rag.py` DB-oriented demo
  - Replace or rewrite toward the new job/SSE pipeline when appropriate.
- `test_phase1.py` DB-oriented assertions
  - Rewrite toward the new architecture; keep useful structural checks if they still apply.

### MODIFY

- `app/main.py`
  - Keep as the FastAPI entry point, but rework lifespan, routing, and app description for the new pipeline.
- `app/core/config.py`
  - Keep pydantic-settings style, but add provider/agent/ML/cache/job env vars from spec section 18.
- `app/core/rag_prompt.py`
  - Keep the grounded-prompt intent, but adapt it for fetched claims, structured output, and the verifier workflow from spec section 11.
- `embeddings.py`
  - Keep the embedding capability, but wrap it behind the spec's `Embedder` interface and make it batch/cache aware.
- `app/services/rag_service.py` parsing logic
  - Keep some of the JSON resilience thinking if useful, but move the main contract to Pydantic models and add verification.
- `README.md`
  - Rewrite around agentic retrieval, job/SSE flow, and the no-hosted-database story.

### KEEP (as-is or with minor updates)

- FastAPI as the backend framework.
- Pydantic v2 as the validation approach.
- Python 3.11+ typing discipline already present.
- The general idea of a grounded LLM report, though implementation changes substantially.
- The existing Gemini dependency if the team still wants Gemini as one LLM backend.

### ADD

This is the bulk of the migration. Spec target layout is in section 5 of the spec; adapted to this repo it means adding:

- `app/providers/`
  - `base.py`, `pqai.py`, `uspto_odp.py`, `patentsview.py`, `epo_ops.py`, `google_patents_page.py`, `registry.py`, `ids.py`
- `app/agent/`
  - `planner.py`, `retrieval.py`, `evaluator.py`, `budget.py`
- `app/ml/`
  - `embedder.py`, `ranking.py`, `projection.py`, `workers.py`
- `app/rag/`
  - `claims.py`, `analyzer.py`, `verifier.py`, `prompts.py`
- `app/llm/`
  - `client.py`, plus backend implementations
- `app/cache/`
  - `store.py`
- `app/api/routes_analyses.py` and `routes_health.py`
- `app/core/jobs.py` and `app/core/events.py`
- `app/models/`
  - new data contract models for patents, planning, events, results
- `docs/`
  - `MIGRATION_AUDIT.md`, `PROVIDERS.md`, `ARCHITECTURE.md`, `EVAL.md`
- Frontend work
  - Not present in this repo yet; spec expects React + Vite + Tailwind, SSE hook, agent trace, scatter map, report and evidence components.

---

## What "done" should look like for this repo

Per spec section 20, the final system should:

- have no PostgreSQL/pgvector/Pinecone anywhere in code, compose, CI, or docs
- accept a draft and produce a live agent trace, a cluster-colored 2D map with a blinking user node, and a risk report whose displayed quotes are verified against fetched claim text
- work with an empty cache, with a search provider down, and with missing claims for some patents
- keep heavy ML off the event loop
- include an eval report with Recall@50, Recall@5, quote verification rate, and latency

---

## Immediate implications for next steps

1. This repo is currently about half-built for the **old** RAG design and essentially a scaffold for the **new** agentic design.
2. The migration is large. Spec section 17 phases are the right planning unit.
3. The first code moves should probably be:
   - decide whether to keep the current app layout or move to the spec's proposed `backend/` structure
   - remove the PostgreSQL/pgvector runtime dependency first, because it touches config, startup, models, pipeline, demo, and tests
   - introduce provider interfaces and `ids.py` early, since everything downstream depends on normalized patent IDs
