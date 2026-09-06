FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    rsync \
    smartmontools \
    hdparm \
    && rm -rf /var/lib/apt/lists/*

COPY cold_sync.py /app/cold_sync.py
WORKDIR /app
