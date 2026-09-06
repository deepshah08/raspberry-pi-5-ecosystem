FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY vault_sentinel.py .

CMD ["python", "vault_sentinel.py"]
