# One-off Gulf-egress probe (task 01a0f3d2-fb2d). Stock Playwright image: real Chromium + xvfb,
# no stealth patches. Runs as the dedicated pi-probe-runner SA; no keys in the image.
FROM mcr.microsoft.com/playwright:v1.58.2-noble
RUN apt-get update && apt-get install -y --no-install-recommends python3-venv xvfb \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir -r requirements.txt
COPY gulf_probe ./gulf_probe
ENV PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
USER pwuser
CMD ["/venv/bin/python", "-m", "gulf_probe.run"]
