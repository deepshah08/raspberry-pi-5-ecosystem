FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mesh_sentinel.py .

CMD ["python", "mesh_sentinel.py"]
