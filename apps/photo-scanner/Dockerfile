FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY nervus-sdk /app/nervus-sdk
COPY apps/photo-scanner/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir /app/nervus-sdk
COPY apps/photo-scanner/. .
RUN mkdir -p /data /photos
EXPOSE 8006
CMD ["python", "main.py"]
