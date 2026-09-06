FROM python:3.11-slim

WORKDIR /app

RUN pip install docker

COPY oom_watchdog.py .

CMD ["python", "oom_watchdog.py"]
