# Recurring incremental UAE beauty collection (task 01a11653-ac7a): one shop per execution,
# sitemap -> new/changed pages -> readings -> feed. Build context is the repository root:
#   docker build -f tools/uae_collect/Dockerfile .
FROM python:3.12-slim
WORKDIR /app
COPY tools/uae_collect/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packages/pi_core/src/pi_core ./pi_core
COPY packages/pi_capture/src/pi_capture ./pi_capture
COPY tools/page_capture/page_capture ./page_capture
COPY tools/capture_read/capture_read ./capture_read
COPY tools/uae_collect/uae_collect ./uae_collect
ENV PYTHONUNBUFFERED=1
USER nobody
CMD ["python", "-m", "uae_collect.run"]
