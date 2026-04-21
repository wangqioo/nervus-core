FROM python:3.11-slim

WORKDIR /app

# 系统依赖（ffmpeg 用于音频处理）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY main.py .

EXPOSE 8081

CMD ["python", "main.py"]
