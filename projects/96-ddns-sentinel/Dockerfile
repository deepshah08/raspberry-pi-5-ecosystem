FROM python:3.11-alpine

WORKDIR /app

RUN pip install requests prometheus_client dnspython

COPY ddns_sentinel.py .

EXPOSE 9121

ENTRYPOINT ["python", "ddns_sentinel.py"]
