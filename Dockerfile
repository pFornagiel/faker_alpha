# ---- web UI (React + shadcn/ui) -------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- API + analysis engine ---------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 FTF_LLM=auto
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY ftf ./ftf
COPY tools ./tools
COPY README.md ./
COPY docs ./docs
COPY research ./research
# models (~460 MB) baked into the image so the demo works offline
RUN python tools/download_models.py
# optional: headless browser for live URL capture
ARG WITH_PLAYWRIGHT=1
RUN if [ "$WITH_PLAYWRIGHT" = "1" ]; then pip install playwright && playwright install --with-deps chromium; fi
COPY --from=web /web/dist ./web/dist
EXPOSE 8765
HEALTHCHECK CMD curl -fs http://localhost:8765/api/health || exit 1
CMD ["python", "-m", "ftf.cli", "serve", "--host", "0.0.0.0", "--port", "8765"]
