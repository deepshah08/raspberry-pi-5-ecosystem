FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    espeak \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY synthesizer_daemon.py .

# Create dummy briefing file for healthcheck or default usage
RUN mkdir -p /data
RUN touch /data/dummy_briefing.md

CMD ["python", "synthesizer_daemon.py", "--briefing-file", "/data/dummy_briefing.md"]
