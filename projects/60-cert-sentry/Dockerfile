FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cert_sentry.py .

CMD ["python", "cert_sentry.py", "--generate-ca"]
