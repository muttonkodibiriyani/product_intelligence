# ulta.ae rung-5 fetch job (ADR-0006 Amendment 2). Stock Playwright WebKit as shipped in the
# official image, pinned to the locked playwright version (tag and digest); no stealth packages,
# no keys in the image. The proxy login is read from Secret Manager at runtime by pi_fetch with
# the operator's short-lived token, never baked in. Runbook: docs/runbooks/ulta-proxy-test.md.
# Build from the repo root: docker build -f tools/ulta_snapshot/Dockerfile -t pi-ulta-fetch .
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble@sha256:72bd171a9ffc2b4b59532aaa6210e21014d07093120dc25528870c0b840da1f0
WORKDIR /app
COPY tools/ulta_snapshot/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --break-system-packages -r requirements.lock
COPY packages/pi_core ./packages/pi_core
COPY packages/pi_fetch ./packages/pi_fetch
COPY packages/pi_connector_ulta ./packages/pi_connector_ulta
RUN pip install --no-cache-dir --break-system-packages --no-deps \
    ./packages/pi_core ./packages/pi_fetch ./packages/pi_connector_ulta
COPY tools/ulta_snapshot/ulta_snapshot ./ulta_snapshot
COPY tools/ulta_snapshot/urls ./urls
ENV PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    OUT_DIR=/out \
    URL_SOURCE=file \
    URLS_FILE=/app/urls/test20_en.txt \
    MAX_PAGES=20 \
    CAPTURE_JSON=0
USER pwuser
CMD ["python", "-m", "ulta_snapshot.run"]
