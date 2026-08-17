FROM node:22-bookworm-slim AS pot-provider

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && git clone --depth 1 --branch 1.3.1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil-ytdlp-pot-provider \
    && cd /opt/bgutil-ytdlp-pot-provider/server \
    && npm ci \
    && npx tsc

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ffmpeg ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --upgrade pip \
    && python -m pip install --upgrade yt-dlp

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY --from=pot-provider /usr/local/bin/node /usr/local/bin/node
COPY --from=pot-provider /opt/bgutil-ytdlp-pot-provider/server/build /opt/bgutil-ytdlp-pot-provider/server/build
COPY --from=pot-provider /opt/bgutil-ytdlp-pot-provider/server/node_modules /opt/bgutil-ytdlp-pot-provider/server/node_modules
COPY app ./app
COPY frontend ./frontend

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /tmp/ytdlp-web \
    && chown -R appuser:appuser /app /tmp/ytdlp-web
USER appuser

EXPOSE 8000
CMD ["sh", "-c", "cd /opt/bgutil-ytdlp-pot-provider/server && node build/main.js --port 4416 & exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
