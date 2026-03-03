FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    UOA_RUNTIME_DATA_DIR=/var/data/runtime \
    UOA_DATA_ROOT=/var/data/dataset

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app
RUN chmod +x /app/deploy/start.sh /app/deploy/ensure_dataset.sh

EXPOSE 10000

CMD ["/bin/sh", "-c", "/app/deploy/start.sh"]
