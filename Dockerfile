# One image: React build served by the FastAPI service; same image runs the seed/ingest Cloud Run Job.
FROM node:20-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN pip install fastapi "uvicorn[standard]" "psycopg[binary]" pydantic-settings google-genai
COPY backend/app ./backend/app
COPY migrations ./migrations
COPY fixtures ./fixtures
COPY --from=ui /ui/dist ./frontend/dist
WORKDIR /app/backend
# Cloud Run supplies $PORT. Non-root user.
RUN useradd -r -u 10001 lore && chown -R lore /app
USER lore
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
