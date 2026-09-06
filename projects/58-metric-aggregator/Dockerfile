FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir requests pyyaml

COPY aggregator.py /app/aggregator.py

CMD ["python", "aggregator.py", "--output", "/app/output/targets.json", "--format", "json", "--interval", "60"]
