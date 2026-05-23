# ── Stage 1: Build frontend ─────────────────────────────────────────
FROM node:22-slim AS frontend-build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Runtime ───────────────────────────────────────────────
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnuma1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY graphify/graphify/ ./graphify/

COPY --from=frontend-build /src/frontend/dist ./frontend/dist

ENV ZOPEDIA_FRONTEND_DIR=/app/frontend/dist
ENV ZOPEDIA_WIKI_VAULT=/app/wiki_data
ENV ZOPEDIA_PORT=8000

RUN useradd --create-home --shell /bin/bash zopedia && chown -R zopedia:zopedia /app
USER zopedia

VOLUME ["/app/wiki_data"]

EXPOSE 8000
CMD ["python", "main.py"]
