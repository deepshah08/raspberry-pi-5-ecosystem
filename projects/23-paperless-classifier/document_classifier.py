import os
import sys
import time
import shutil
import logging
import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from pypdf import PdfReader
from prometheus_client import start_http_server, Counter
from PIL import Image
import pytesseract

# Prometheus Metrics
DOCS_CLASSIFIED = Counter(
    "homelab_docs_classified_total",
    "Total number of successfully classified and routed documents",
    ["category"]
)
DOCS_FAILED = Counter(
    "homelab_docs_failed_total",
    "Total number of documents that failed processing or classification"
)

# Regex Patterns for Categories
CATEGORIES = {
    "Tax": re.compile(r"(?i)\b(w2|w-2|1099|1040|tax return|irs|franchise tax board)\b"),
    "Medical": re.compile(r"(?i)\b(health|medical|insurance|clinic|hospital|patient|eob|explanation of benefits|copay|deductible)\b"),
    "Utilities": re.compile(r"(?i)\b(electric|water|gas|utility|internet|broadband|pg&e|coned|power|bill)\b"),
    "Invoices": re.compile(r"(?i)\b(invoice|receipt|balance due|amount due|total due)\b")
}

def extract_text(file_path: Path) -> str:
    """Extract text from PDF, Images, or fallback to text file reading."""
    text = ""
    try:
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            reader = PdfReader(str(file_path))
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        elif suffix in [".jpg", ".jpeg", ".png"]:
            text = pytesseract.image_to_string(Image.open(file_path))
        else:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
    except Exception as e:
        logging.error(f"Error extracting text from {file_path}: {e}")
    return text

def classify_text(text: str) -> str:
    """Score keyword matches based on regex rules."""
    scores = {category: 0 for category in CATEGORIES}

    for category, pattern in CATEGORIES.items():
        matches = pattern.findall(text)
        scores[category] = len(matches)

    best_category = max(scores, key=scores.get)
    if scores[best_category] > 0:
        return best_category
    return "Uncategorized"

def setup_logging(use_json: bool):
    """Configure logging format."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    handler = logging.StreamHandler()
    if use_json:
        class JsonFormatter(logging.Formatter):
            def format(self, record):
                log_record = {
                    "timestamp": self.formatTime(record, self.datefmt),
                    "level": record.levelname,
                    "message": record.getMessage()
                }
                return json.dumps(log_record)
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)

def process_file(file_path: Path, archive_base: Path, dry_run: bool):
    """Process a single document."""
    logging.info(f"Processing file: {file_path.name}")

    text = extract_text(file_path)
    if not text.strip():
        logging.warning(f"No text extracted from {file_path.name}. Falling back to filename classification.")
        text = file_path.name # Fallback to filename

    category = classify_text(text)

    if category == "Uncategorized":
        DOCS_FAILED.inc()
        logging.warning(f"Failed to classify {file_path.name}")
    else:
        DOCS_CLASSIFIED.labels(category=category).inc()
        logging.info(f"Classified {file_path.name} as {category}")

    # Route file
    year = str(datetime.now().year)
    target_dir = archive_base / year / category
    target_path = target_dir / file_path.name

    if dry_run:
        logging.info(f"[DRY RUN] Would move {file_path} to {target_path}")
    else:
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(file_path), str(target_path))
            logging.info(f"Moved {file_path.name} to {target_path}")
        except Exception as e:
            logging.error(f"Error moving {file_path.name}: {e}")
            DOCS_FAILED.inc()

def scan_directory(input_dir: Path, archive_base: Path, dry_run: bool):
    """Scan directory for new files."""
    if not input_dir.exists():
        logging.error(f"Input directory does not exist: {input_dir}")
        return

    for item in input_dir.iterdir():
        if item.is_file() and item.suffix.lower() in [".pdf", ".txt", ".md", ".jpg", ".png", ".jpeg"]:
            process_file(item, archive_base, dry_run)

def main():
    # Set nice value to 15 for CPU throttling as requested
    try:
        os.nice(15)
    except Exception as e:
        logging.warning(f"Failed to set nice value: {e}")

    parser = argparse.ArgumentParser(description="Homelab Document OCR Classifier & Ingest Bridge")
    parser.add_argument("--input-dir", type=str, required=True, help="Input directory to watch")
    parser.add_argument("--scan-now", action="store_true", help="Run a single scan immediately and exit")
    parser.add_argument("--dry-run", action="store_true", help="Do not actually move files")
    parser.add_argument("--json", action="store_true", help="Log output in JSON format")

    args = parser.parse_args()

    setup_logging(args.json)

    input_dir = Path(args.input_dir).resolve()
    archive_base = Path("archive").resolve()

    if not args.scan_now:
        # Start prometheus server on port 9130 only if we are running as a daemon/continuously
        # (or always, up to you. But if it's a one-off, prometheus metrics won't be collected by external scraper)
        start_http_server(9130)
        logging.info("Started Prometheus metrics server on port 9130")

        logging.info(f"Watching {input_dir} for new documents...")
        try:
            while True:
                scan_directory(input_dir, archive_base, args.dry_run)
                time.sleep(10)
        except KeyboardInterrupt:
            logging.info("Shutting down...")
    else:
        # Single scan
        scan_directory(input_dir, archive_base, args.dry_run)

if __name__ == "__main__":
    main()
