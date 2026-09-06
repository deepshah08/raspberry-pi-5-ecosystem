# Project 39: Stirling-PDF Automated OCR Receipt Watcher

## Overview
This project implements a Watchdog daemon (`receipt_watcher.py`) that monitors an incoming directory for new receipt images. It uses Tesseract OCR to extract text from the images, parses key financial attributes (merchant, date, tax, total) using regular expressions, inserts a structured record into a SQLite database (`projects/15-financial-pipeline/financial.db`), and moves the processed receipt to an `archive/YYYY-MM/` directory.

## Architecture

```
+----------------+      +-------------------+      +------------------+
| Incoming Dir   | ---> | Watchdog Daemon   | ---> | Tesseract OCR    |
| (Receipts)     |      | (receipt_watcher) |      | (Text Extraction)|
+----------------+      +-------------------+      +------------------+
                                 |                          |
                                 v                          v
                        +-------------------+      +------------------+
                        | SQLite Database   | <--- | Regex Parser     |
                        | (financial.db)    |      | (Attribute Extr.)|
                        +-------------------+      +------------------+
                                 |
                                 v
                        +-------------------+
                        | Archive Dir       |
                        | (YYYY-MM/)        |
                        +-------------------+
```

## Schema Mapping
The extracted data is mapped to the `transactions` table in `financial.db`:

| Extracted Field | Database Column | Type   | Description                               |
|-----------------|-----------------|--------|-------------------------------------------|
| `date`          | `date`          | TEXT   | The transaction date (e.g., YYYY-MM-DD).  |
| `merchant`      | `description`   | TEXT   | The merchant or store name (first line).  |
| `total`         | `amount`        | REAL   | The total transaction amount.             |
| `tax`           | `tax`           | REAL   | The tax or VAT amount.                    |
| File Name       | `source_file`   | TEXT   | The name of the original receipt file.    |

## Running the Service
A systemd service unit file is provided at `systemd/receipt-watcher.service` with sandboxed resource limits (`Nice=15`, `MemoryMax=512M`).

To install and start the service:
```bash
sudo cp projects/39-ocr-receipt-watcher/systemd/receipt-watcher.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable receipt-watcher.service
sudo systemctl start receipt-watcher.service
```

## Testing
The project includes a robust pytest suite using mocked PDF/image receipts and temporary SQLite databases.

To run the tests:
```bash
pytest projects/39-ocr-receipt-watcher/tests/
```
