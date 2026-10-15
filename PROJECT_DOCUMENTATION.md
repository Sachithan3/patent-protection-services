# ClaimGuard AI — Project Documentation

ClaimGuard AI is a FastAPI service for preliminary patent-overlap analysis. It combines
semantic patent retrieval, lexical feature comparison, claim-level evidence when
available, and grounded Gemini report generation.

> **Important:** Results are technical screening signals for preliminary review. They
> are not a probability of infringement, a legal opinion, or a substitute for qualified
> patent counsel.

## 1. System Overview

```text
Technical draft
      |
      v
Sentence-transformer embedding
      |
      v
PostgreSQL + pgvector candidate retrieval
      |
      v
Claim/feature reranking
      |
      v
Evidence-aware risk scoring
      |
      v
Grounded Gemini JSON report
      |
      v
FastAPI response + browser dashboard
```

The application has two evidence paths:

- **Claim evidence:** Used when indexed patent claims are present. The score is based
  on claim-level semantic and lexical overlap.
- **Title/abstract evidence:** Used for CSV records that do not contain claims. The
  score combines semantic similarity and technical feature coverage, but must not be
  described as proven claim overlap.

Semantic similarity is kept as a discovery signal and is not used by itself to
determine legal risk.

## 2. Repository Structure

```text
.
├── app/
│   ├── api/endpoints.py          FastAPI routes and request validation
│   ├── core/
│   │   ├── config.py             Environment-backed settings
│   │   ├── database.py           Database lifecycle and seed loading
│   │   └── rag_prompt.py         Grounding and report schema instructions
│   ├── models/patent.py          SQLAlchemy Patent model
│   ├── services/
│   │   ├── pipeline.py           Retrieval, reranking, and score calibration
│   │   └── rag_service.py        Gemini orchestration and context formatting
│   └── static/                   Browser dashboard
├── data/
│   └── Patents_data_withclaims.csv  Claim-bearing patent dataset
├── scripts/import_patent_csv.py  CSV ingestion utility
├── embeddings.py                 Sentence-transformer embedding engine
├── generate_seed.py              Seed data generator
├── test_phase1.py                Structural project checks
├── test_rag_scoring.py           Score regression tests
├── docker-compose.yml             PostgreSQL and API services
├── Dockerfile                     API image definition
└── requirements.txt               Python dependencies
```

## 3. Requirements

- Docker and Docker Compose
- Python 3.11+ for the supplied Docker image
- At least 8 GB RAM recommended for the embedding model
- A Gemini API key for generated infringement reports

## 4. Configuration

Copy the template and set local secrets:

```bash
cp .env.template .env
```

Important variables:

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_HOST` | PostgreSQL hostname | `localhost` |
| `DATABASE_PORT` | PostgreSQL port outside Docker | `5433` |
| `DATABASE_USER` | Database user | `claimguard_user` |
| `DATABASE_PASSWORD` | Database password | empty |
| `DATABASE_NAME` | Database name | `claimguard_db` |
| `EMBEDDING_MODEL` | Sentence-transformer model | `all-MiniLM-L6-v2` |
| `EMBEDDING_VECTOR_DIMENSION` | pgvector dimension | `384` |
| `GEMINI_API_KEY` | Gemini credential | required for reports |
| `GEMINI_MODEL` | Gemini model name | `gemini-3.5-flash-lite` |
| `LLM_MAX_OUTPUT_TOKENS` | Report output limit | `4096` |

Never commit `.env`, database passwords, or API keys.

## 5. Start with Docker Compose

Build and start PostgreSQL plus the API:

```bash
docker compose up -d --build
```

The API is available at:

- Dashboard: <http://localhost:8000/app/>
- Swagger UI: <http://localhost:8000/docs>
- Health endpoint: <http://localhost:8000/api/v1/health>

Check service state:

```bash
docker compose ps
```

View API logs:

```bash
docker compose logs -f app
```

Restart after code changes:

```bash
docker compose up -d --build app
```

Stop services without deleting the database volume:

```bash
docker compose down
```

To remove the database volume as well, use `docker compose down -v`. This deletes
local PostgreSQL data and should only be done when a clean database is intended.

## 6. Database and Seed Data

On startup, the application:

1. Enables the PostgreSQL `vector` extension.
2. Creates the `patents` table if it does not exist.
3. Loads `data/Patents_data_withclaims.csv` only when the table is empty.
4. Generates normalized embeddings for the seed records.

The configured dataset contains claim-bearing patent records and is suitable for
local evaluation, not production legal analysis.

If the database already contains records, changing the seed JSON does not automatically
replace them. Re-import or clear the database intentionally when refreshing test data.

## 7. Importing Patent CSV Data

Import a CSV containing at least:

```text
publication_number,title,abstract
```

Optional claim columns are supported:

- `claims`
- `patent_claims`
- `claim`

Claims may be represented as:

- JSON list: `["claim one", "claim two"]`
- Newline-separated text
- `||`-separated text

Run the importer from the repository root:

```bash
docker compose exec app python scripts/import_patent_csv.py \
  --input data/Patents_data_withclaims.csv
```

Records without claims remain searchable through title/abstract evidence. They cannot
support an element-by-element claim comparison until claim text is imported.

## 8. Analyze a Draft

### API request

```bash
curl -s -X POST 'http://localhost:8000/api/v1/analyze?top_k=6' \
  -H 'Content-Type: application/json' \
  -d '{
    "user_draft": "A method compresses data stored in a tree structure by leaving root-child node data uncompressed, compressing leaf-child node data, and querying the structure sequentially from the root through its child nodes."
  }' | jq
```

The draft must contain at least 20 characters. `top_k` accepts values from 1 through 20.

### Response fields

| Field | Description |
|---|---|
| `retrieval_method` | `semantic` or `keyword_fallback` |
| `matching_patents` | Ranked patent candidates |
| `cosine_similarity` | Semantic discovery signal |
| `claim_overlap_score` | Evidence score used for ranking and calibration |
| `feature_coverage` | Shared title/abstract technical-term coverage |
| `evidence_type` | `claim` or `title_abstract` |
| `risk_scoring.model` | `claim_overlap_v2` or `technical_overlap_v2` |
| `llm_infringement_report` | Structured or raw grounded report |

For abstract-only records, `claim_overlap_score` is a technical-overlap score and
should be interpreted together with `evidence_type: "title_abstract"`.

## 9. Risk Scoring

### Claim-bearing records

Claim-bearing candidates are scored using:

- Claim-level lexical feature coverage
- Claim-level embedding similarity
- Number and strength of matched claim candidates
- Patent-level semantic retrieval signal

The result is bounded from 0 to 100 and calibrated independently of the LLM's
reported score.

### Abstract-only records

For records without claims, the fallback score is:

```text
technical evidence =
    55% semantic discovery signal
  + 35% title/abstract feature coverage
  + 10% bonus when feature coverage is meaningful
```

The fallback is capped below the maximum legal-risk range and is labeled technical
evidence. It is not proof of claim overlap.

### Risk bands

| Score | Label | Interpretation |
|---:|---|---|
| 0–39 | LOW | Weak or broad technical similarity |
| 40–69 | MEDIUM | Meaningful similarity with uncertainty or missing evidence |
| 70–100 | HIGH | Strong supported preliminary overlap; requires claim evidence for a legal interpretation |

These bands are screening thresholds, not legal conclusions.

## 10. Recommended Test Cases

Use the following drafts to check that scores vary with evidence:

### Direct tree-compression match

```text
A method compresses data stored in a tree structure by leaving root-child node data uncompressed, compressing leaf-child node data, and querying the structure sequentially from the root through its child nodes.
```

Expected: highest technical score for the tree-compression patent.

### Partial match

```text
A hierarchical storage system compresses leaf nodes of a tree while preserving metadata in parent and root nodes without compression.
```

Expected: lower than the direct match because sequential root-to-child querying is missing.

### Broad related concept

```text
A database stores objects in a hierarchical tree and traverses parent and child nodes to retrieve records efficiently.
```

Expected: moderate or low score; traversal alone should not be treated as the specific compression arrangement.

### Unrelated cryptography example

```text
A post-quantum digital signature generates lattice-based keys, applies Gaussian noise, and uses rejection sampling to produce compact signatures.
```

Expected: low score for the tree-compression patent.

## 11. Testing

Run the structural checks:

```bash
python test_phase1.py
```

Run the scoring tests when pytest is installed:

```bash
python -m pytest -q test_rag_scoring.py
```

Basic syntax validation:

```bash
python -m compileall -q app scripts embeddings.py
```

The scoring tests verify that:

- Direct claim/feature matches outrank unrelated drafts.
- The LLM cannot inflate the independently calibrated score.
- Abstract-only scores vary with title/abstract feature overlap.
- Claim and abstract-only scoring models remain distinguishable.

## 12. Troubleshooting

### The UI still shows a fixed score

Rebuild the API image so the container includes current source code:

```bash
docker compose up -d --build app
docker compose ps
curl http://localhost:8000/api/v1/health
```

Refresh the browser with a hard reload after the container is healthy.

### The report says claims are unavailable

This is expected for CSV records imported without a claim column. Add claims using
one of the supported formats and re-import the record.

### Database connection failures

```bash
docker compose ps
docker compose logs --tail=100 postgres
docker compose logs --tail=100 app
```

The API uses `postgres:5432` inside Compose and `localhost:5433` from the host.

### Gemini report generation fails

Check that `.env` contains a valid `GEMINI_API_KEY`, then rebuild/restart the app:

```bash
docker compose up -d --build app
docker compose logs --tail=100 app
```

## 13. Production Considerations

Before production use:

- Replace synthetic seed data with verified patent records and claims.
- Add authentication, authorization, audit logging, and rate limiting.
- Add a durable evaluation set with human-reviewed labels.
- Store model and scoring versions with every analysis.
- Add claim parsing and jurisdiction-aware legal review workflows.
- Avoid presenting any score as a probability of infringement.
