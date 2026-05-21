FROM node:22-bookworm-slim AS frontend-build
WORKDIR /src/frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV APP_ROOT=/opt/mister-companion-web/app \
    APP_CONFIG_DIR=/config \
    APP_DATA_DIR=/data \
    FRONTEND_DIST=/opt/mister-companion-web/app/frontend/dist \
    UPSTREAM_DIR=/opt/mister-companion-web/app/vendor/mister-companion/mister-companion \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/mister-companion-web/app
COPY backend/ ./backend/
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && mkdir -p /opt/mister-companion-web/app/vendor \
    && git clone --depth 1 https://github.com/Anime0t4ku/mister-companion.git /opt/mister-companion-web/app/vendor/mister-companion

COPY --from=frontend-build /src/frontend/dist ./frontend/dist
RUN mkdir -p /config /data

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS http://127.0.0.1:8080/api/health >/dev/null || exit 1
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
