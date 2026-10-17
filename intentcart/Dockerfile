FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ARG VITE_AUTH_MODE=demo
ARG VITE_FIREBASE_API_KEY
ARG VITE_FIREBASE_AUTH_DOMAIN
ARG VITE_FIREBASE_PROJECT_ID
ARG VITE_FIREBASE_APP_ID
RUN npm run build

FROM python:3.12-slim AS backend
COPY --from=ghcr.io/astral-sh/uv:0.6.1 /uv /bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --extra cloud --no-install-project
COPY backend/app ./app
RUN uv sync --frozen --no-dev --extra cloud
COPY --from=frontend /build/dist /app/frontend/dist
RUN useradd --create-home appuser
RUN mkdir -p /app/backend/.data && chown appuser:appuser /app/backend/.data
USER appuser
ENV PATH="/app/backend/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
