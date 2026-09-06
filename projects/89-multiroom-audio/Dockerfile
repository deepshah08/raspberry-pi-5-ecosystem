FROM python:3.12-slim

WORKDIR /app
COPY audio_sentry.py /app/
RUN pip install prometheus-client

CMD ["python", "audio_sentry.py"]
