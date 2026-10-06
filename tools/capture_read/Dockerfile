# Reads saved pages from our own bucket into pi_capture readings (task 01a0fc6d). It fetches
# nothing from any retailer. Build context is the repository root so the readers ship with it:
#   docker build -f tools/capture_read/Dockerfile .
FROM python:3.12-slim
WORKDIR /app
COPY tools/capture_read/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packages/pi_core/src/pi_core ./pi_core
COPY packages/pi_capture/src/pi_capture ./pi_capture
COPY tools/capture_read/capture_read ./capture_read
ENV PYTHONUNBUFFERED=1
USER nobody
CMD ["python", "-m", "capture_read.run"]
