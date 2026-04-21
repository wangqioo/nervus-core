FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY nervus-sdk /app/nervus-sdk
COPY apps/meeting-notes/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir /app/nervus-sdk
COPY apps/meeting-notes/. .
RUN mkdir -p /data
EXPOSE 8002
CMD ["python", "main.py"]
