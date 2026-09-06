FROM python:3.12-alpine

# Install system dependencies required for cryptography and Pillow
RUN apk add --no-cache gcc musl-dev libffi-dev jpeg-dev zlib-dev

WORKDIR /app

# Install python dependencies
RUN pip install --no-cache-dir cryptography qrcode Pillow

# Copy the script
COPY provisioner.py /app/provisioner.py

# Keep the container alive to allow `docker exec` commands
CMD ["tail", "-f", "/dev/null"]
