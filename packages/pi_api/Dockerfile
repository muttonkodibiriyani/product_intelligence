# pi-api: the read-only service layer on Cloud Run (service-layer design §3, task 01a0f488).
# Build from the repo root:  docker build -f packages/pi_api/Dockerfile -t pi-api .
# No keys in the image: GCS reads use the service account; ID tokens are verified against
# Google's public certificates. Unauthenticated invoke is allowed because every route checks
# the Firebase ID token in-app. Base images are pinned by digest; bump tag and digest together.
FROM ghcr.io/astral-sh/uv:0.12.13@sha256:b485bd65cc2cf1c9a93b3554012c9c3778cf7b1b5fd3d3096ce9e1226c97e1e6 AS uv

FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages ./packages
RUN uv sync --frozen --no-dev --no-editable --package pi-api --extra gcs

FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER nobody
EXPOSE 8080
CMD ["uvicorn", "--factory", "pi_api.app:app_from_env", "--host", "0.0.0.0", "--port", "8080", \
     "--no-server-header", "--timeout-graceful-shutdown", "10"]
