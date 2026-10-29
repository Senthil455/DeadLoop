# syntax=docker/dockerfile:1.7

FROM node:22-alpine AS frontend-build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEADLOOP_FRONTEND_DIST=/app/frontend/dist
WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend-build /src/frontend/dist /app/frontend/dist

RUN useradd --create-home --uid 10001 deadloop \
    && mkdir -p /app/backend/data \
    && chown -R deadloop:deadloop /app
USER deadloop

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3).read()"

# Migrations are explicit. Automatic schema creation is disabled in production.
CMD ["sh", "-c", "python -m alembic -c alembic.ini upgrade head && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"]
