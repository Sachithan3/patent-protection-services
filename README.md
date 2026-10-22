# ClaimGuard AI

ClaimGuard AI is a FastAPI service for preliminary patent-overlap analysis. It
uses sentence-transformer embeddings, PostgreSQL with pgvector, claim-level
retrieval, and grounded Gemini report generation.

> **Important:** Results are technical screening signals for preliminary review.
> They are not a legal opinion, a probability of infringement, or a substitute
> for qualified patent counsel.

## Run on a new computer

The following instructions are the recommended local-development setup. They
assume Linux or macOS. Windows users can run the same commands in WSL, or use
the PowerShell activation command shown below.

### 1. Install prerequisites

Install:

- Git
- Python 3.11 or newer
- Docker Desktop or Docker Engine with the Docker CLI
- At least 8 GB RAM (the embedding model is downloaded and loaded at startup)
- A Google Gemini API key for generated analysis reports

Check that the tools are available:

```bash
git --version
python3 --version
docker --version
```

### 2. Clone the repository

```bash
git clone https://github.com/Sachithan3/patent-protection-services.git
cd patent-protection-services
```

Confirm that the patent dataset is present:

```bash
test -f data/Patents_data_withclaims.csv && echo "Dataset found"
```

### 3. Create a Python environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

### 4. Configure environment variables

Create a local environment file from the template:

```bash
cp .env.template .env
```

Open `.env` and set:

```dotenv
DATABASE_PASSWORD=choose_a_local_database_password
GEMINI_API_KEY=your_gemini_api_key
```

Keep `.env` local. Do not commit database passwords or API keys.

### 5. Start PostgreSQL with pgvector

Start the database container using the same password configured in `.env`:

```bash
docker run \
  --name claimguard-pgvector \
  -e POSTGRES_USER=claimguard_user \
  -e POSTGRES_PASSWORD=choose_a_local_database_password \
  -e POSTGRES_DB=claimguard_db \
  -p 5433:5432 \
  -v pgvector_data:/var/lib/postgresql/data \
  -d \
  ankane/pgvector:latest
```

Wait until PostgreSQL is ready:

```bash
until docker exec claimguard-pgvector pg_isready -U claimguard_user -d claimguard_db >/dev/null 2>&1; do
  sleep 2
done
echo "PostgreSQL is ready"
```

If the container already exists, start it instead:

```bash
docker start claimguard-pgvector
```

The application connects to `localhost:5433` using the database settings in
`.env`.

### 6. Start the API

From the repository root, with the virtual environment activated:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The first startup may take several minutes because it downloads the
`all-MiniLM-L6-v2` embedding model and indexes the CSV dataset. The application
automatically:

1. Enables the PostgreSQL `vector` extension.
2. Creates the required database tables.
3. Loads `data/Patents_data_withclaims.csv` when the database is empty.
4. Generates and stores embeddings for the imported patents.

Leave this terminal running while using the application.

### 7. Verify the installation

In a second terminal:

```bash
cd patent-protection-services
source .venv/bin/activate
curl http://localhost:8000/api/v1/health
```

Open these URLs in a browser:

- Dashboard: <http://localhost:8000/app/>
- Swagger API documentation: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/api/v1/health>

The health response should report `"status": "healthy"` after the database and
embedding model are ready.

## Try an analysis

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "user_draft": "An autonomous indoor drone uses LiDAR and event cameras to build a sparse 3D occupancy map and uses reinforcement learning for collision-free path planning on an edge FPGA."
  }'
```

The request must contain a technical draft with at least 20 characters. The
response includes retrieved patents, claim-overlap evidence, technical
differences, design-around suggestions, and a grounded Gemini report.

## Useful commands

Run the terminal RAG demo:

```bash
python demo_rag.py
```

Validate the embedding engine:

```bash
python embeddings.py
```

Stop the database without deleting its data:

```bash
docker stop claimguard-pgvector
```

Start it again later:

```bash
docker start claimguard-pgvector
```

Delete the local database and all indexed data:

```bash
docker rm -f claimguard-pgvector
docker volume rm pgvector_data
```

Only run the deletion commands when a clean database is intended.

## Configuration

The main settings are read from `.env`:

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_HOST` | PostgreSQL hostname | `localhost` |
| `DATABASE_PORT` | PostgreSQL port | `5433` |
| `DATABASE_USER` | PostgreSQL user | `claimguard_user` |
| `DATABASE_PASSWORD` | PostgreSQL password | required |
| `DATABASE_NAME` | PostgreSQL database | `claimguard_db` |
| `EMBEDDING_MODEL` | Sentence-transformer model | `all-MiniLM-L6-v2` |
| `EMBEDDING_VECTOR_DIMENSION` | pgvector dimension | `384` |
| `GEMINI_API_KEY` | Gemini credential | required for reports |
| `GEMINI_MODEL` | Gemini model | `gemini-3.5-flash-lite` |
| `GEMINI_TIMEOUT_SECONDS` | Per-report Gemini timeout (also bounds SDK retries) | `120` |
| `LLM_MAX_OUTPUT_TOKENS` | Maximum report size | `4096` |

## Troubleshooting

### `docker: command not found`

Install Docker Desktop or Docker Engine, then rerun `docker --version`.

### Database connection refused

Check the container and its logs:

```bash
docker ps
docker logs claimguard-pgvector
```

Confirm that `.env` uses `DATABASE_HOST=localhost`, `DATABASE_PORT=5433`,
`DATABASE_USER=claimguard_user`, `DATABASE_NAME=claimguard_db`, and the same
password used when the container was created.

### Container name already in use

If the existing container is the intended local database, run:

```bash
docker start claimguard-pgvector
```

To recreate it, first remove only that named container:

```bash
docker rm -f claimguard-pgvector
```

Then repeat the PostgreSQL startup command.

### Embedding model download is slow or times out

Ensure the computer has internet access and enough disk space, then retry:

```bash
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

### Gemini analysis is unavailable

Check that `GEMINI_API_KEY` is set in `.env`, restart Uvicorn, and verify that
the key has access to the configured `GEMINI_MODEL`.

### Analysis stays on “Searching” for a long time

Report generation waits on the Gemini API, which can take 20–60 seconds (longer
when the model is under high demand and the SDK retries a `503`). The web UI
shows elapsed progress and times out after 2.5 minutes; the API itself gives up
after `GEMINI_TIMEOUT_SECONDS` (default `120`). Lower that value for a shorter
wait, or check `docker compose logs app` for the per-stage timings
(`Embedding and retrieval`, `Claim reranking`, `Gemini report received`).

## Project structure

```text
.
├── app/                         FastAPI application and browser dashboard
├── data/Patents_data_withclaims.csv
├── embeddings.py                Embedding engine
├── demo_rag.py                  Terminal RAG demo
├── docker-compose.yml           Container configuration
├── Dockerfile                   API image definition
├── requirements.txt             Python dependencies
├── .env.template                Local configuration template
└── PROJECT_DOCUMENTATION.md     Detailed technical documentation
```

## License and attribution

ClaimGuard AI | LegalTech patent analysis engine

Built with FastAPI, sentence-transformers, PostgreSQL/pgvector, and Google
Gemini.
