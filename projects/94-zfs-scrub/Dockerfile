FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y zfsutils-linux smartmontools && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY zfs_orchestrator.py .

CMD ["python", "zfs_orchestrator.py"]
