FROM python:3.12-slim

# Metadados e variáveis de ambiente essenciais
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8765 \
    PORT=8765

WORKDIR /app

# Instala certificados SSL e curl para health check
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Cria usuário não-privilegiado (non-root)
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/false -m appuser

# Instala dependências do Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código da aplicação com ownership restrito
COPY --chown=appuser:appgroup src/ ./src/
COPY --chown=appuser:appgroup start_worker.py .
COPY --chown=appuser:appgroup package.json .

# Muda para o usuário sem privilégios
USER appuser

# Healthcheck interno do container
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8765/health || exit 1

EXPOSE 8765

CMD ["python", "start_worker.py"]
