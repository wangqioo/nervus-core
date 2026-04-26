FROM nervus-python-base:latest

WORKDIR /srv

COPY requirements.txt .
RUN pip install --force-reinstall -U pydantic -i https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . /srv/arbor

EXPOSE 8090

CMD ["python", "/srv/arbor/main.py"]
