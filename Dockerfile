# ClaimGuard AI - FastAPI Application Dockerfile
# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=20 \
    HF_HUB_DOWNLOAD_TIMEOUT=300

# Install system dependencies for sentence-transformers and pgvector
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Set work directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install the torch CPU wheel from a pre-downloaded local file. The PyTorch CDN
# download is huge (~196MB) and the connection drops mid-transfer; fetching it
# via curl with resume (outside Docker) keeps it reliable, and installing it
# first means the main pip pass sees torch as satisfied and never re-downloads it.
COPY wheels/ /tmp/wheels/
RUN pip install --no-deps /tmp/wheels/torch-*.whl

# Install Python dependencies. The cache mount keeps downloaded wheels around
# so a dropped connection does not force a full re-download on the next build.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout 300 --retries 20 -r requirements.txt

# Pre-download the embedding model so startup does not depend on the
# Hugging Face network at runtime and cold starts stay fast. Retry to survive
# transient network failures on slow connections.
ENV HF_HOME=/app/.hf-cache \
    SENTENCE_TRANSFORMERS_HOME=/app/.st-cache
RUN success=0; \
    for attempt in 1 2 3 4 5; do \
        if python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"; then success=1; break; fi; \
        echo "Model download attempt $attempt failed; retrying..."; \
        sleep 5; \
    done; \
    test "$success" = 1

# Copy application code
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY embeddings.py .
COPY generate_seed.py .
COPY demo_rag.py .
COPY .env.template .

# Create data and logs directories
RUN mkdir -p data logs && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]