# ulta.ae rung-5 fetch job (ADR-0006 Amendment 2). Stock Playwright WebKit as shipped in the
# official image, pinned to the locked playwright version; no stealth packages, no keys in the
# image. The proxy login is read from Secret Manager at runtime by pi_fetch, never baked in.
# Build from the repo root: docker build -f tools/ulta_snapshot/Dockerfile -t pi-ulta-fetch .
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble
WORKDIR /app
COPY tools/ulta_snapshot/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --break-system-packages -r requirements.lock \
    "google-auth[requests]==2.40.3"
COPY packages/pi_core ./packages/pi_core
COPY packages/pi_fetch ./packages/pi_fetch
COPY packages/pi_connector_ulta ./packages/pi_connector_ulta
RUN pip install --no-cache-dir --break-system-packages --no-deps \
    ./packages/pi_core ./packages/pi_fetch ./packages/pi_connector_ulta
COPY tools/ulta_snapshot/ulta_snapshot ./ulta_snapshot
ENV PYTHONUNBUFFERED=1
USER pwuser
CMD ["python", "-m", "ulta_snapshot.run"]
