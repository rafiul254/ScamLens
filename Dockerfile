# ---------------------------------------------------------------------------
# ScamLens — single image, two stages: build the PWA, then serve it + the API.
# The FastAPI app serves the built frontend, so one container gives you the whole
# product at http://localhost:8000 (the mobile app is the same origin as the API,
# which also means no CORS configuration is needed in production).
# ---------------------------------------------------------------------------

# ---------- stage 1: build the frontend ----------
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- stage 2: python runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ML_ARTIFACTS_DIR=/app/ml/artifacts \
    DB_PATH=/data/scamlens.db

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY ml/ ./ml/
COPY data/demo_samples.json ./data/demo_samples.json
COPY backend/app/data/scam_patterns.json ./backend/app/data/scam_patterns.json

# Trained artifacts (text_classifier.joblib, url_risk_model.joblib, metrics.json).
# They are produced by `make train`; without them the API still runs and reports
# "rules only" in /api/health instead of inventing scores.
COPY ml/artifacts/ ./ml/artifacts/

# Built PWA is served by FastAPI from here
COPY --from=web /web/dist ./frontend/dist
ENV FRONTEND_DIST=/app/frontend/dist

RUN useradd --create-home --uid 10001 scamlens \
 && mkdir -p /data && chown -R scamlens:scamlens /data /app
USER scamlens

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# One worker: the model is loaded once and the app is stateless besides SQLite.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "backend"]
