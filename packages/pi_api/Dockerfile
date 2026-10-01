# pi-api: the read-only service layer on Cloud Run (service-layer design §3, task 01a0f488).
# Build from the repo root:  docker build -f packages/pi_api/Dockerfile -t pi-api .
# No keys in the image: GCS reads use the service account; ID tokens are verified against
# Google's public certificates. Unauthenticated invoke is allowed because every route checks
# the Firebase ID token in-app.
FROM ghcr.io/astral-sh/uv:0.12.13 AS uv

FROM python:3.12-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages ./packages
RUN uv sync --frozen --no-dev --no-editable --package pi-api --extra gcs

FROM python:3.12-slim
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER nobody
EXPOSE 8080
CMD ["uvicorn", "--factory", "pi_api.app:app_from_env", "--host", "0.0.0.0", "--port", "8080", \
     "--no-server-header", "--timeout-graceful-shutdown", "10"]
