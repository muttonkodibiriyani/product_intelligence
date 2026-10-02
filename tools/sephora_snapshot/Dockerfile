# Sephora UAE snapshot job (task 01a0f424-006c). Plain httpx only; runs as a dedicated SA, no keys in the image.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sephora_snapshot ./sephora_snapshot
ENV PYTHONUNBUFFERED=1
USER nobody
CMD ["python", "-m", "sephora_snapshot.run"]
