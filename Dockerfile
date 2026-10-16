# syntax=docker/dockerfile:1
# One image serves both the API and the built React app (same origin, no CORS).

# ---- 1. Build the frontend ------------------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. Python runtime ----------------------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/ ./
COPY --from=frontend /app/frontend/dist ./frontend_dist
# WhiteNoise serves pre-compressed files; generate .gz versions of the bundle once here.
RUN python -m whitenoise.compress frontend_dist

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
# The workload is I/O-bound (waiting on routing/weather APIs), so threads scale well,
# and a single process keeps the in-memory forecast/route cache shared by all requests.
CMD gunicorn config.wsgi:application \
    --bind 0.0.0.0:${PORT} \
    --workers ${WEB_CONCURRENCY:-1} \
    --threads ${GUNICORN_THREADS:-16} \
    --timeout 120 \
    --access-logfile -
