# ── フロントエンドビルド ──────────────────────────────
FROM node:24-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build
# 成果物: /app/frontend/dist

# ── Python 依存関係 ───────────────────────────────────
FROM python:3.12-slim AS backend-builder
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app/backend
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY backend/pyproject.toml backend/uv.lock ./
# uv.lock と pyproject.toml がずれていたら、ここで失敗させる
RUN uv sync --locked --no-dev

# ── ランタイム ────────────────────────────────────────
FROM python:3.14-slim-trixie
WORKDIR /app
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data
COPY --from=backend-builder /opt/venv /opt/venv
COPY backend/ ./backend/
# Vite のビルド成果物。backend からは ../frontend/dist として参照する。
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist
RUN useradd --system --create-home --uid 10001 kazayomi && mkdir -p /data && chown kazayomi /data
USER kazayomi
VOLUME ["/data"]
EXPOSE 8080
WORKDIR /app/backend
# worker を増やすときは VALKEY_URL を必ず設定する（撮像トークンを worker 間で共有するため）
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120"]
