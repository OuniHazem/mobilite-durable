# ============================================================
# Dockerfile — Pipeline Mobilité Durable
# Multi-stage : builder (deps) + runner (image finale légère)
# ============================================================

# ---- Stage 1 : builder ----
FROM python:3.11-slim AS builder

WORKDIR /build

# Dépendances système pour compiler certains packages C
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Isolation des dépendances dans un venv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


# ---- Stage 2 : runner ----
FROM python:3.11-slim AS runner

# Métadonnées
LABEL maintainer="data-team@mobilite-durable.fr"
LABEL description="Pipeline Mobilité Durable — Lille & Montpellier"
LABEL version="1.0.0"

# Dépendances runtime uniquement
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copier le venv depuis le builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Utilisateur non-root pour la sécurité
RUN useradd --create-home --shell /bin/bash pipeline
WORKDIR /app
RUN chown pipeline:pipeline /app

# Copier le code source
COPY --chown=pipeline:pipeline . .

USER pipeline

# Variables d'environnement par défaut (surchargées par docker-compose)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    ENV=production \
    HEALTH_PORT=8080 \
    LOG_LEVEL=INFO

# Health check Docker natif
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -sf http://localhost:${HEALTH_PORT}/health || exit 1

EXPOSE ${HEALTH_PORT}

CMD ["python", "main.py"]
