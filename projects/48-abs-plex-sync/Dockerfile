FROM python:3.12-slim

WORKDIR /app
COPY sync_daemon.py .
RUN pip install requests

CMD ["python", "sync_daemon.py"]
