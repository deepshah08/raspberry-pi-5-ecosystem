1. **Create `projects/39-ocr-receipt-watcher/receipt_watcher.py`**
   - Implement a daemon using `watchdog` to monitor a specified directory for incoming receipts (images).
   - Upon detecting a new file, run Tesseract OCR using `pytesseract` to extract text.
   - Use regular expressions to extract key attributes from the OCR text:
     - Merchant/store name
     - Transaction date
     - Tax amount
     - Total amount
   - Insert the structured record into the SQLite database at `projects/15-financial-pipeline/finances.db` (creating the `transactions` table if it doesn't exist).
   - Move the processed receipt to an `archive/YYYY-MM/` directory based on the current date or transaction date.

2. **Create `projects/39-ocr-receipt-watcher/systemd/receipt-watcher.service`**
   - Define a systemd unit file for the watcher daemon.
   - Specify sandboxing limits: `Nice=15` and `MemoryMax=512M`.
   - Set up correct paths and user context.

3. **Create `projects/39-ocr-receipt-watcher/README.md`**
   - Document the architecture with a diagram.
   - Provide a schema mapping explanation.
   - Document how to test and run the project.

4. **Create `projects/39-ocr-receipt-watcher/tests/test_receipt_watcher.py`**
   - Write tests using `pytest` and `pytest-mock`.
   - Test text extraction and regex parsing.
   - Test database insertion using an in-memory or temporary SQLite db.
   - Test file moving to the correct archive folder.
   - Test the watchdog event handler logic using mocked dependencies.

5. **Run tests**
   - Execute `pytest` and ensure a 100% pass rate.

6. **Complete pre-commit steps**
   - Run `pre_commit_instructions` and follow the guidelines to ensure quality and readiness.

7. **Submit changes**
   - Commit and push to a new branch.
