FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY document_classifier.py .

# Create directory structure
RUN mkdir -p input archive

# Do not run as root when writing to bound volumes if possible,
# but for simplicity in a docker-compose setup without explicit user mapping:
USER root

CMD ["python", "document_classifier.py", "--input-dir", "/app/input"]
