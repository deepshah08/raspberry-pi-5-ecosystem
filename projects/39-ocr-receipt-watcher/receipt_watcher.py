import os
import re
import sqlite3
import shutil
import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional

import pytesseract
from PIL import Image
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
INCOMING_DIR = os.environ.get("RECEIPT_INCOMING_DIR", "/tmp/receipts_incoming")
ARCHIVE_DIR = os.environ.get("RECEIPT_ARCHIVE_DIR", "/tmp/receipts_archive")
DB_PATH = os.environ.get("RECEIPT_DB_PATH", "projects/15-financial-pipeline/financial.db")


def extract_text_from_image(image_path: str) -> str:
    """Extracts text from an image using Tesseract OCR."""
    try:
        image = Image.open(image_path)
        text = pytesseract.image_to_string(image)
        return text
    except Exception as e:
        logger.error(f"Error extracting text from {image_path}: {e}")
        return ""


def parse_receipt_data(text: str) -> Dict[str, Any]:
    """Parses key financial attributes from OCR text."""
    data: Dict[str, Any] = {
        "merchant": None,
        "date": None,
        "tax": None,
        "total": None
    }

    if not text:
        return data

    lines = [line.strip() for line in text.split('\n') if line.strip()]
    if lines:
        data["merchant"] = lines[0] # Simple heuristic: first line is often the merchant

    # Date regex (YYYY-MM-DD, MM/DD/YYYY, etc.)
    date_patterns = [
        r'\b(\d{4}-\d{2}-\d{2})\b',
        r'\b(\d{1,2}/\d{1,2}/\d{2,4})\b',
        r'\b(\d{1,2}-\d{1,2}-\d{2,4})\b'
    ]
    for pattern in date_patterns:
        match = re.search(pattern, text)
        if match:
            # Normalize to YYYY-MM-DD or whatever parse format can handle, keeping raw string for now
            data["date"] = match.group(1)
            break

    # Tax regex
    tax_pattern = re.compile(r'(?:tax|vat)\s*(?:\:|\-|\=)?\s*\$?([\d\.\,]+)', re.IGNORECASE)
    tax_match = tax_pattern.search(text)
    if tax_match:
        try:
            data["tax"] = float(tax_match.group(1).replace(',', ''))
        except ValueError:
            pass

    # Total regex
    total_pattern = re.compile(r'(?:total|amount|due)\s*(?:\:|\-|\=)?\s*\$?([\d\.\,]+)', re.IGNORECASE)
    # Find all matches and take the largest or the last one. Usually the last 'Total' is the grand total.
    total_matches = total_pattern.findall(text)
    if total_matches:
        try:
            # Let's take the last valid float we find
            for t_str in reversed(total_matches):
                try:
                    data["total"] = float(t_str.replace(',', ''))
                    break
                except ValueError:
                    continue
        except Exception:
            pass

    # Fallback to finding the largest currency amount if total not explicitly labeled
    if data["total"] is None:
        money_pattern = re.compile(r'\$?\b(\d+\.\d{2})\b')
        money_matches = money_pattern.findall(text)
        if money_matches:
            amounts = [float(m) for m in money_matches]
            data["total"] = max(amounts)

    return data

def init_db(db_path: str = DB_PATH):
    """Initializes the database table if it doesn't exist."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            description TEXT,
            amount REAL,
            tax REAL,
            source_file TEXT
        )
    ''')
    conn.commit()
    conn.close()


def insert_transaction(data: Dict[str, Any], file_name: str, db_path: str = DB_PATH):
    """Inserts a structured transaction record into the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO transactions (date, description, amount, tax, source_file) VALUES (?, ?, ?, ?, ?)",
        (data.get("date"), data.get("merchant"), data.get("total"), data.get("tax"), file_name)
    )
    conn.commit()
    conn.close()
    logger.info(f"Inserted transaction from {file_name} into DB.")


def archive_receipt(file_path: str, date_str: Optional[str], archive_base_dir: str = ARCHIVE_DIR) -> str:
    """Moves the processed receipt to an archive folder organized by YYYY-MM."""
    # Determine YYYY-MM folder
    yyyy_mm = datetime.now().strftime("%Y-%m")
    if date_str:
        # Try to parse YYYY-MM from date_str
        # Assuming format is usually YYYY-MM-DD or MM/DD/YYYY
        if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
            yyyy_mm = date_str[:7]
        elif re.match(r'\d{1,2}/\d{1,2}/\d{2,4}', date_str):
            parts = date_str.split('/')
            if len(parts[-1]) == 4: # MM/DD/YYYY
                yyyy_mm = f"{parts[-1]}-{parts[0].zfill(2)}"
            elif len(parts[-1]) == 2: # MM/DD/YY
                yyyy_mm = f"20{parts[-1]}-{parts[0].zfill(2)}"

    archive_dir = os.path.join(archive_base_dir, yyyy_mm)
    os.makedirs(archive_dir, exist_ok=True)

    file_name = os.path.basename(file_path)
    new_path = os.path.join(archive_dir, file_name)

    # Ensure unique filename if it exists
    base, ext = os.path.splitext(file_name)
    counter = 1
    while os.path.exists(new_path):
        new_path = os.path.join(archive_dir, f"{base}_{counter}{ext}")
        counter += 1

    shutil.move(file_path, new_path)
    logger.info(f"Archived {file_path} to {new_path}")
    return new_path

def process_file(file_path: str):
    """Orchestrates the extraction, parsing, insertion, and archiving of a receipt."""
    logger.info(f"Processing new file: {file_path}")
    text = extract_text_from_image(file_path)
    if not text:
        logger.warning(f"No text extracted from {file_path}. Skipping.")
        return

    data = parse_receipt_data(text)
    logger.info(f"Extracted data: {data}")

    file_name = os.path.basename(file_path)
    insert_transaction(data, file_name)
    archive_receipt(file_path, data.get("date"))


class ReceiptHandler(FileSystemEventHandler):
    """Watchdog event handler for new files."""
    def on_created(self, event):
        if not event.is_directory:
            # Add a small delay to ensure file is completely written before processing
            time.sleep(1)
            process_file(event.src_path)

def main():
    logger.info("Starting OCR Receipt Watcher...")
    init_db()

    os.makedirs(INCOMING_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    event_handler = ReceiptHandler()
    observer = Observer()
    observer.schedule(event_handler, INCOMING_DIR, recursive=False)
    observer.start()

    logger.info(f"Watching for new receipts in {INCOMING_DIR}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()
