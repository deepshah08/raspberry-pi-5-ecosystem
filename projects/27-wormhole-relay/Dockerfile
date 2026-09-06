FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY wormhole_relay.py .

CMD ["python", "wormhole_relay.py"]
