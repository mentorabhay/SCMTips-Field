# SCMTIPS Field production images (M4-C18, hosted on VM-1 with the SCMTIPS core). Build from the repository root:
#   docker build -f deploy/docker/field.Dockerfile --target field-api    -t scmtips-field-api .
#   docker build -f deploy/docker/field.Dockerfile --target field-worker -t scmtips-field-worker .
#   docker build -f deploy/docker/field.Dockerfile --target erp-sim      -t scmtips-erp-sim .
# One locked environment (uv.lock, runtime dependencies only) holds field-api, field-worker, the ERP connector and
# erp-sim; the stand-in core (tools/fake-core, a dev double) is never installed. Every target runs as a non-root user.
# Migrations: the field-api image, `alembic upgrade head` in services/field-api and services/erp-sim (compose
# service field-migrate in the hosting kit). Settings by name: deploy/hosted/field.env.example.

ARG PYTHON_IMAGE=python:3.13-slim-bookworm
ARG UV_VERSION=0.11.32

FROM ${PYTHON_IMAGE} AS build
ARG UV_VERSION
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
RUN pip install "uv==${UV_VERSION}"
WORKDIR /app
# The workspace manifests first, so the dependency layer is cached while only source changes.
COPY pyproject.toml uv.lock ./
COPY services/field-api/pyproject.toml services/field-api/
COPY services/field-worker/pyproject.toml services/field-worker/
COPY services/erp-sim/pyproject.toml services/erp-sim/
COPY connectors/sap/pyproject.toml connectors/sap/
COPY compat/pyproject.toml compat/
COPY tools/fake-core/pyproject.toml tools/fake-core/
RUN uv sync --frozen --no-dev --no-install-project --no-install-workspace
COPY services ./services
COPY connectors ./connectors
COPY config ./config
# Workspace members in place (editable), so the alembic folders and config/ stay where the code looks for them.
RUN uv sync --frozen --no-dev --no-install-project --no-install-package fake-core --no-install-package field-compat \
    && rm -rf tools

FROM ${PYTHON_IMAGE} AS runtime
RUN groupadd --system --gid 10001 field \
    && useradd --system --uid 10001 --gid field --home-dir /app --shell /usr/sbin/nologin field
WORKDIR /app
COPY --from=build /app /app
# Writable data folders (assistant photos, evidence crops, try-look photos); the hosting kit mounts a volume on /data.
RUN mkdir -p /data/assistant-photos /data/crops /data/try-photos && chown -R 10001:10001 /data
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FIELD_ASSISTANT_PHOTO_DIR=/data/assistant-photos \
    FIELD_CROP_DIR=/data/crops \
    FIELD_TRY_PHOTO_DIR=/data/try-photos
USER 10001:10001

FROM runtime AS field-api
EXPOSE 8020
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8020/v1/health', timeout=4)"]
# Behind Caddy on the kit's internal network: X-Forwarded-* from the proxy are honoured.
CMD ["uvicorn", "field_api.app:app", "--host", "0.0.0.0", "--port", "8020", "--proxy-headers", \
     "--forwarded-allow-ips", "*", "--no-access-log"]

FROM runtime AS field-worker
# Healthy while the worker's own heartbeat row (ops.service_heartbeat, written every tick) is under 2 minutes old.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=4 \
    CMD ["python", "-c", "import os,psycopg; c=psycopg.connect(os.environ['FIELD_WORKER_DATABASE_URL'],connect_timeout=5); r=c.execute(\"SELECT beat_at > NOW() - interval '2 minutes' FROM ops.service_heartbeat WHERE service = 'field-worker'\").fetchone(); raise SystemExit(0 if r and r[0] else 1)"]
CMD ["python", "-m", "field_worker"]

FROM runtime AS erp-sim
EXPOSE 8002
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8002/_sim/health', timeout=4)"]
CMD ["uvicorn", "erp_sim.app:app", "--host", "0.0.0.0", "--port", "8002", "--proxy-headers", \
     "--forwarded-allow-ips", "*", "--no-access-log"]
