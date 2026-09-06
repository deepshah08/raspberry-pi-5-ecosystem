FROM python:3.11-slim
WORKDIR /app
RUN pip install prometheus_client
COPY alert_silencer.py .
CMD ["python", "alert_silencer.py"]
