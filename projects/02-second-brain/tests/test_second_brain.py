import os
import tempfile
import pytest
from pypdf import PdfWriter
# Add the parent directory to sys.path so we can import our modules
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from ingest import ingest_directory, get_db_client, chunk_text
from search import search
from unittest.mock import patch

def test_chunk_text():
    text = "A" * 1500
    chunks = chunk_text(text, chunk_size=1000, overlap=100)
    assert len(chunks) == 2
    assert len(chunks[0]) == 1000
    assert len(chunks[1]) == 600

def test_ingest_and_search():
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a dummy PDF file
        pdf_path = os.path.join(temp_dir, "test.pdf")
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        with open(pdf_path, "wb") as f:
            writer.write(f)

        # We will mock read_pdf to return something predictable
        with patch('ingest.read_pdf', return_value="Dummy text for testing Second Brain integration."):
            # Set up ChromaDB in a temporary directory
            db_path = os.path.join(temp_dir, "chroma_db")

            # Run ingestion
            ingest_directory(temp_dir, db_path)

            # Wait a moment to ensure it is flushed
            client = get_db_client(db_path)
            collection = client.get_or_create_collection(name="second_brain")
            assert collection.count() >= 1

            # Test searching
            results = search("Second Brain", db_path, n_results=1)
            # search returns formatted results as a list of dicts
            assert len(results) == 1
            assert "Dummy text" in results[0]["document"]
