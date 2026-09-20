# Next Steps for the Coding Agent — ClaimGuard AI Migration

> Read `shared-context.md`, then this file. Stay on the current branch until Phase 1b is green.
> Current branch: `agent/phase-0.5-1a-complete` (branched from `master 9a650e6`).
> Phase 0.5 + 1a is committed as the branch base. Do not rewrite that commit.

## 0. Branch and commit discipline (done, keep following it)

- Work on `agent/phase-0.5-1a-complete` only. Do not commit to `master`.
- One logical commit per adapter or module. Small, reviewable commits.
- Never commit `.venv/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.cache/`, `data/seed_patents.json` (all gitignored).
- Update `shared-context.md` milestone log with every commit that changes behavior.

## 1. Verify the base before new code

Run from `patent-protection-services/`:

```bash
.venv/Scripts/python -m pytest
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m mypy
```

Expected: `70 passed`, `All checks passed!`, `no issues found in 7 source files`.
If any gate is red, stop and fix before Phase 1b.

## 2. Phase 1b — search/claims adapters + registry (in this order)

1. `app/providers/pqai.py` — primary semantic search. Map raw response to `PatentStub`.
2. `app/providers/uspto_odp.py` — US metadata + claims. Map to `PatentStub` and `PatentClaims`.
3. `app/providers/patentsview.py` — enrichment only (assignee, CPC, citations). Never a claims source.
4. `app/providers/registry.py` — parallel fan-out, merge keyed by `dedupe_key`, per-provider failure becomes a warning. Search order `PQAI -> USPTO_ODP -> PATENTSVIEW`. Claims order `USPTO_ODP -> GOOGLE_PATENTS_PAGE` (`EPO` behind `ENABLE_EPO=false`).
5. `app/providers/epo_ops.py` (flagged off) and `app/providers/google_patents_page.py` (claims fallback only) last. Page fetcher must enforce `app/core/ssrf.py`: `validate_page_url()` + `is_allowed_ip()` post-DNS, redirects disabled, ~2 MB / timeout caps, real `User-Agent` from env.
6. `app/providers/demo.py` — `python -m app.providers.demo "<query>"` prints normalized stubs from at least one live provider.

For every adapter:

- Confirm each spec 7.2 `VERIFY` item against official docs. Log endpoint, auth, rate limits, response mapping, quirks, and verification date in `docs/PROVIDERS.md`.
- Record fixtures under `tests/fixtures/` with respx. Contract tests assert raw response maps to `PatentStub` / `PatentClaims`.
- Reuse `ProviderHttpClient` (15 s timeout, tenacity 429/5xx/timeout retries, `TokenBucket`, `CircuitBreaker`). Do not build ad-hoc HTTP.
- Watch known sharp edges: `TokenBucket` has no async lock (concurrent acquire can race under `PROVIDER_CONCURRENCY=4`); `CircuitBreaker` half-open allows multiple trial calls — bound both with the registry semaphore.

## 3. Go/no-go #1 (stop here and report)

Live-verify PQAI and USPTO ODP return usable abstracts plus claims. If either fails, stop before Phase 2 and revisit spec 7.2. Paste the demo CLI output and `docs/PROVIDERS.md` dates into `shared-context.md`.

## 4. After go — Phase 2 preview (do not start early)

- `app/ml/embedder.py` (`Embedder` protocol + `SentenceTransformerEmbedder`, batch 32, thread-offloaded), `app/ml/ranking.py` (`cosine_rank` + brute-force equivalence test), `app/cache/store.py` (SQLite + no-op; all tests pass on no-op).
- DB removal sweep only then: `app/core/database.py`, `app/models/patent.py`, seed logic, DB blocks in `.env.template`, `pgvector`/`sqlalchemy`/`asyncpg` from `requirements.txt`, DB docs in `README.md`. Rewrite `test_phase1.py` at that point, not before.

## 5. Standing constraints

- Python 3.10 compatible (no `typing.Self`, no `except*`). Ruff/mypy `py310`.
- K2 holds: keep the current app runnable throughout Phase 1b. No DB deletion yet.
- K3 holds: Gemini only. No Ollama/Groq adapters in this phase.
- K4 holds: no frontend. Keep `map_points`/`clusters` contract in mind for `ml_done` payloads later.
- Full type hints, Pydantic v2, `httpx.AsyncClient`, tenacity, pytest + pytest-asyncio, ruff + mypy.
