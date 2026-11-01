# ── フロントエンドビルド ──────────────────────────────
FROM node:24-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
# kazayomi 自身のライセンス。ビルドで dist/licenses/ に入れる
COPY LICENSE /app/LICENSE
RUN npm run build
# 成果物: /app/frontend/dist

# ── Python 依存関係 ───────────────────────────────────
# ランタイムと同じイメージにする。Python のバージョンがずれると、/opt/venv に入れた依存関係が
# 見つからずに起動できない（No module named 'gunicorn' など）
FROM python:3.14-slim-trixie AS backend-builder
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app/backend
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY backend/pyproject.toml backend/uv.lock ./
# uv.lock と pyproject.toml がずれていたら、ここで失敗させる
RUN uv sync --locked --no-dev
# 入れた依存関係のライセンス文を集める。画面のメニューから開けるよう、dist/licenses/ に置く
COPY backend/scripts/third_party_licenses.py ./scripts/
RUN /opt/venv/bin/python scripts/third_party_licenses.py /licenses/backend.txt

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
COPY --from=backend-builder /licenses/backend.txt ./frontend/dist/licenses/backend.txt
RUN useradd --system --create-home --uid 10001 kazayomi && mkdir -p /data && chown kazayomi /data
USER kazayomi
VOLUME ["/data"]
EXPOSE 8080
WORKDIR /app/backend
# worker を増やすときは VALKEY_URL を必ず設定する（撮像トークンを worker 間で共有するため）
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120"]
