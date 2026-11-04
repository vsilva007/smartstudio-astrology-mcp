ARG PYTHON_IMAGE=python:3.12.16-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
FROM ${PYTHON_IMAGE} AS dependencies
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.lock ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.lock

FROM dependencies AS build
COPY src src
COPY data/ephemeris-manifest.json data/ephemeris-manifest.json
COPY scripts/fetch_ephemeris.py scripts/fetch_ephemeris.py
RUN python scripts/fetch_ephemeris.py \
    && PYTHONPATH=src /opt/venv/bin/python -m compileall -q src \
    && PYTHONPATH=src /opt/venv/bin/python -c "from smartstudio_mcp.engine import Engine; from smartstudio_mcp.config import Settings; assert len(Engine(Settings()).calculate(2451545.0, 'mean')[0]) == 12"

FROM ${PYTHON_IMAGE} AS runtime
ARG PROJECT_NAME=smartstudio-astrology-mcp
ARG DEPLOY_ENV=demo
ARG RELEASE_REVISION=development
LABEL dev.smartstudio.project="${PROJECT_NAME}" \
      dev.smartstudio.environment="${DEPLOY_ENV}" \
      org.opencontainers.image.title="Smart Studio Astrology MCP" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.revision="${RELEASE_REVISION}"
ENV PATH="/opt/venv/bin:$PATH" PYTHONPATH=/app/src PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 CARTA_RELEASE_REVISION="${RELEASE_REVISION}"
WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
COPY --from=build /build/data data
COPY --from=build /build/src src
COPY legal legal
COPY docs/PRIVACY.md docs/PRIVACY.md
COPY LICENSE NOTICE ./
COPY artifacts/source.tar.gz artifacts/source.tar.gz
RUN rm -rf /opt/venv/lib/python3.12/site-packages/pip* /opt/venv/bin/pip* \
    /usr/local/lib/python3.12/site-packages/pip* /usr/local/bin/pip* \
    && useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin carta
USER 1000:1000
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import os,json,urllib.request; host=json.loads(os.environ['CARTA_ALLOWED_HOSTS'])[0]; r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/healthz',headers={'Host':host}),timeout=2); assert json.load(r)['status']=='ok'"
CMD ["uvicorn", "smartstudio_mcp.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--no-proxy-headers", "--limit-concurrency", "32", "--timeout-keep-alive", "5", "--timeout-graceful-shutdown", "10"]
