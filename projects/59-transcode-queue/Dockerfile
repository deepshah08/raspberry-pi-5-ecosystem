FROM linuxserver/ffmpeg:latest

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Install Python 3
RUN apt-get update && \
    apt-get install -y python3 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the transcode daemon script
COPY transcode_daemon.py /app/transcode_daemon.py

# Entrypoint will be overridden by docker-compose, but provide a safe default
ENTRYPOINT ["python3", "transcode_daemon.py"]
