FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir redis prometheus_client

COPY redis_sentry.py .

CMD ["python", "redis_sentry.py"]
