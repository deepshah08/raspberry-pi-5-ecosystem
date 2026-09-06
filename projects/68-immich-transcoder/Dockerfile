FROM python:3.12-slim

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY video_cache_manager.py .

ENTRYPOINT ["python", "video_cache_manager.py"]
