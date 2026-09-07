# ClaimGuard AI Phase 1 - Deployment & Command Reference

## 🚀 Quick Deploy (Copy-Paste Ready)

### One-Line Full Setup
```bash
cd /path/to/cloudproj && \
python3 -m venv venv && \
source venv/bin/activate && \
pip install -r requirements.txt && \
docker run --name claimguard-pgvector \
  -e POSTGRES_USER=claimguard_user \
  -e POSTGRES_PASSWORD=claimguard_secure_password_123 \
  -e POSTGRES_DB=claimguard_db \
  -p 5432:5432 -d ankane/pgvector:latest && \
python3 generate_seed.py && \
python3 test_phase1.py
```

---

## 📋 Step-by-Step Deployment Commands

### Phase 1: Python Environment Setup

```bash
# Navigate to project directory
cd /path/to/cloudproj

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate           # On Linux/macOS
# OR
.\venv\Scripts\activate            # On Windows

# Install all dependencies
pip install -r requirements.txt

# Verify installation
pip list | grep -E "fastapi|sentence-transformers|sqlalchemy|pgvector"
```

**Expected Output:**
```
fastapi              0.109.0
sentence-transformers 2.2.2
sqlalchemy          2.0.25
pgvector            0.2.1
...
```

---

### Phase 2: PostgreSQL + pgvector Container Launch

#### Option A: Docker (Recommended)

```bash
# Launch pgvector container
docker run \
  --name claimguard-pgvector \
  -e POSTGRES_USER=claimguard_user \
  -e POSTGRES_PASSWORD=claimguard_secure_password_123 \
  -e POSTGRES_DB=claimguard_db \
  -p 5432:5432 \
  -v pgvector_data:/var/lib/postgresql/data \
  -d \
  ankane/pgvector:latest

# Verify container is running
docker ps | grep claimguard-pgvector

# View logs
docker logs claimguard-pgvector
```

**Expected Output:**
```
claimguard-pgvector   ankane/pgvector:latest   Up 2 seconds   0.0.0.0:5432->5432/tcp
```

#### Option B: Test Database Connection

```bash
# Install psycopg2-binary if not already installed
pip install psycopg2-binary

# Test connection via Python
python3 -c "
import psycopg2
try:
    conn = psycopg2.connect(
        host='localhost',
        port=5432,
        user='claimguard_user',
        password='claimguard_secure_password_123',
        database='claimguard_db'
    )
    print('✓ PostgreSQL Connection Successful!')
    conn.close()
except Exception as e:
    print(f'✗ Connection Failed: {e}')
"
```

#### Option C: Enable pgvector Extension

```bash
# Connect to database and enable extension
docker exec -it claimguard-pgvector psql \
  -U claimguard_user \
  -d claimguard_db \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Verify extension
docker exec -it claimguard-pgvector psql \
  -U claimguard_user \
  -d claimguard_db \
  -c "SELECT version();"
```

---

### Phase 3: Seed Data Generation

```bash
# Activate virtual environment (if not already active)
source venv/bin/activate

# Generate seed patents
python3 generate_seed.py

# Verify seed data file
ls -lh data/seed_patents.json

# View seed data structure
head -100 data/seed_patents.json

# Count patents
python3 -c "import json; data=json.load(open('data/seed_patents.json')); print(f'Total Patents: {data[\"total_patents\"]}')"
```

**Expected Output:**
```
✓ Seed data generated successfully at: data/seed_patents.json
✓ Total patents: 5
✓ File size: 5296 bytes
```

---

### Phase 4: Embedding Engine Validation

```bash
# Activate virtual environment
source venv/bin/activate

# Download and cache embedding model
python3 -c "
from sentence_transformers import SentenceTransformer
print('Downloading all-MiniLM-L6-v2 model...')
model = SentenceTransformer('all-MiniLM-L6-v2')
print(f'✓ Model loaded. Dimension: {model.get_sentence_embedding_dimension()}')
"

# Test embedding engine
python3 embeddings.py
```

**Expected Output:**
```
======================================================================
ClaimGuard AI - Vector Embedding Engine Test
======================================================================

✓ Model loaded: all-MiniLM-L6-v2
✓ Vector dimension: 384

[TEST 1] Single Text Embedding
  Input: Autonomous vehicle path planning using reinforcement learning
  Output dimension: 384
  First 5 values: [...]
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

---

### Phase 5: Integration Testing

```bash
# Run comprehensive test suite
python3 test_phase1.py
```

**Expected Output:**
```
██████████████████████████████████████████████████████████████████████
█  ClaimGuard AI Phase 1 - Integration Test Suite
██████████████████████████████████████████████████████████████████████

[All 5 tests should show ✓ PASS]

  Result: 5/5 tests passed

✓ Phase 1 Infrastructure Ready for Deployment!
```

---

## 🔧 Container Management Commands

### Check Container Status
```bash
docker ps -a | grep claimguard
docker inspect claimguard-pgvector
```

### View Container Logs
```bash
docker logs claimguard-pgvector
docker logs claimguard-pgvector -f          # Follow logs in real-time
docker logs claimguard-pgvector --tail 50   # Last 50 lines
```

### Restart Container
```bash
docker stop claimguard-pgvector
docker start claimguard-pgvector
```

### Execute Commands in Container
```bash
# Connect to PostgreSQL CLI
docker exec -it claimguard-pgvector psql -U claimguard_user -d claimguard_db

# Execute SQL command directly
docker exec -it claimguard-pgvector psql \
  -U claimguard_user \
  -d claimguard_db \
  -c "SELECT count(*) FROM pg_extension WHERE extname='vector';"
```

### Full Container Cleanup
```bash
docker stop claimguard-pgvector
docker rm claimguard-pgvector
docker volume rm pgvector_data
```

---

## 🐛 Troubleshooting Commands

### Database Connection Issues
```bash
# Check if port 5432 is in use
lsof -i :5432        # Linux/macOS
netstat -ano | grep 5432  # Windows

# Restart container
docker restart claimguard-pgvector

# Verify connectivity
python3 -c "
import socket
try:
    socket.create_connection(('localhost', 5432), timeout=5)
    print('✓ Port 5432 is accessible')
except:
    print('✗ Port 5432 is not accessible')
"
```

### Model Download Issues
```bash
# Clear transformers cache
rm -rf ~/.cache/huggingface/

# Retry with verbose output
python3 -c "
import logging
logging.basicConfig(level=logging.DEBUG)
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('all-MiniLM-L6-v2')
print(f'✓ Model loaded. Dimension: {model.get_sentence_embedding_dimension()}')
"
```

### Python/Dependency Issues
```bash
# Verify Python version
python3 --version    # Should be 3.8+

# Check virtual environment
which python3         # Should show venv path

# Reinstall requirements
pip install --upgrade --force-reinstall -r requirements.txt

# Check for conflicting packages
pip check
```

### Memory/Performance Issues
```bash
# Monitor Docker container memory usage
docker stats claimguard-pgvector

# If out of memory, increase Docker resource limits
docker update --memory 4g claimguard-pgvector
```

---

## 📊 Verification Checklist

Run this command to verify all components:

```bash
#!/bin/bash
echo "═══════════════════════════════════════════"
echo "ClaimGuard AI Phase 1 - Verification"
echo "═══════════════════════════════════════════"

echo -n "✓ Python version: "
python3 --version

echo -n "✓ Virtual environment: "
which python3 | grep -q venv && echo "Active" || echo "Inactive"

echo -n "✓ PostgreSQL container: "
docker ps | grep -q claimguard-pgvector && echo "Running" || echo "Not running"

echo -n "✓ Port 5432: "
lsof -i :5432 >/dev/null 2>&1 && echo "Listening" || echo "Not listening"

echo -n "✓ Seed data file: "
[ -f data/seed_patents.json ] && echo "Present" || echo "Missing"

echo -n "✓ FastAPI dependency: "
pip show fastapi >/dev/null 2>&1 && echo "Installed" || echo "Missing"

echo -n "✓ sentence-transformers: "
pip show sentence-transformers >/dev/null 2>&1 && echo "Installed" || echo "Missing"

echo "═══════════════════════════════════════════"
```

Save as `verify.sh`, then run:
```bash
chmod +x verify.sh
./verify.sh
```

---

## 🚀 Launch Next Phase (Phase 2)

When Phase 1 is complete, Phase 2 includes:

```bash
# Phase 2 deliverables (not yet implemented)
# - Database schema creation
# - FastAPI endpoints (/patents/upload, /patents/search)
# - Patent vector indexing
# - Similarity search implementation
# - Swagger API documentation
```

Start Phase 2 by:
```bash
# Create Phase 2 branch
git checkout -b feature/phase2-api-endpoints

# Create new modules
mkdir -p app/services app/schemas
touch app/services/__init__.py app/schemas/__init__.py
touch app/main.py app/database.py

# Update requirements.txt with Phase 2 dependencies
# Implement database models and API endpoints
```

---

## 📞 Support & Resources

| Issue | Command |
|-------|---------|
| Docker issues | `docker ps -a && docker logs claimguard-pgvector` |
| PostgreSQL connection | `psql -h localhost -U claimguard_user -d claimguard_db` |
| Model download | `python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"` |
| Test all systems | `python3 test_phase1.py` |
| View seed data | `python3 generate_seed.py` |

---

## 📝 Environment Variables Reference

Create `.env.local` for custom settings:

```bash
# Database
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_USER=claimguard_user
DATABASE_PASSWORD=claimguard_secure_password_123
DATABASE_NAME=claimguard_db

# Application
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=DEBUG

# Embeddings (keep defaults)
EMBEDDING_MODEL=all-MiniLM-L6-v2
EMBEDDING_BATCH_SIZE=32
EMBEDDING_VECTOR_DIMENSION=384

# FastAPI
API_HOST=0.0.0.0
API_PORT=8000
API_RELOAD=true

# Paths
SEED_DATA_PATH=data/seed_patents.json
```

Load custom config:
```bash
export $(cat .env.local | xargs)
```

---

## ✅ Phase 1 Complete Checklist

- [x] Project directory structure
- [x] requirements.txt with all dependencies
- [x] .env configuration files
- [x] Docker pgvector setup commands
- [x] Seed data generator (5 patents)
- [x] Vector embedding engine (384-dim)
- [x] Test suite (5/5 passing)
- [x] Documentation & deployment guide
- [x] Verification commands

**Status: READY FOR PRODUCTION DEPLOYMENT** ✓

---

Last Updated: Phase 1 Complete | Ready for Phase 2 Development
