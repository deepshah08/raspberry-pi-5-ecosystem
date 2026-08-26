import os
import tempfile
import pytest
from pypdf import PdfWriter

# Add the parent directory to sys.path so we can import our modules
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ingest import ingest_directory, get_db_client, chunk_text
from search import search

@pytest.fixture
def temp_workspace():
    # Create a temporary directory for dummy files and chromadb
    with tempfile.TemporaryDirectory() as temp_dir:
        files_dir = os.path.join(temp_dir, "files")
        db_dir = os.path.join(temp_dir, "db")
        os.makedirs(files_dir)
        os.makedirs(db_dir)
        
        # Create a dummy txt file
        txt_path = os.path.join(files_dir, "dummy.txt")
        with open(txt_path, "w") as f:
            f.write("This is a dummy text file for testing semantic search with machine learning.")
            
        # Create a dummy md file
        md_path = os.path.join(files_dir, "dummy.md")
        with open(md_path, "w") as f:
            f.write("# Markdown Test\nHere is some markdown content about artificial intelligence.")
            
        # Create a dummy pdf file
        pdf_path = os.path.join(files_dir, "dummy.pdf")
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        with open(pdf_path, "wb") as f:
            writer.write(f)
            
        yield {
            "files_dir": files_dir,
            "db_dir": db_dir,
            "txt_path": txt_path,
            "md_path": md_path,
            "pdf_path": pdf_path
        }

def test_ingest_files(temp_workspace):
    files_dir = temp_workspace["files_dir"]
    db_dir = temp_workspace["db_dir"]
    
    count = ingest_directory(files_dir, db_path=db_dir, collection_name="test_collection")
    
    assert count >= 2
    
    client = get_db_client(db_dir)
    collection = client.get_collection("test_collection")
    assert collection.count() == count

def test_chunk_text_edge_cases():
    text = "abcdefghij"
    assert len(chunk_text(text, chunk_size=4, overlap=2)) == 5
    
    chunks = chunk_text(text, chunk_size=4, overlap=4)
    assert len(chunks) == 7

def test_search(temp_workspace):
    files_dir = temp_workspace["files_dir"]
    db_dir = temp_workspace["db_dir"]
    
    empty_results = search("", db_path=db_dir, collection_name="test_collection")
    assert len(empty_results) == 0
    
    ingest_directory(files_dir, db_path=db_dir, collection_name="test_collection")
    
    results = search("machine learning", db_path=db_dir, collection_name="test_collection")
    assert len(results) > 0
    assert any("machine learning" in res["document"] for res in results)
    
    for res in results:
        assert "id" in res
        assert "distance" in res
        assert "document" in res
        assert "metadata" in res
    
    results = search("artificial intelligence", db_path=db_dir, collection_name="test_collection")
    assert len(results) > 0
    assert any("artificial intelligence" in res["document"] for res in results)
    
    results = search("artificial intelligence", db_path=db_dir, collection_name="test_collection", metadata_filter={"extension": ".md"})
    assert len(results) > 0
    for res in results:
        assert res["metadata"]["extension"] == ".md"
        
    results_ml = search("machine learning", db_path=db_dir, collection_name="test_collection", metadata_filter={"extension": ".md"})
    if results_ml:
        for res in results_ml:
            assert res["metadata"]["extension"] == ".md"
