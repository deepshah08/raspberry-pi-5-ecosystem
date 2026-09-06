FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends smartmontools libcap2-bin && \
    setcap cap_sys_admin,cap_sys_rawio+ep /usr/sbin/smartctl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir prometheus-client requests

# Create a non-root user
RUN groupadd -g 1000 sentinel && \
    useradd -u 1000 -g sentinel -m sentinel && \
    # The user might need access to raw devices. Since capabilities (SYS_RAWIO)
    # are added at runtime via docker-compose, running as non-root is fine.
    usermod -aG disk sentinel

WORKDIR /app
COPY smart_sentinel.py .

USER sentinel

CMD ["python", "/app/smart_sentinel.py"]
