# ClaimGuard AI — Implementation Plan

> Companion to `CLAIMGUARD_AGENTIC_MIGRATION.md` (the spec) and `docs/MIGRATION_AUDIT.md` (the audit).
> This plan adapts the spec's phased rollout (section 17) to the real repo layout in `patent-protection-services/`.
> Decisions K1–K4 were confirmed by the user on 2026-09-20. The active work stream is Phase 0.5 + Phase 1a in one pass (per K2).

## 0. Baseline facts this plan relies on

- Repo is backend-only today. There is no `frontend/`, no `docs/` (now created), no `tests/` in the pytest sense.
- Existing runtime pieces: FastAPI app (`app/main.py`), synchronous `POST /api/v1/analyze`, Gemini-direct report generation, pgvector persistence, seed script, terminal demo, structural (non-pytest) test script.
- Python version note: code already uses `str | None` (3.10+) while README claims 3.8+ support. The spec requires 3.11+; docs must be corrected either way.
- Dependencies are heavily pinned (fastapi 0.109, pydantic 2.5, torch 2.2.0+cpu via extra index). The migration adds `httpx`, `tenacity`, `sse-starlette`, `pytest`, `pytest-asyncio`, `respx` or `vcrpy`, `ruff`, `mypy`, and later `umap-learn` + `scikit-learn`. Pin strategy: **[CONFIRM]** relax pins vs. bump them per phase.

## 1. Standing decisions (defaults, per spec section 0 item 6)

| # | Decision | Confirmed choice |
|---|----------|------------------|
| K1 | Repo layout | **Keep the existing `app/` package.** New packages (`providers/`, `agent/`, `ml/`, `rag/`, `llm/`) live under `app/`. |
| K2 | First code move | **Phase 0.5 tooling uplift + Phase 1a provider foundations in one pass**, keeping the current app runnable throughout. DB removal still lands in Phase 2. |
| K3 | LLM backends | **Gemini only first.** Phase 3 ports the existing Gemini path behind `LLMClient`; Ollama/Groq adapters come later behind the same interface. |
| K4 | Frontend scope | **Out of scope for this repo.** Phase 6 is a hand-off stub; the backend still ships `map_points`/`clusters` inside the `ml_done` event data per spec 13.1 so a future frontend can render early. |

Assumptions taken from the spec itself (not re-confirmed): D1–D8 in spec section 1, provider orders in spec 7.3, budget defaults in spec 8.3.

## 2. Phase plan (spec section 17 adapted)

Legend: ✅ done · 🔜 next · ⛔ blocked on a **[CONFIRM]** decision.

### ✅ Phase 0 — Audit and scaffolding
- [x] `docs/MIGRATION_AUDIT.md` written against the real module list.
- [x] `docs/` directory exists.
- *Accept:* audit reviewed by user — this plan is the review artifact.

### 🔜 Phase 0.5 — Tooling uplift (small, unglamorous, first)
Repo has no pytest suite; the spec's acceptance criteria are all test-based, so this must land before anything else can be "green".
- Add `requirements-dev.txt`: `pytest`, `pytest-asyncio`, `httpx`, `respx` (contract tests), `ruff`, `mypy`, `tenacity` (also runtime).
- Create `tests/unit/`, `tests/contract/`, `tests/integration/`, `tests/fixtures/` per spec section 16.
- Configure `pyproject.toml` (ruff + mypy + pytest-asyncio), minimal strictness, tightened per phase.
- Wrap `test_phase1.py` content: keep as a script, but exclude from pytest collection until rewritten in Phase 2.
- *Accept:* `pytest` runs (even if near-empty), `ruff check .` and `mypy app` pass on the current codebase.

### Phase 1a — Provider foundations (no network)
- Add `app/providers/base.py` (Protocols + `ProviderError`, spec 7.1), `app/providers/ids.py` (spec 7.4 code verbatim as starting point).
- Add `app/core/ratelimit.py` (token bucket) and `app/core/ssrf.py` (host allowlist, IP-range blocking, size/time caps — spec 14.3) now, because every adapter needs them and they are pure logic.
- Add `app/providers/http.py`: shared `httpx.AsyncClient` factory wiring timeout 15 s, tenacity retries (3, exp backoff + jitter, only 429/5xx/timeouts), per-provider rate limit, circuit breaker state.
- Tests: `tests/unit/test_ids.py` (15+ real formats per spec 16.1), ratelimit bucket tests, SSRF guard tests.
- *Accept:* unit tests green; nothing here touches the network.

### Phase 1b — Search/claims adapters + registry
- Implement `app/providers/pqai.py` (primary search) and `app/providers/uspto_odp.py` (metadata + claims) first, then `app/providers/patentsview.py` (enrichment only). `epo_ops.py` behind `ENABLE_EPO=false`; `google_patents_page.py` claims-fallback last (selectors isolated, fixture-tested).
- `app/providers/registry.py`: parallel fan-out, merge, per-provider failure = warning; claims order `USPTO_ODP -> (EPO?) -> GOOGLE_PATENTS_PAGE`.
- Record fixtures in `tests/fixtures/` via respx; contract tests map raw responses → `PatentStub` / `PatentClaims`.
- ⚠️ Every `VERIFY` item in spec 7.2 must be confirmed against official docs and logged in `docs/PROVIDERS.md` with a verification date. This phase needs live network access once, for recording.
- Add `python -m app.providers.demo "<query>"` CLI (spec Phase 1 accept criterion).
- *Accept:* contract tests pass; demo CLI prints normalized stubs from ≥1 live provider; `docs/PROVIDERS.md` exists.

### Phase 2 — In-memory embed + rank; remove the database
- `app/ml/embedder.py`: `Embedder` protocol (spec 9.1) + `SentenceTransformerEmbedder` wrapping the existing `embeddings.py` engine (batch 32, thread-offloaded). `FastembedEmbedder` deferred to Phase 7 unless memory forces it.
- `app/ml/ranking.py`: `cosine_rank` from spec 9.2 + brute-force equivalence test.
- `app/cache/store.py`: SQLite cache + no-op implementation; all tests must pass with no-op (spec 14.1).
- `app/models/patents.py`: `PatentStub`, `Claim`, `PatentClaims` (spec 6) — this replaces the ORM model.
- Rewire `app/services/pipeline.py` to fetch candidates from the registry instead of pgvector; keep the function signature stable for `demo_rag.py`.
- **Remove:** `app/core/database.py`, `app/models/patent.py`, seed logic from startup, DB blocks in `.env.template`, `pgvector`/`sqlalchemy`/`asyncpg` from `requirements.txt`, DB instructions from `README.md`, docker instructions. Keep `generate_seed.py` output as trimmed test fixtures (spec change map).
- Update `app/api/endpoints.py` health check (drop DB probe, keep embedder probe) — full replacement comes in Phase 5.
- *Accept:* end-to-end draft → top-50 with similarities runs with **no DB process**; `pytest` green; README no longer mentions pgvector.

### Phase 3 — Planner and retrieval agent
- `app/llm/client.py` (`LLMClient` protocol), `app/llm/gemini.py` (port `rag_service._generate_with_gemini`), `app/llm/structured.py` (JSON parse/validate/retry). `ollama.py`/`groq.py` behind the same interface per K3.
- `app/models/plan.py`: `SearchPlan`, `QueryVariant` (spec 6). Planner prompt from spec 8.1.
- `app/agent/planner.py`, `app/agent/evaluator.py`, `app/agent/budget.py`, `app/agent/retrieval.py` (loop from spec 8.2, plateau stop rule, budgets from spec 8.3 — every consumption emits an event).
- `tests/eval/`: build the 10–20 case set (spec 16.4). Measure single-shot vs agentic Recall@50.
- *Accept:* agentic ≥ single-shot Recall@50 on the eval set; budget/stop-condition unit tests green.

### Phase 4 — Claims, analyzer, verifier
- `app/rag/claims.py` (fetch chain, parallel sem 3, drop-not-guess), claim parser with dependency detection unit tests.
- `app/rag/prompts.py`: port `app/core/rag_prompt.py` intent into the spec 11.2 system prompt + tagged user layout; delete the old file.
- `app/rag/analyzer.py`, `app/rag/verifier.py` (spec 11.4 code as the base), report assembly per spec 11.3.
- `app/models/results.py`: `MapPoint`, `Cluster`, `RiskFinding`, `AnalysisReport`, `Provenance`, `AnalysisResult` (spec 6).
- Tests: verifier variants (curly quotes, hyphens, wrong claim number, paraphrase rejection), prompt-injection fixture test.
- *Accept:* quote verification rate ≥ 0.9 on eval set with the production LLM; injection test passes; degraded mode (map without report) tested.

### Phase 5 — Job API and SSE
- `app/core/jobs.py` (in-memory jobs, TTL 1 h, max 200, semaphore `MAX_CONCURRENT_JOBS=2`) and `app/core/events.py` (`AgentEvent`, per-job event log + subscriber queues).
- `app/api/routes_analyses.py`: `POST /api/analyses`, `GET /api/analyses/{id}`, `GET /api/analyses/{id}/events` (SSE, `Last-Event-ID` replay, 15 s heartbeat); `app/api/routes_health.py`. Old `endpoints.py` deleted; sync shim exists only in tests.
- `app/main.py`: lifespan starts job manager + UMAP warm-up (once Phase 7 adds `app/ml/workers.py`), removes DB init.
- Orchestrator per spec 12.3 with `return_exceptions=True` degraded-mode rules.
- *Accept:* SSE integration tests (reconnect, no lost/duplicated events), 3-job concurrency test, both degraded modes tested.

### Phase 6 — Frontend (per K4: hand-off stub, not built here)
- If the frontend lands in this repo later: React + Vite + Tailwind, components per spec 13.2, consuming the `ml_done` event payload prepared in Phase 5.
- *Accept (stub):* spec 13 contract documented in `docs/ARCHITECTURE.md`; example `curl` event stream in README.

### Phase 7 — Hardening, ML track, deploy
- `app/ml/projection.py` + `app/ml/workers.py` (spec 10: process pool, numba warm-up, small-n PCA fallback, silhouette-chosen k, TF-IDF labels). This is deliberately late: the map is the least load-bearing artifact and the job API must exist first.
- Docker: remove `db` service entirely, single-stage slim image, non-root, `--workers 1`, model pre-download.
- Memory measurement (peak RSS per job) recorded in `docs/ARCHITECTURE.md`; switch to `FastembedEmbedder` if over budget.
- Rewrite README (spec 15.3), write `docs/EVAL.md`, `docs/ARCHITECTURE.md`; `.env.example` per spec 18 replaces `.env.template`.
- *Accept:* deployed job completes within 150 s budget on a free tier; all docs match reality.

## 3. Repo-specific risks the spec doesn't call out

1. **Pinned deps vs new ones.** `torch==2.2.0+cpu` on the pytorch extra index is the brittle one; `umap-learn` (numba/llvmlite) has tight numpy version coupling with the pinned `numpy==1.26.4`. Budget for a dependency-bump session in Phase 7 (or earlier if installs break).
2. **Windows dev box.** Process-pool code (`app/ml/workers.py`) needs the `if __name__ == "__main__"` guard discipline and spawn-context awareness; warm-up in lifespan must not assume fork.
3. **`test_phase1.py` asserts the old world** (checks `pgvector` in requirements, DB vars in `.env`). It will start failing in Phase 2 by design — plan its rewrite/remove then, not before.
4. **No `data/` directory exists yet** even though `config.py` points at `data/seed_patents.json`; it is generated by `generate_seed.py`. Fixture extraction in Phase 2 must handle the case where seeds were never generated on this machine.

## 4. Go/no-go checkpoints

- End of Phase 1b: are the chosen providers actually returning usable abstracts + claims? If PQAI or USPTO ODP fails live verification, stop and revisit spec 7.2 before Phase 2 wiring.
- End of Phase 3: Recall@50 comparison. If agentic refinement doesn't beat single-shot, simplify (keep single-shot + budget guards) rather than complicate.
- End of Phase 4: verification rate ≥ 0.9. If not, fix prompts/model before building SSE UX on top.
