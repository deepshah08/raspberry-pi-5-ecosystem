FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ml_governor.py .

EXPOSE 9128
ENTRYPOINT ["python", "ml_governor.py"]
