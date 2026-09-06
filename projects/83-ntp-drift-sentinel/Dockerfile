FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir ntplib prometheus_client

COPY ntp_sentinel.py .

CMD ["python", "ntp_sentinel.py"]
