# ClaimGuard AI - Autonomous IP Discovery & Patent Infringement Engine

**Phase 2: Retrieval-Augmented Patent Infringement Analysis**

## 🎯 Project Objective

ClaimGuard AI is a LegalTech platform for preliminary patent infringement analysis. The current implementation combines semantic embeddings, PostgreSQL/pgvector cosine retrieval, and grounded Gemini or Mistral report generation.

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                  FastAPI Application                     │
├─────────────────────────────────────────────────────────┤
│  Draft → EmbeddingEngine → pgvector cosine retrieval     │
│  Retrieved claims → strict RAG prompt → Gemini/Mistral    │
│  PostgreSQL Patent Store ← automatic JSON seed loading    │
└─────────────────────────────────────────────────────────┘
```

## 🛠️ Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| **Backend Framework** | FastAPI | 0.109.0 |
| **Web Server** | Uvicorn | 0.27.0 |
| **Embeddings** | sentence-transformers | 2.2.2 |
| **Database** | PostgreSQL + pgvector | Latest |
| **ORM** | SQLAlchemy | 2.0.25 |
| **ML Backend** | PyTorch | 2.2.0 |
| **Config Management** | Pydantic | 2.5.0 |
| **LLM** | Google Gemini / Mistral | `gemini-3.6-flash` / `mistral-small-latest` |

## 📦 Installation

### Prerequisites
- Python 3.8+
- Docker & Docker Compose
- 8GB+ RAM (for embedding model)
- 2GB+ free disk space

### 1. Clone & Setup Environment

```bash
cd /path/to/cloudproj
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Launch PostgreSQL with pgvector

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

**Verify:**
```bash
docker ps | grep claimguard-pgvector
```

### 3. Generate Seed Data

```bash
python generate_seed.py
```

**Output:** `data/seed_patents.json` with 5 realistic patents

### 4. Start the RAG API

Copy `.env.template` to `.env`, then set `GEMINI_API_KEY` for Gemini or `MISTRAL_API_KEY` for fallback:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The application startup creates the pgvector table and automatically embeds the five JSON seed patents when the database is empty.

Open Swagger UI at [http://localhost:8000/docs](http://localhost:8000/docs).

### 5. Analyze a Draft

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{"user_draft":"An autonomous indoor drone uses LiDAR and event cameras to build a sparse 3D occupancy map and uses reinforcement learning for collision-free path planning on an edge FPGA."}'
```

### 6. Run the RAG Terminal Demo

```bash
python demo_rag.py
```

### 7. Validate Embedding Engine

```bash
python embeddings.py
```

**Verification Points:**
- ✓ Vector dimension: 384
- ✓ L2 norm: 1.0 (normalized)
- ✓ Batch processing: OK
- ✓ Similarity computation: OK

## 📋 File Structure

```
cloudproj/
├── app/                          # FastAPI application package
│   ├── __init__.py
│   ├── core/                     # Config, database, prompts
│   ├── models/                   # SQLAlchemy + pgvector models
│   ├── services/                 # Retrieval and LLM orchestration
│   └── api/                      # FastAPI route handlers
├── data/
│   └── seed_patents.json         # Generated patent dataset
├── logs/                         # Application logs
├── .env                          # Environment configuration
├── .env.template                 # Configuration template
├── .gitignore                    # Git ignore rules
├── requirements.txt              # Python dependencies
├── generate_seed.py              # Seed data generator script
├── embeddings.py                 # Vector embedding engine
├── demo_rag.py                    # End-to-end terminal demonstration
├── README.md                     # This file
└── SETUP.md                      # Detailed setup guide
```

## 🚀 Quick Start

```bash
# Full setup (one-liner with proper order)
pip install -r requirements.txt && \
docker run --name claimguard-pgvector \
  -e POSTGRES_USER=claimguard_user \
  -e POSTGRES_PASSWORD=claimguard_secure_password_123 \
  -e POSTGRES_DB=claimguard_db \
  -p 5432:5432 -d ankane/pgvector:latest && \
python generate_seed.py && \
python embeddings.py
```

## 📊 Seed Data Contents

### 5 Production-Grade Patents

1. **US-2023-001456** | Autonomous Vehicle Path Planning
   - Category: Autonomous Systems
   - 3 Claims | Abstract + Implementation Details

2. **US-2023-008934** | Post-Quantum Cryptographic Signature Scheme
   - Category: Cryptography
   - 3 Claims | Lattice-based security

3. **US-2023-015678** | Smart Grid Demand Response System
   - Category: Smart Grid
   - 3 Claims | Federated learning edge computing

4. **US-2023-022401** | Real-Time 3D Object Detection
   - Category: Computer Vision
   - 3 Claims | Event cameras + sparse CNNs

5. **US-2023-031847** | Hierarchical Vector Database
   - Category: Vector Databases
   - 3 Claims | Billion-scale ANNS queries

### Data Structure
```json
{
  "patent_id": "US-2023-001456",
  "title": "...",
  "abstract": "...",
  "claims": ["claim1", "claim2", ...],
  "category": "Autonomous Systems"
}
```

## 🔬 Vector Embedding Engine

### EmbeddingEngine API

```python
from embeddings import EmbeddingEngine

# Initialize
engine = EmbeddingEngine(model_name="all-MiniLM-L6-v2")

# Single embedding
vector = engine.embed_text("Autonomous vehicle patent claims")
# Returns: List[float] of length 384

# Batch embedding
vectors = engine.embed_batch([
    "Patent text 1",
    "Patent text 2",
    "Patent text 3"
])
# Returns: List[List[float]]

# Get vector dimension
dim = engine.get_vector_dimension()
# Returns: 384
```

### Properties
- **Model:** sentence-transformers/all-MiniLM-L6-v2
- **Vector Dimension:** 384
- **Normalization:** L2 (unit length)
- **Processing:** Batch-optimized
- **Latency:** ~10-50ms per 32-text batch (CPU)

## 🗄️ Database Configuration

### PostgreSQL Connection
```
Host: localhost
Port: 5432
User: claimguard_user
Password: claimguard_secure_password_123
Database: claimguard_db
```

### pgvector Extension
Automatically available in `ankane/pgvector` image. Enable on first use:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## ✅ Validation Checklist

- [x] Python dependencies installed
- [x] PostgreSQL container running on port 5432
- [x] Seed data generated (5 patents)
- [x] Embedding engine initialized
- [x] Vector dimension verified (384)
- [x] Normalization verified (L2 norm = 1.0)
- [x] Batch processing validated
- [x] Similarity computation working

## 🔌 API Endpoints

### `GET /api/v1/health`

Checks PostgreSQL connectivity and verifies that the embedding model produces 384-dimensional vectors.

### `POST /api/v1/analyze`

Request:

```json
{
  "user_draft": "Technical product or implementation description",
  "top_k": 5
}
```

The response contains:

- Retrieved patents ordered by pgvector cosine distance
- Cosine similarity scores
- Patent claims supplied to the LLM
- A structured JSON infringement report

The report is constrained to retrieved claims and includes risk rating, overlapping patent claims, technical differences, design-around recommendations, limitations, and a final preliminary verdict summary.

## 🧠 RAG Execution Flow

1. Validate the draft with Pydantic.
2. Encode the draft using `all-MiniLM-L6-v2`.
3. Query PostgreSQL using pgvector `<=>` cosine distance.
4. Format only retrieved patent metadata and numbered claims as context.
5. Send the grounded prompt to Gemini `gemini-3.6-flash`.
6. Fall back to Mistral if Gemini is unavailable.
7. Return retrieval scores and the structured report through FastAPI.

## 📚 Next Steps (Phase 3)

- [ ] Patent ingestion endpoints for non-synthetic data
- [ ] Claim-level embeddings and hybrid lexical retrieval
- [ ] Authentication and audit logging
- [ ] Human legal-review workflow
- [ ] Evaluation dataset and retrieval/grounding metrics

## 🔧 Troubleshooting

### Database Connection Refused
```bash
# Check if container is running
docker ps | grep claimguard-pgvector

# Restart container if needed
docker start claimguard-pgvector
```

### Model Download Timeout
```bash
# Retry with explicit cache
python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('all-MiniLM-L6-v2')"
```

### Permission Denied on Logs Directory
```bash
chmod 755 logs/
```

## 📖 Documentation

- **[SETUP.md](SETUP.md)** - Detailed installation & Docker commands
- **[embeddings.py](embeddings.py)** - Embedding engine with inline documentation
- **[generate_seed.py](generate_seed.py)** - Seed data generator with examples

## 📝 License & Attribution

ClaimGuard AI Phase 1 | LegalTech Patent Analysis Engine
Built with FastAPI, sentence-transformers, and pgvector

## 🤝 Support

For issues or questions:
1. Check SETUP.md troubleshooting section
2. Review inline code documentation
3. Verify Docker container health
4. Ensure Python 3.8+ compatibility

---

**Status:** ✅ Phase 1 Complete & Ready for Phase 2 Development
