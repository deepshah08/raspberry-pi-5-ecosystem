FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    wireguard-tools \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install prometheus_client

COPY . .

CMD ["python", "wg_failover.py"]
