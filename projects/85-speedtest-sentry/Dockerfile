FROM python:3.11-slim

WORKDIR /app
COPY speedtest_sentry.py .
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 9115

ENTRYPOINT ["python", "speedtest_sentry.py"]
