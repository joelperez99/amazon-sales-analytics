# =============================================================================
# Amazon Sales Analytics — imagen de producción
# Construcción en dos etapas para que la imagen final no incluya compiladores.
# =============================================================================

# ---------- Etapa 1: dependencias -------------------------------------------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Herramientas necesarias solo para compilar ruedas (psycopg2, etc.).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt


# ---------- Etapa 2: imagen final -------------------------------------------
FROM python:3.11-slim

LABEL org.opencontainers.image.title="Amazon Sales Analytics" \
      org.opencontainers.image.description="Tablero de ventas y rentabilidad para Amazon Seller Central" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_ENV=production \
    TZ=America/Mexico_City

# Solo la biblioteca de PostgreSQL en tiempo de ejecución y curl para el healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# La aplicación corre como usuario sin privilegios.
RUN useradd --create-home --uid 1000 appuser

COPY --chown=appuser:appuser . .

# Carpetas de datos, cargas y registros con permisos de escritura.
RUN mkdir -p /app/data/uploads /app/data/demo /app/logs \
    && chown -R appuser:appuser /app/data /app/logs

USER appuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl --fail http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
