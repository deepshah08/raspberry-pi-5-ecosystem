FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY canary.py .

EXPOSE 9110

CMD ["python", "canary.py"]
