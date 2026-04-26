FROM node:20-slim AS frontend-build
WORKDIR /frontend
COPY apps/file-manager/frontend/package*.json ./
RUN npm install
COPY apps/file-manager/frontend/ .
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY sdk/python /app/nervus-sdk
COPY apps/file-manager/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple \
 && pip install --no-cache-dir /app/nervus-sdk -i https://pypi.tuna.tsinghua.edu.cn/simple
COPY apps/file-manager/manifest.json /app/manifest.json
COPY apps/file-manager/backend/ ./backend/
COPY --from=frontend-build /frontend/dist ./frontend/dist
RUN mkdir -p /app/data/files
ENV PYTHONPATH=/app
EXPOSE 8015
CMD ["python", "backend/main.py"]
