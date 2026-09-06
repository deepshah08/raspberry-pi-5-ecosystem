import sys
import os
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from document_classifier import extract_text, classify_text, process_file, scan_directory, main
import document_classifier

def test_classify_text_tax():
    text = "Here is my W-2 for the year."
    assert classify_text(text) == "Tax"

def test_classify_text_medical():
    text = "Explanation of benefits from clinic."
    assert classify_text(text) == "Medical"

def test_classify_text_utilities():
    text = "PG&E Electric bill amount due."
    assert classify_text(text) == "Utilities"

def test_classify_text_invoices():
    text = "Invoice total due 100."
    assert classify_text(text) == "Invoices"

def test_classify_text_uncategorized():
    text = "Random letter from a friend."
    assert classify_text(text) == "Uncategorized"

def test_extract_text_txt_file(tmp_path):
    p = tmp_path / "test.txt"
    p.write_text("Hello World!")
    assert extract_text(p) == "Hello World!"

@patch('document_classifier.PdfReader')
def test_extract_text_pdf_file(mock_pdf_reader, tmp_path):
    p = tmp_path / "test.pdf"
    p.touch()

    mock_page = MagicMock()
    mock_page.extract_text.return_value = "PDF text"
    mock_reader_instance = mock_pdf_reader.return_value
    mock_reader_instance.pages = [mock_page]

    assert extract_text(p) == "PDF text\n"

@patch('document_classifier.pytesseract.image_to_string')
@patch('document_classifier.Image.open')
def test_extract_text_image_file(mock_image_open, mock_image_to_string, tmp_path):
    p = tmp_path / "test.jpg"
    p.touch()

    mock_image_to_string.return_value = "OCR text"

    assert extract_text(p) == "OCR text"

@patch('document_classifier.shutil.move')
def test_process_file_routing(mock_move, tmp_path):
    p = tmp_path / "doc.txt"
    p.write_text("W-2 tax return")
    archive_base = tmp_path / "archive"

    # Reset metrics for test isolation
    before_val = document_classifier.DOCS_CLASSIFIED.labels(category="Tax")._value.get()

    process_file(p, archive_base, dry_run=False)

    # verify move was called
    assert mock_move.called

    # check prometheus metrics
    after_val = document_classifier.DOCS_CLASSIFIED.labels(category="Tax")._value.get()
    assert after_val > before_val

@patch('document_classifier.shutil.move')
def test_process_file_dry_run(mock_move, tmp_path):
    p = tmp_path / "doc2.txt"
    p.write_text("W-2 tax return")
    archive_base = tmp_path / "archive"

    process_file(p, archive_base, dry_run=True)

    # move should NOT be called in dry run
    assert not mock_move.called

@patch('document_classifier.process_file')
def test_scan_directory(mock_process, tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "valid.txt").touch()
    (input_dir / "invalid.bin").touch()

    archive_base = tmp_path / "archive"

    scan_directory(input_dir, archive_base, dry_run=False)

    # Only valid.txt should be processed
    assert mock_process.call_count == 1
    args, _ = mock_process.call_args
    assert args[0].name == "valid.txt"

@patch('document_classifier.scan_directory')
@patch('document_classifier.start_http_server')
def test_cli_flags(mock_server, mock_scan, monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    # Test --scan-now and --dry-run
    test_args = ["document_classifier.py", "--input-dir", str(input_dir), "--scan-now", "--dry-run", "--json"]
    with patch.object(sys, 'argv', test_args):
        main()

    assert mock_scan.called
    args, kwargs = mock_scan.call_args
    assert args[2] == True # dry-run flag
    assert not mock_server.called # start_http_server should not be called with --scan-now
