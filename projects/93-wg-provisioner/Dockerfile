FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir cryptography qrcode pillow

COPY wg_provisioner.py /app/

ENTRYPOINT ["python3", "wg_provisioner.py"]
