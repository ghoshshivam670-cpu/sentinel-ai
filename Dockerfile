FROM python:3.12-slim

# Prevent Python from writing .pyc files and ensure unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

WORKDIR /app

# Install minimal system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (optimal Docker layer caching)
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy application source
COPY sentinel/ ./sentinel/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY app_ui.py cli.py pytest.ini .env.example ./

# Create non-root user for hardened sandbox container execution
RUN useradd --create-home --shell /bin/bash sentinel \
    && chown -R sentinel:sentinel /app
USER sentinel

EXPOSE 8000 8501

# Default entrypoint runs FastAPI streaming server; override in docker-compose for UI/CLI
CMD ["uvicorn", "sentinel.server.app:app", "--host", "0.0.0.0", "--port", "8000"]
