FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir requests pillow

COPY photo_curator.py .

CMD ["python", "photo_curator.py"]
