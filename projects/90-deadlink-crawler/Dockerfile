FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY crawler_sentry.py .

CMD ["python", "crawler_sentry.py"]
