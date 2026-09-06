FROM python:3.12-slim

WORKDIR /app

RUN pip install requests prometheus_client pyyaml

COPY proxy_sentry.py .

CMD ["python", "proxy_sentry.py"]
