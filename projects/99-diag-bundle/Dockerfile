FROM python:3.12-slim

# Install necessary host utilities: docker CLI, smartmontools, systemd
# systemctl needs systemd package.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    docker.io \
    smartmontools \
    systemd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY diag_exporter.py /app/

ENTRYPOINT ["python", "diag_exporter.py"]
CMD ["--help"]
