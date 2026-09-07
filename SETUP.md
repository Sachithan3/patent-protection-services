# ClaimGuard AI Phase 1 - Setup & Deployment Guide

## Project Overview
ClaimGuard AI is an autonomous IP discovery and patent infringement detection engine. Phase 1 establishes the core infrastructure: database, embedding engine, and seed data generation.

---

## Part 1: Directory Structure

```
cloudproj/
├── app/
│   ├── __init__.py
│   ├── core/
│   │   └── __init__.py
│   ├── models/
│   │   └── __init__.py
│   └── api/
│       └── __init__.py
├── data/
│   └── seed_patents.json          (generated)
├── logs/
├── .env                            (environment variables)
├── .env.template                   (template reference)
├── requirements.txt                (Python dependencies)
├── generate_seed.py               (seed data generator)
├── embeddings.py                  (vector embedding engine)
└── SETUP.md                       (this file)
```

---

## Part 2: Installation & Setup

### Step 1: Install Python Dependencies

```bash
pip install -r requirements.txt
```

**Expected output:**
```
Successfully installed fastapi==0.109.0 uvicorn==0.27.0 ...
```

### Step 2: Launch PostgreSQL Container with pgvector

Run the following Docker command to start the pgvector-enabled PostgreSQL database:

```bash
docker run \
  --name claimguard-pgvector \
  -e POSTGRES_USER=claimguard_user \
  -e POSTGRES_PASSWORD=claimguard_secure_password_123 \
  -e POSTGRES_DB=claimguard_db \
  -p 5432:5432 \
  -v pgvector_data:/var/lib/postgresql/data \
  -d \
  ankane/pgvector:latest
```

**Verify the container is running:**
```bash
docker ps -a | grep claimguard-pgvector
```

**Expected output:**
```
claimguard-pgvector   ankane/pgvector:latest   Up X seconds   0.0.0.0:5432->5432/tcp
```

### Step 3: Verify Database Connectivity

Test the PostgreSQL connection:

```bash
psql -h localhost -p 5432 -U claimguard_user -d claimguard_db -c "SELECT version();"
```

When prompted for password, enter: `claimguard_secure_password_123`

**Expected output:**
```
PostgreSQL X.X on ... (Debian ...)
```

---

## Part 3: Generate Seed Data

Generate the synthetic patent dataset:

```bash
python generate_seed.py
```

**Expected output:**
```
======================================================================
✓ Seed data generated successfully at: data/seed_patents.json
✓ Total patents: 5
✓ File size: XXXX bytes

Patents generated:
  - US-2023-001456: Autonomous Vehicle Path Planning Using Quantum-E...
  - US-2023-008934: Post-Quantum Cryptographic Signature Scheme Using...
  - US-2023-015678: Smart Grid Demand Response System Using Federated...
  - US-2023-022401: Real-Time 3D Object Detection Using Sparse Convo...
  - US-2023-031847: Hierarchical Vector Database with Approximate Nea...
```

Verify the seed data file:

```bash
wc -l data/seed_patents.json && head -20 data/seed_patents.json
```

---

## Part 4: Test Vector Embedding Engine

Initialize and test the embedding engine:

```bash
python embeddings.py
```

**Expected output:**
```
======================================================================
ClaimGuard AI - Vector Embedding Engine Test
======================================================================

✓ Model loaded: all-MiniLM-L6-v2
✓ Vector dimension: 384

[TEST 1] Single Text Embedding
  Input: Autonomous vehicle path planning using reinforcement learning
  Output dimension: 384
  First 5 values: [... values ...]
  L2 norm: 1.000000

[TEST 2] Batch Text Embedding
  Input texts: 3
  Output vectors: 3
  Dimension per vector: 384
  Vector 0 L2 norm: 1.000000
  Vector 1 L2 norm: 1.000000
  Vector 2 L2 norm: 1.000000

[TEST 3] Similarity Analysis
  Similarity (patent vs. driving): X.XXXX
  Similarity (driving vs. quantum): X.XXXX

======================================================================
✓ All tests passed successfully!
======================================================================
```

**Key verification points:**
- Vector dimension = 384 ✓
- All L2 norms = 1.0 (normalized) ✓
- Similarity values in range [-1, 1] ✓

---

## Part 5: Environment Configuration

The `.env` file contains all configuration. Key variables:

| Variable | Value | Purpose |
|----------|-------|---------|
| `DATABASE_HOST` | localhost | PostgreSQL connection |
| `DATABASE_PORT` | 5432 | pgvector port |
| `DATABASE_USER` | claimguard_user | DB credentials |
| `DATABASE_PASSWORD` | claimguard_secure_password_123 | DB password |
| `DATABASE_NAME` | claimguard_db | Database name |
| `EMBEDDING_MODEL` | all-MiniLM-L6-v2 | Sentence-transformer model |
| `EMBEDDING_VECTOR_DIMENSION` | 384 | Vector output dimension |
| `API_PORT` | 8000 | FastAPI server port |

---

## Part 6: Troubleshooting

### Database Connection Error
```
psycopg2.OperationalError: could not connect to server
```
**Solution:** Ensure Docker container is running:
```bash
docker start claimguard-pgvector
```

### Model Download Timeout
The `all-MiniLM-L6-v2` model (133MB) downloads on first run. If you see timeout errors:
```bash
pip install --upgrade sentence-transformers
python embeddings.py  # Retry
```

### pgvector Extension Not Available
If you get "pgvector not installed" error:
```bash
docker exec claimguard-pgvector psql -U claimguard_user -d claimguard_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### Python Version Issue
Ensure Python 3.8+:
```bash
python --version
```

---

## Part 7: File Manifests

### requirements.txt Contents
- **FastAPI & Uvicorn**: Web framework and server
- **Pydantic**: Data validation and settings management
- **python-dotenv**: Environment variable loading
- **sentence-transformers**: Embedding model
- **torch**: Deep learning backend
- **SQLAlchemy**: ORM for database operations
- **psycopg2-binary**: PostgreSQL adapter
- **pgvector**: Vector database extension
- **numpy, scipy**: Numerical computing

### generate_seed.py Contents
- `SeedDataGenerator` class with 5 production-grade patents
- Patent categories: Autonomous Systems, Cryptography, Smart Grid, Computer Vision, Vector Databases
- Each patent includes: `patent_id`, `title`, `abstract`, `claims[]`, `category`
- JSON export with metadata

### embeddings.py Contents
- `EmbeddingEngine` class using `sentence-transformers`
- `embed_text(text)`: Single text to 384-dim vector
- `embed_batch(texts)`: Batch processing with normalization
- L2-normalized vectors for similarity searches
- Full test suite with 3 validation tests

---

## Quick Reference Commands

```bash
# Full setup from scratch
pip install -r requirements.txt
docker run --name claimguard-pgvector -e POSTGRES_USER=claimguard_user \
  -e POSTGRES_PASSWORD=claimguard_secure_password_123 \
  -e POSTGRES_DB=claimguard_db -p 5432:5432 -d ankane/pgvector:latest
python generate_seed.py
python embeddings.py

# Daily startup
docker start claimguard-pgvector
python embeddings.py  # Verify embeddings

# Cleanup
docker stop claimguard-pgvector
docker rm claimguard-pgvector
```

---

## Phase 1 Completion Checklist

- [x] Directory structure created
- [x] requirements.txt with all dependencies
- [x] .env configuration files
- [x] PostgreSQL pgvector container ready
- [x] Seed data generator (5 realistic patents)
- [x] Vector embedding engine (384-dim normalized)
- [x] Test suites passing
- [x] Documentation complete

**Status: ✓ Phase 1 Ready for Development**

Next Phase (Phase 2): Database schema, FastAPI endpoints, patent ingestion pipeline.
