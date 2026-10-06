# Real-browser capture job (task 01a0fc6d, ADR-0006 rung 2). Stock Chromium from the official
# Playwright image, default settings: no stealth packages, no fingerprint changes, no proxy.
# Build context is tools/ so page_capture (plan, robots, blocks, store) ships alongside.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble
WORKDIR /app
COPY browser_capture/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY page_capture/page_capture ./page_capture
COPY browser_capture/browser_capture ./browser_capture
ENV PYTHONUNBUFFERED=1
USER pwuser
CMD ["python", "-m", "browser_capture.run"]
