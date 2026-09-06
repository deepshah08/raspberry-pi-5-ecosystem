FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    smartmontools \
    btrfs-progs \
    zfsutils-linux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

CMD ["python", "scrub_sentinel.py"]