FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ups_sentinel.py .

EXPOSE 9113

CMD ["python", "ups_sentinel.py"]
