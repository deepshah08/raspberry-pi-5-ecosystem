import os
import sqlite3
import pytest
from unittest.mock import patch, MagicMock

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import sys, os; sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))); import receipt_watcher; import os

def test_parse_receipt_data_all_fields():
    ocr_text = """Acme Corp
123 Fake St.
Date: 2023-10-27
Some item   10.00
Tax: $1.50
Total: $11.50
Thank you!"""
    data = receipt_watcher.parse_receipt_data(ocr_text)
    assert data["merchant"] == "Acme Corp"
    assert data["date"] == "2023-10-27"
    assert data["tax"] == 1.50
    assert data["total"] == 11.50

def test_parse_receipt_data_missing_fields():
    ocr_text = """Just A Store
Some item 5.00
"""
    data = receipt_watcher.parse_receipt_data(ocr_text)
    assert data["merchant"] == "Just A Store"
    assert data["date"] is None
    assert data["tax"] is None
    assert data["total"] == 5.00  # Fallback to largest amount

def test_parse_receipt_data_multiple_totals():
    ocr_text = """Big Box Store
2024-01-15
Subtotal: 20.00
Tax 2.00
Total Due 22.00
"""
    data = receipt_watcher.parse_receipt_data(ocr_text)
    assert data["merchant"] == "Big Box Store"
    assert data["date"] == "2024-01-15"
    assert data["tax"] == 2.00
    assert data["total"] == 22.00

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_financial.db"
    receipt_watcher.init_db(str(db_file))
    return str(db_file)

def test_insert_transaction(temp_db):
    data = {
        "merchant": "Test Store",
        "date": "2023-11-01",
        "tax": 1.00,
        "total": 10.00
    }
    receipt_watcher.insert_transaction(data, "receipt1.jpg", db_path=temp_db)

    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT date, description, amount, tax, source_file FROM transactions")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "2023-11-01"
    assert row[1] == "Test Store"
    assert row[2] == 10.00
    assert row[3] == 1.00
    assert row[4] == "receipt1.jpg"


@pytest.fixture
def mock_archive_dir(tmp_path):
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    return str(archive_dir)

def test_archive_receipt(tmp_path, mock_archive_dir):
    # Create a dummy file
    dummy_file = tmp_path / "receipt_test.jpg"
    dummy_file.write_text("dummy image data")

    # Archive it with a specific date
    new_path = receipt_watcher.archive_receipt(str(dummy_file), "2023-12-25", archive_base_dir=mock_archive_dir)

    import os; assert os.path.exists(new_path)
    assert not os.path.exists(str(dummy_file))
    assert "2023-12" in new_path
    assert os.path.basename(new_path) == "receipt_test.jpg"

def test_archive_receipt_no_date(tmp_path, mock_archive_dir):
    # Create a dummy file
    dummy_file = tmp_path / "receipt_nodate.jpg"
    dummy_file.write_text("dummy")

    new_path = receipt_watcher.archive_receipt(str(dummy_file), None, archive_base_dir=mock_archive_dir)

    import os; assert os.path.exists(new_path)
    # Should use current YYYY-MM
    import sys, os; import os; sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))); from datetime import datetime
    current_yyyy_mm = datetime.now().strftime("%Y-%m")
    assert current_yyyy_mm in new_path


@patch('receipt_watcher.extract_text_from_image')
@patch('receipt_watcher.insert_transaction')
@patch('receipt_watcher.archive_receipt')
def test_process_file(mock_archive, mock_insert, mock_extract, tmp_path):
    mock_extract.return_value = "Mock Store\n2024-02-01\nTotal: 15.00"

    dummy_file = tmp_path / "test_process.jpg"
    dummy_file.write_text("dummy")

    receipt_watcher.process_file(str(dummy_file))

    mock_extract.assert_called_once_with(str(dummy_file))
    mock_insert.assert_called_once()

    args, _ = mock_insert.call_args
    data = args[0]
    assert data["merchant"] == "Mock Store"
    assert data["total"] == 15.00

    mock_archive.assert_called_once_with(str(dummy_file), "2024-02-01")

@patch('receipt_watcher.extract_text_from_image')
@patch('receipt_watcher.insert_transaction')
def test_process_file_no_text(mock_insert, mock_extract, tmp_path):
    mock_extract.return_value = ""
    dummy_file = tmp_path / "empty.jpg"
    dummy_file.write_text("dummy")

    receipt_watcher.process_file(str(dummy_file))

    mock_insert.assert_not_called()
