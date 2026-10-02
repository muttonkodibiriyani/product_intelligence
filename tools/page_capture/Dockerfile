# Generic page/picture capture job (task 01a0fc6d). Plain httpx only; no proxy, no stealth packages.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY page_capture ./page_capture
ENV PYTHONUNBUFFERED=1
USER nobody
CMD ["python", "-m", "page_capture.run"]
