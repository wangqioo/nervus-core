FROM nervus-python-base:latest
WORKDIR /app
COPY nervus-sdk /app/nervus-sdk
COPY apps/file-manager/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple \
 && pip install --no-cache-dir /app/nervus-sdk -i https://pypi.tuna.tsinghua.edu.cn/simple
COPY apps/file-manager/. .
RUN mkdir -p /data/files
EXPOSE 8015
CMD ["python", "main.py"]
